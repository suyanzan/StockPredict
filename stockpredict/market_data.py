"""Bounded server-side downloads for the two opt-in US reference factors."""

import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime
from math import ceil
from threading import Lock
from zoneinfo import ZoneInfo

from stockpredict.data import DataSourceError, yahoo_data

SYMBOLS = ("UMC", "SOXX")
CACHE_TTL = 300
ERROR_TTL = 60
_LOCK = Lock()
_CACHE: tuple[date, float, dict[str, list[dict]]] | None = None
_ERROR: tuple[float, str, int | None] | None = None


def _today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _clock() -> float:
    return time.monotonic()


def clear_cache() -> None:
    global _CACHE, _ERROR
    with _LOCK:
        _CACHE = None
        _ERROR = None


def _factor(symbol: str) -> list[dict]:
    points, metadata = yahoo_data(symbol)
    if metadata.get("currency") != "USD" or metadata.get("exchange_timezone") != "America/New_York":
        raise DataSourceError(
            "美股參考資料的幣別或交易所時區不符，請稍後再試。", code="us_invalid_data"
        )
    return points


def overnight_factors() -> dict[str, list[dict]]:
    """Coalesce callers, cache five minutes, and never return expired data on error."""
    global _CACHE, _ERROR
    if not _LOCK.acquire(timeout=2):
        raise DataSourceError("美股參考資料正在讀取中，請稍後再試。", code="us_busy", retry_after=2)
    try:
        today, now = _today(), _clock()
        if _CACHE and _CACHE[0] == today and _CACHE[1] > now:
            return deepcopy(_CACHE[2])
        if _ERROR and _ERROR[0] > now:
            raise DataSourceError(
                "美股參考資料暫時無法取得，請稍後再試。",
                code=_ERROR[1],
                http_status=_ERROR[2],
                retry_after=ceil(_ERROR[0] - now),
            )
        downloaded, failures = {}, []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {symbol: pool.submit(_factor, symbol) for symbol in SYMBOLS}
            for symbol, future in pending.items():
                try:
                    downloaded[symbol] = future.result()
                except DataSourceError as exc:
                    failures.append(exc)
        if failures:
            # Wait long enough for both responses, while retaining a rate-limit
            # diagnosis even if the other request failed for a different reason.
            failure = next((e for e in failures if e.code == "us_rate_limited"), failures[0])
            cooldown = max(
                max(ERROR_TTL, e.retry_after or (300 if e.code == "us_rate_limited" else ERROR_TTL))
                for e in failures
            )
            _ERROR = (_clock() + cooldown, failure.code, failure.http_status)
            raise DataSourceError(
                str(failure),
                code=failure.code,
                http_status=failure.http_status,
                retry_after=cooldown,
            ) from failure
        _CACHE = (today, _clock() + CACHE_TTL, downloaded)
        _ERROR = None
        return deepcopy(downloaded)
    finally:
        _LOCK.release()
