"""Validated local CSV, reproducible synthetic examples, and daily Yahoo data."""

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from math import ceil
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import numpy as np

from stockpredict.forecast import MAX_POINTS, validate_points

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9^][A-Z0-9.^=\-]{0,19}$")
EXAMPLES = {
    "2330.TW": ("台積電", "TWD", 900.0),
    "0050.TW": ("元大台灣50", "TWD", 55.0),
    "AAPL": ("Apple", "USD", 220.0),
    "MSFT": ("Microsoft", "USD", 430.0),
}
YAHOO_CLOSE_DELAY = timedelta(minutes=15)
DATA_ERROR_CODES = frozenset(
    {
        "data_unavailable",
        "us_rate_limited",
        "us_access_denied",
        "us_connection_failed",
        "us_invalid_data",
        "us_unavailable",
        "us_busy",
    }
)


class DataSourceError(Exception):
    """Expected upstream failure with bounded, safe fields for public diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "data_unavailable",
        http_status: int | None = None,
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.code = (
            code if isinstance(code, str) and code in DATA_ERROR_CODES else "data_unavailable"
        )
        self.http_status = (
            http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        )
        self.retry_after = max(1, min(retry_after, 86400)) if type(retry_after) is int else None


def normalize_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not SYMBOL_PATTERN.fullmatch(value):
        raise ValueError("股票代號格式無效，例如 2330.TW、0050.TW 或 AAPL。")
    return value


def demo_data(symbol: str) -> tuple[list[dict], dict]:
    if symbol not in EXAMPLES:
        raise ValueError(
            "示範資料支援 2330.TW、0050.TW、AAPL 與 MSFT；其他代號請使用 Yahoo 或 CSV。"
        )
    name, currency, base = EXAMPLES[symbol]
    # Synthetic data deliberately does not mimic or claim actual market prices.
    seed = int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:4], "big")
    rng = np.random.default_rng(seed)
    days = []
    day = datetime.now(ZoneInfo("Asia/Taipei")).date() - timedelta(days=1)
    while len(days) < 252:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days.reverse()
    prices = base * np.exp(np.cumsum(rng.normal(0.0004, 0.012, len(days))))
    return (
        [{"date": d.isoformat(), "close": round(float(p), 4)} for d, p in zip(days, prices)],
        {
            "name": name,
            "currency": currency,
            "source": "demo",
            "source_label": "合成示範資料（非真實行情）",
        },
    )


def parse_csv(text: str) -> list[dict]:
    if len(text.encode("utf-8")) > 2_000_000:
        raise ValueError("CSV 不可超過 2 MB。")
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
        headers = reader.fieldnames
        if not headers:
            raise ValueError("CSV 必須包含 Date 與 Close 欄位。")
        normalized = [h.strip().lower() for h in headers]
        if len(set(normalized)) != len(normalized):
            raise ValueError("CSV 欄位名稱不可重複。")
        if "date" not in normalized or "close" not in normalized:
            raise ValueError("CSV 必須包含 Date 與 Close 欄位。")
        date_header = headers[normalized.index("date")]
        close_header = headers[normalized.index("close")]
        points = []
        for line, row in enumerate(reader, start=2):
            if len(points) >= MAX_POINTS:
                raise ValueError(f"CSV 不可超過 {MAX_POINTS} 筆資料。")
            if None in row:
                raise ValueError(f"第 {line} 列欄位數與標題不符。")
            try:
                day_text = row[date_header].strip()
                day = date.fromisoformat(day_text)
                if day.isoformat() != day_text:
                    raise ValueError("日期格式")
                close = float(row[close_header])
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f"第 {line} 列需要 YYYY-MM-DD 日期與有效收盤價。") from exc
            points.append({"date": day.isoformat(), "close": close})
    except csv.Error as exc:
        raise ValueError("CSV 格式無法解析，請確認逗號、引號與換行。") from exc
    points.sort(key=lambda p: p["date"])
    validate_points(points)
    return points


def _now(timezone: ZoneInfo) -> datetime:
    return datetime.now(timezone)


def _retry_after(value: str | None) -> int | None:
    """Parse a provider's retry hint without forwarding arbitrary header text."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value):
        # Large digit strings still mean wait at least our bounded maximum;
        # do not pass them to int(), which limits excessive decimal input.
        digits = value.lstrip("0") or "0"
        return min(int(digits), 86400) if len(digits) <= 5 else 86400
    try:
        when = parsedate_to_datetime(value)
        if when.tzinfo is None or when.utcoffset() is None:
            return None
        return max(0, min(ceil((when - _now(ZoneInfo("UTC"))).total_seconds()), 86400))
    except (TypeError, ValueError, OverflowError):
        return None


