"""Bounded server-side downloads for the two opt-in US reference factors."""

import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime
from math import ceil
from threading import Lock
from zoneinfo import ZoneInfo

from stockpredict.data import DataSourceError, yahoo_data
from stockpredict.reference_profiles import FACTOR_PAIRS

SYMBOLS = ("UMC", "SOXX")
CACHE_TTL = 300
ERROR_TTL = 60
MAX_CACHE_SIZE = 4
_LOCK = Lock()
_CACHE: OrderedDict[tuple[str, str], tuple[date, float, dict[str, list[dict]]]] = OrderedDict()
_ERRORS: OrderedDict[tuple[str, str], tuple[float, str, int | None]] = OrderedDict()
_ERROR: tuple[float, str, int | None] | None = None


def _today() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _clock() -> float:
    return time.monotonic()


def clear_cache() -> None:
    global _ERROR
    with _LOCK:
        _CACHE.clear()
        _ERRORS.clear()
        _ERROR = None


def _factor(symbol: str) -> list[dict]:
    points, metadata = yahoo_data(symbol)
    if metadata.get("currency") != "USD" or metadata.get("exchange_timezone") != "America/New_York":
        raise DataSourceError(
            "美股參考資料的幣別或交易所時區不符，請稍後再試。", code="us_invalid_data"
        )
    return points


def overnight_factors(factor_symbols: tuple[str, str] = SYMBOLS) -> dict[str, list[dict]]:
    """Coalesce callers, cache five minutes, and never return expired data on error."""
    global _ERROR
    if not isinstance(factor_symbols, tuple) or factor_symbols not in FACTOR_PAIRS:
        raise ValueError("Unsupported reference-factor pair.")
    if not _LOCK.acquire(timeout=2):
        raise DataSourceError("美股參考資料正在讀取中，請稍後再試。", code="us_busy", retry_after=2)
    try:
        today, now = _today(), _clock()
        cached = _CACHE.get(factor_symbols)
        if cached and cached[0] == today and cached[1] > now:
            _CACHE.move_to_end(factor_symbols)
            return deepcopy(cached[2])
        failure = _ERROR if _ERROR and _ERROR[0] > now else _ERRORS.get(factor_symbols)
        if failure and failure[0] > now:
            raise DataSourceError(
                "美股參考資料暫時無法取得，請稍後再試。",
                code=failure[1],
                http_status=failure[2],
                retry_after=ceil(failure[0] - now),
            )
        if _ERROR and _ERROR[0] <= now:
            _ERROR = None
        downloaded, failures = {}, []
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {symbol: pool.submit(_factor, symbol) for symbol in factor_symbols}
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
            error = (_clock() + cooldown, failure.code, failure.http_status)
            if failure.code == "us_rate_limited":
                _ERROR = error
            _ERRORS[factor_symbols] = error
            _ERRORS.move_to_end(factor_symbols)
            while len(_ERRORS) > MAX_CACHE_SIZE:
                _ERRORS.popitem(last=False)
            raise DataSourceError(
                str(failure),
                code=failure.code,
                http_status=failure.http_status,
                retry_after=cooldown,
            ) from failure
        _CACHE[factor_symbols] = (today, _clock() + CACHE_TTL, downloaded)
        _CACHE.move_to_end(factor_symbols)
        while len(_CACHE) > MAX_CACHE_SIZE:
            _CACHE.popitem(last=False)
        _ERRORS.pop(factor_symbols, None)
        return deepcopy(downloaded)
    finally:
        _LOCK.release()
