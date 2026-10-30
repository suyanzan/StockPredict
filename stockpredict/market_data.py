"""Bounded server-side downloads for the two opt-in US reference factors."""

import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime
from threading import Lock
from zoneinfo import ZoneInfo

from stockpredict.data import DataSourceError, yahoo_data

SYMBOLS = ("UMC", "SOXX")
CACHE_TTL = 300
ERROR_TTL = 60
_LOCK = Lock()
_CACHE: tuple[date, float, dict[str, list[dict]]] | None = None
_error_until = 0.0


def _today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _clock() -> float:
    return time.monotonic()


def clear_cache() -> None:
    global _CACHE, _error_until
    with _LOCK:
        _CACHE = None
        _error_until = 0.0


def _factor(symbol: str) -> list[dict]:
    points, metadata = yahoo_data(symbol)
    if metadata.get("currency") != "USD" or metadata.get("exchange_timezone") != "America/New_York":
        raise DataSourceError("美股參考資料的幣別或交易所時區不符，請稍後再試。")
    return points


def overnight_factors() -> dict[str, list[dict]]:
    """Coalesce callers, cache five minutes, and never return expired data on error."""
    global _CACHE, _error_until
    if not _LOCK.acquire(timeout=2):
        raise DataSourceError("美股參考資料正在讀取中，請稍後再試。")
    try:
        today, now = _today(), _clock()
        if _CACHE and _CACHE[0] == today and _CACHE[1] > now:
            return deepcopy(_CACHE[2])
        if _error_until > now:
            raise DataSourceError("美股參考資料暫時無法取得，請稍後再試。")
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                downloaded = dict(zip(SYMBOLS, pool.map(_factor, SYMBOLS)))
        except DataSourceError:
            _error_until = _clock() + ERROR_TTL
            raise
        _CACHE = (today, _clock() + CACHE_TTL, downloaded)
        _error_until = 0.0
        return deepcopy(downloaded)
    finally:
        _LOCK.release()
