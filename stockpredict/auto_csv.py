"""Read published close-only CSV snapshots from this repository's fixed data branch.

The manifest selects immutable paths. Dates, file hashes, sizes and observations
are checked before any prices reach the model. Missing current-session data never
falls back to an older snapshot or to another upstream provider.
"""

import hashlib
import json
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from math import ceil
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from stockpredict.calendar import available_at, is_session
from stockpredict.data import DataSourceError, parse_csv
from stockpredict.reference_profiles import FACTOR_LABELS, FACTOR_PAIRS

BASE_URL = "https://raw.githubusercontent.com/suyanzan/StockPredict/market-data/"
SYMBOLS = tuple(FACTOR_LABELS)
MANIFEST_TTL = 300
ERROR_TTL = 60
MAX_CACHE_SIZE = 4
MANIFEST_LIMIT = 32_000
CSV_LIMIT = 2_000_000
HTTP_TIMEOUT = 8
_LOCK = Lock()
_MANIFEST: tuple[float, dict] | None = None
_CACHE: OrderedDict[tuple[str, tuple[str, str]], dict[str, list[dict]]] = OrderedDict()
_ERRORS: OrderedDict[tuple[tuple[str, str], str], tuple[float, str, int | None]] = OrderedDict()


def _allowed_url(url: str) -> bool:
    parsed = urlsplit(url)
    prefix = "/suyanzan/StockPredict/market-data/"
    relative = parsed.path.removeprefix(prefix)
    known_path = relative == "manifest.json" or bool(
        re.fullmatch(
            r"snapshots/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{16}/(?:UMC|TSM|SOXX|SPY|QQQ)\.csv",
            relative,
        )
    )
    return (
        parsed.scheme == "https"
        and parsed.netloc == "raw.githubusercontent.com"
        and parsed.path.startswith(prefix)
        and known_path
        and not parsed.query
        and not parsed.fragment
    )


class _SnapshotRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl):
            raise URLError("CSV redirect is outside the configured source")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = build_opener(_SnapshotRedirect())


def _urlopen(request: Request, timeout: int):
    return _OPENER.open(request, timeout=timeout)


def _clock() -> float:
    return time.monotonic()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def clear_cache() -> None:
    global _MANIFEST
    with _LOCK:
        _MANIFEST = None
        _CACHE.clear()
        _ERRORS.clear()


def _error(code: str, *, http_status: int | None = None, retry_after: int = ERROR_TTL):
    return DataSourceError(
        "自動收盤資料暫時無法使用，請稍後重試或手動匯入對應 CSV。",
        code=code,
        http_status=http_status,
        retry_after=retry_after,
    )


def _download(url: str, limit: int) -> bytes:
    if not _allowed_url(url):
        raise _error("auto_csv_invalid_data")
    request = Request(
        url,
        headers={"User-Agent": "StockPredict/0.1", "Accept": "application/json,text/csv"},
    )
    try:
        with _urlopen(request, timeout=HTTP_TIMEOUT) as response:
            if not _allowed_url(response.geturl()):
                raise _error("auto_csv_invalid_data")
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise _error("auto_csv_invalid_data")
        return raw
    except DataSourceError:
        raise
    except HTTPError as exc:
        raise _error("auto_csv_unavailable", http_status=exc.code) from None
    except (URLError, TimeoutError, OSError):
        raise _error("auto_csv_unavailable") from None


def _iso_day(value) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Invalid session date")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Invalid session date")
    return parsed


