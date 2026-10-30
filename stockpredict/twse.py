"""TWSE listed-security daily closes, with conservative pacing and bounded caching.

The official STOCK_DAY endpoint returns one calendar month per request. Never
replace an upstream failure with synthetic or stale prices.
"""

import json
import re
import time
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from stockpredict.data import DataSourceError
from stockpredict.forecast import MAX_PRICE, MIN_PRICE, validate_points

CACHE_TTL = 3600
PENDING_CLOSE_TTL = 300
CLOSE_AVAILABLE_HOUR = 15
ERROR_TTL = 60
MAX_CACHE_SIZE = 64
REQUEST_INTERVAL = 3.0
MAX_MONTHS = 6
TARGET_POINTS = 100

_LOCK = Lock()
_CACHE: OrderedDict[str, tuple[tuple[date, bool], float, list[dict], dict]] = OrderedDict()
_ERRORS: OrderedDict[str, tuple[float, str]] = OrderedDict()
_last_request_at: float | None = None
_sleep = time.sleep


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Taipei"))


def _clock() -> float:
    return time.monotonic()


@contextmanager
def _fetch_slot():
    # Avoid an unbounded queue behind a cold monthly download on a small server.
    if not _LOCK.acquire(timeout=2):
        raise DataSourceError("證交所資料正在讀取中，請稍候再試；也可先匯入 CSV。")
    try:
        yield
    finally:
        _LOCK.release()


def clear_cache() -> None:
    """Clear process-local caches (primarily useful for deterministic tests)."""
    global _last_request_at
    with _LOCK:
        _CACHE.clear()
        _ERRORS.clear()
        _last_request_at = None


def normalize_twse_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not re.fullmatch(r"[0-9]{4,6}(?:\.TW)?", value):
        raise ValueError(
            "證交所來源僅支援上市台股／ETF，例如 2303 或 2303.TW；"
            "上櫃 .TWO 與美股請使用 Yahoo 或 CSV。"
        )
    return value if value.endswith(".TW") else value + ".TW"


def _month_before(month: date) -> date:
    return date(month.year - (month.month == 1), 12 if month.month == 1 else month.month - 1, 1)