def _today_session_completed(meta: dict, now: datetime) -> bool:
    """Use Yahoo's session schedule, including early closes and DST.

    Wait an additional fifteen minutes before trusting a same-day daily candle.
    Missing, malformed, or another day's schedule keeps today's candle excluded.
    This is a conservative application policy, not a promise of publication time.
    """
    try:
        if not isinstance(meta.get("exchangeTimezoneName"), str):
            return False
        session = meta["currentTradingPeriod"]["regular"]
        start, end = session["start"], session["end"]
        if type(start) is not int or type(end) is not int or not 0 < end - start <= 86400:
            return False
        opens = datetime.fromtimestamp(start, now.tzinfo)
        closes = datetime.fromtimestamp(end, now.tzinfo)
        return opens.date() == closes.date() == now.date() and now >= closes + YAHOO_CLOSE_DELAY
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return False


def yahoo_data(symbol: str) -> tuple[list[dict], dict]:
    """Daily closes, never silently fall back to synthetic data on failure."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
        "?range=2y&interval=1d"
    )
    request = Request(url, headers={"User-Agent": "StockPredict/0.1", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read(5_000_001))
    except HTTPError as exc:
        retry_after = _retry_after(exc.headers.get("Retry-After") if exc.headers else None)
        if exc.code == 429:
            raise DataSourceError(
                "Yahoo 已限流（HTTP 429）。上市台股請改用「證交所每日行情」，"
                "美股請稍後重試或匯入 CSV。",
                code="us_rate_limited",
                http_status=429,
                retry_after=max(60, retry_after if retry_after is not None else 300),
            ) from exc
        if exc.code == 404:
            raise DataSourceError(
                "Yahoo 找不到此股票代號，請確認市場後綴。",
                code="us_unavailable",
                http_status=404,
                retry_after=retry_after,
            ) from exc
        raise DataSourceError(
            f"Yahoo 行情暫時無法使用（HTTP {exc.code}），請改用 CSV 或示範資料。",
            code="us_access_denied" if exc.code in (401, 403) else "us_unavailable",
            http_status=exc.code,
            retry_after=retry_after,
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise DataSourceError(
            "無法取得 Yahoo 行情，請檢查網路設定，或改用 CSV／示範資料。",
            code="us_connection_failed",
        ) from exc
    except ValueError as exc:
        raise DataSourceError(
            "Yahoo 回傳的有效資料不足或格式不符，請改用 CSV。", code="us_invalid_data"
        ) from exc
    try:
        if not isinstance(payload, dict):
            raise ValueError("invalid upstream payload")
        chart = payload["chart"]
        if not isinstance(chart, dict):
            raise ValueError("invalid upstream chart")
        if chart.get("error") or not chart.get("result"):
            raise ValueError("upstream chart error")
        if not isinstance(chart["result"], list):
            raise ValueError("invalid upstream results")
        result = chart["result"][0]
        if not isinstance(result, dict):
            raise ValueError("invalid upstream result")
        meta = result["meta"]
        if not isinstance(meta, dict):
            raise ValueError("invalid upstream metadata")
        timezone = ZoneInfo(meta.get("exchangeTimezoneName", "UTC"))
        closes = result["indicators"]["quote"][0]["close"]
        timestamps = result["timestamp"]
        if not isinstance(closes, list) or not isinstance(timestamps, list):
            raise ValueError("invalid upstream price series")
        if len(closes) != len(timestamps):
            raise ValueError("mismatched timestamps and prices")
        # A daily candle is mutable while the exchange session is in progress.
        now = _now(timezone)
        today = now.date()
        include_today = _today_session_completed(meta, now)
        points = []
        for timestamp, close in zip(timestamps, closes):
            day = datetime.fromtimestamp(timestamp, timezone).date()
            if close is not None and (day < today or (include_today and day == today)):
                points.append({"date": day.isoformat(), "close": float(close)})
        points.sort(key=lambda p: p["date"])
        validate_points(points)
        name = next(
            (
                value
                for value in (meta.get("longName"), meta.get("shortName"))
                if isinstance(value, str) and value.strip()
            ),
            symbol,
        )
        currency = meta.get("currency", "")
        return points, {
            "name": name,
            "currency": currency if isinstance(currency, str) else "",
            "source": "yahoo",
            "source_label": "Yahoo Finance 每日收盤價（非即時、未還原權息）",
            "exchange_timezone": timezone.key,
        }
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        raise DataSourceError(
            "Yahoo 回傳的有效資料不足或格式不符，請改用 CSV。", code="us_invalid_data"
        ) from exc