def _validated_manifest(raw: bytes) -> dict:
    try:
        manifest = json.loads(raw)
        if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int:
            raise ValueError("Invalid manifest")
        if manifest["schema_version"] != 1:
            raise ValueError("Unsupported schema")
        session = _iso_day(manifest["session_date"])
        if not is_session(session, "XNYS"):
            raise ValueError("Not a regular US weekday")
        snapshot = manifest["snapshot_id"]
        if not isinstance(snapshot, str) or not re.fullmatch(
            re.escape(session.isoformat()) + r"-[0-9a-f]{16}", snapshot
        ):
            raise ValueError("Invalid immutable snapshot")
        generated = manifest["generated_at"]
        if not isinstance(generated, str) or len(generated) > 64 or "T" not in generated:
            raise ValueError("Invalid publication time")
        generated_at = datetime.fromisoformat(generated)
        close_available = available_at(session, "XNYS")
        if (
            generated_at.tzinfo is None
            or generated_at.utcoffset() is None
            or generated_at < close_available
            or generated_at > _now() + timedelta(minutes=5)
        ):
            raise ValueError("Invalid publication time")
        source = manifest["source"]
        expected_source = {
            "provider": "Yahoo Finance",
            "currency": "USD",
            "price_type": "unadjusted_close",
            "session_timezone": "America/New_York",
        }
        if not isinstance(source, dict) or any(
            source.get(k) != v for k, v in expected_source.items()
        ):
            raise ValueError("Invalid source metadata")
        files = manifest["files"]
        if not isinstance(files, dict) or set(files) != set(SYMBOLS):
            raise ValueError("Unexpected symbols")
        for symbol in SYMBOLS:
            item = files[symbol]
            if (
                not isinstance(item, dict)
                or item.get("path") != f"snapshots/{snapshot}/{symbol}.csv"
            ):
                raise ValueError("Invalid snapshot path")
            digest = item.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid file digest")
            if type(item.get("rows")) is not int or not 60 <= item["rows"] <= 5000:
                raise ValueError("Invalid row count")
            first, last = _iso_day(item["first_date"]), _iso_day(item["last_date"])
            if first > last or last != session:
                raise ValueError("Invalid file dates")
        return manifest
    except (ValueError, TypeError, KeyError, OverflowError):
        raise _error("auto_csv_invalid_data") from None


def _manifest() -> dict:
    global _MANIFEST
    if _MANIFEST and _MANIFEST[0] > _clock():
        return _MANIFEST[1]
    manifest = _validated_manifest(_download(BASE_URL + "manifest.json", MANIFEST_LIMIT))
    _MANIFEST = (_clock() + MANIFEST_TTL, manifest)
    return manifest


def _prices(symbol: str, manifest: dict) -> list[dict]:
    item = manifest["files"][symbol]
    raw = _download(BASE_URL + item["path"], CSV_LIMIT)
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise _error("auto_csv_invalid_data")
    try:
        points = parse_csv(raw.decode("utf-8"))
        if (
            len(points) != item["rows"]
            or points[0]["date"] != item["first_date"]
            or points[-1]["date"] != item["last_date"]
        ):
            raise ValueError("CSV disagrees with its manifest")
        return points
    except (ValueError, UnicodeError):
        raise _error("auto_csv_invalid_data") from None


def auto_csv_factors(
    factor_symbols: tuple[str, str], required_session_date: str
) -> tuple[dict[str, list[dict]], dict]:
    """Return only a verified snapshot for the exact required US trading date."""
    if not isinstance(factor_symbols, tuple) or factor_symbols not in FACTOR_PAIRS:
        raise ValueError("Unsupported reference-factor pair.")
    required = _iso_day(required_session_date).isoformat()
    if not _LOCK.acquire(timeout=2):
        raise _error("auto_csv_unavailable", retry_after=2)
    try:
        error_key = (factor_symbols, required)
        failure = _ERRORS.get(error_key)
        if failure and failure[0] > _clock():
            raise _error(
                failure[1], http_status=failure[2], retry_after=ceil(failure[0] - _clock())
            )
        try:
            manifest = _manifest()
            if manifest["session_date"] != required:
                raise _error("auto_csv_missing_session")
            cache_key = (manifest["snapshot_id"], factor_symbols)
            factors = _CACHE.get(cache_key)
            if factors is None:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = {
                        symbol: pool.submit(_prices, symbol, manifest) for symbol in factor_symbols
                    }
                    factors = {symbol: future.result() for symbol, future in futures.items()}
                _CACHE[cache_key] = factors
                _CACHE.move_to_end(cache_key)
                while len(_CACHE) > MAX_CACHE_SIZE:
                    _CACHE.popitem(last=False)
            else:
                _CACHE.move_to_end(cache_key)
        except DataSourceError as exc:
            _ERRORS[error_key] = (_clock() + ERROR_TTL, exc.code, exc.http_status)
            _ERRORS.move_to_end(error_key)
            while len(_ERRORS) > MAX_CACHE_SIZE:
                _ERRORS.popitem(last=False)
            raise
        _ERRORS.pop(error_key, None)
        metadata = {
            "snapshot_session_date": manifest["session_date"],
            "generated_at": manifest["generated_at"],
            "provider": "Yahoo Finance",
        }
        return deepcopy(factors), metadata
    finally:
        _LOCK.release()