def _fetch_month(code: str, month: date) -> dict:
    global _last_request_at
    if _last_request_at is not None:
        remaining = REQUEST_INTERVAL - (_clock() - _last_request_at)
        if remaining > 0:
            _sleep(remaining)
    _last_request_at = _clock()
    query = urlencode({"response": "json", "date": month.strftime("%Y%m01"), "stockNo": code})
    request = Request(
        "https://www.twse.com.tw/exchangeReport/STOCK_DAY?" + query,
        headers={"User-Agent": "StockPredict/0.1", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("oversized upstream response")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("invalid response object")
        return payload
    except HTTPError as exc:
        raise DataSourceError(
            f"證交所行情暫時無法使用（HTTP {exc.code}），請稍後重試或匯入 CSV。"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise DataSourceError("無法連線至證交所，請稍後重試或匯入 CSV。") from exc
    except (ValueError, TypeError) as exc:
        raise DataSourceError("證交所回應格式無法解析，請稍後重試或匯入 CSV。") from exc


def _parse_month(
    payload: dict, code: str, month: date, today: date, include_today: bool = False
) -> tuple[list[dict], str]:
    try:
        status = payload.get("stat")
        if isinstance(status, str) and "沒有符合條件的資料" in status:
            return [], ""
        if status != "OK":
            raise ValueError("upstream status not OK")
        fields = payload["fields"]
        rows = payload["data"]
        if not isinstance(fields, list) or not isinstance(rows, list):
            raise ValueError("invalid fields or data")
        if not all(isinstance(field, str) for field in fields) or len(set(fields)) != len(fields):
            raise ValueError("invalid or duplicate fields")
        day_index, close_index = fields.index("日期"), fields.index("收盤價")
        points = []
        seen = set()
        for row in rows:
            if not isinstance(row, list) or len(row) != len(fields):
                raise ValueError("invalid row width")
            text = row[day_index]
            if not isinstance(text, str) or not re.fullmatch(r"[0-9]{2,3}/[0-9]{2}/[0-9]{2}", text):
                raise ValueError("invalid ROC date")
            year, mm, dd = (int(part) for part in text.split("/"))
            day = date(year + 1911, mm, dd)
            if day.year != month.year or day.month != month.month or day in seen:
                raise ValueError("duplicate or mismatched month")
            seen.add(day)
            if day > today or (day == today and not include_today):
                continue
            close_text = row[close_index]
            if close_text == "--":  # Suspended/no-trade sessions have no usable close.
                continue
            if not isinstance(close_text, str) or not re.fullmatch(
                r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?", close_text
            ):
                raise ValueError("invalid close")
            close = float(close_text.replace(",", ""))
            if not MIN_PRICE <= close <= MAX_PRICE:
                raise ValueError("close out of bounds")
            points.append({"date": day.isoformat(), "close": close})
        title = payload.get("title", "")
        name_match = (
            re.search(rf"{re.escape(code)}\s+(.+?)\s+各日成交資訊", title)
            if isinstance(title, str)
            else None
        )
        return points, name_match.group(1) if name_match else ""
    except (KeyError, ValueError, TypeError, IndexError, OverflowError) as exc:
        raise DataSourceError("證交所回傳資料格式不符，請稍後重試或匯入 CSV。") from exc


def _remember(mapping: OrderedDict, key: str, value: tuple) -> None:
    mapping[key] = value
    mapping.move_to_end(key)
    while len(mapping) > MAX_CACHE_SIZE:
        mapping.popitem(last=False)


def twse_data(symbol: str) -> tuple[list[dict], dict]:
    """Return up to six months of completed TWSE daily closes.

    A single lock coalesces concurrent downloads, including aliases 2303 and
    2303.TW, and enforces a process-wide three-second request spacing. Successful
    Today's official row is eligible only after our conservative 15:00 Taipei
    cutoff, which is a product policy rather than a guaranteed publication time.
    Results live one hour, except weekday post-cutoff results still missing
    today's close, which live five minutes. The cutoff and midnight invalidate
    successful caches; failures cool down for a minute. Neither cache persists.
    """
    normalized = normalize_twse_symbol(symbol)
    code = normalized.removesuffix(".TW")
    with _fetch_slot():
        local_now = _now()
        today = local_now.date()
        include_today = local_now.hour >= CLOSE_AVAILABLE_HOUR
        cache_period = (today, include_today)
        now = _clock()
        cached = _CACHE.get(code)
        if cached and cached[0] == cache_period and cached[1] > now:
            _CACHE.move_to_end(code)
            return deepcopy((cached[2], cached[3]))
        failure = _ERRORS.get(code)
        if failure and failure[0] > now:
            _ERRORS.move_to_end(code)
            raise DataSourceError(failure[1])
        try:
            month = today.replace(day=1)
            points = []
            name = ""
            for _ in range(MAX_MONTHS):
                monthly, monthly_name = _parse_month(
                    _fetch_month(code, month), code, month, today, include_today
                )
                points.extend(monthly)
                if not name and monthly_name:
                    name = monthly_name
                if len(points) >= TARGET_POINTS:
                    break
                month = _month_before(month)
            points.sort(key=lambda point: point["date"])
            try:
                validate_points(points)
            except ValueError as exc:
                raise DataSourceError(
                    "證交所近六個月有效收盤價不足 60 筆，或資料無效。"
                    "請確認為上市代碼；新上市／長期停牌股票可改用 CSV。"
                ) from exc
            metadata = {
                "name": name or f"台股 {code}",
                "currency": "TWD",
                "source": "twse",
                "source_label": "台灣證券交易所每日收盤價（未還原權息）",
            }
            awaiting_close = (
                include_today and today.weekday() < 5 and points[-1]["date"] != today.isoformat()
            )
            ttl = PENDING_CLOSE_TTL if awaiting_close else CACHE_TTL
            _remember(_CACHE, code, (cache_period, _clock() + ttl, points, metadata))
            _ERRORS.pop(code, None)
            return deepcopy((points, metadata))
        except DataSourceError as exc:
            _remember(_ERRORS, code, (_clock() + ERROR_TTL, str(exc)))
            raise
