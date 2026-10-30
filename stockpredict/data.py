"""Validated local CSV, reproducible synthetic examples, and daily Yahoo data."""

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta
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


class DataSourceError(Exception):
    """Expected upstream failure; safe, user-facing message only."""


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
        if exc.code == 429:
            raise DataSourceError(
                "Yahoo 已限流（HTTP 429）。上市台股請改用「證交所每日行情」，"
                "美股請稍後重試或匯入 CSV。"
            ) from exc
        if exc.code == 404:
            raise DataSourceError("Yahoo 找不到此股票代號，請確認市場後綴。") from exc
        raise DataSourceError(
            f"Yahoo 行情暫時無法使用（HTTP {exc.code}），請改用 CSV 或示範資料。"
        ) from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise DataSourceError(
            "無法取得 Yahoo 行情，請檢查網路設定，或改用 CSV／示範資料。"
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
        # Today's candle may still be in flight. Keep completed previous dates only.
        today = datetime.now(timezone).date()
        points = []
        for timestamp, close in zip(timestamps, closes):
            day = datetime.fromtimestamp(timestamp, timezone).date()
            if close is not None and day < today:
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
        }
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        raise DataSourceError("Yahoo 回傳的有效資料不足或格式不符，請改用 CSV。") from exc
