"""Published 0050 daily history for the private plan page.

Yahoo rate-limits the Render host, so a GitHub Actions job fetches the history
and commits one validated JSON file to this repository's ``plan-data`` branch.
The site only reads that file; it never asks Yahoo directly for this history.

Run ``python -m stockpredict.plan_data --output-dir DIR`` to (re)build it.
"""

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from stockpredict.data import DataSourceError, yahoo_data
from stockpredict.forecast import MAX_POINTS, validate_points

SYMBOL = "0050.TW"
FILE_NAME = "0050.json"
SOURCE_URL = f"https://raw.githubusercontent.com/suyanzan/StockPredict/plan-data/{FILE_NAME}"
SOURCE = {
    "provider": "Yahoo Finance",
    "price_type": "split_adjusted_close",
    "dividends": "excluded",
}
HISTORY_YEARS = 20
MIN_HISTORY_YEARS = 10  # Yahoo's 0050.TW daily data starts later than 20 years back.
CHUNK_SECONDS = 365 * 86400  # Short windows keep Yahoo on daily candles.
REQUEST_INTERVAL = 3
RETRY_DELAYS = (30, 90)
MAX_BYTES = 400_000
HTTP_TIMEOUT = 8
TAIPEI = timezone(timedelta(hours=8))

_sleep = time.sleep


# --- Generator (GitHub Actions) ---------------------------------------------


def _window(begin: int, stop: int) -> list[dict]:
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            points, metadata = yahoo_data(SYMBOL, period=(begin, stop))
            if metadata.get("currency") not in (None, "", "TWD"):
                raise DataSourceError("Unexpected currency", code="us_invalid_data")
            return points
        except DataSourceError as exc:
            retryable = exc.code in {"us_rate_limited", "us_connection_failed", "us_unavailable"}
            if not retryable or attempt == len(RETRY_DELAYS):
                raise
            print(
                json.dumps({"status": "retrying", "reason": exc.code, "window": [begin, stop]}),
                file=sys.stderr,
            )
            _sleep(RETRY_DELAYS[attempt])
    raise AssertionError("unreachable")


def fetch_history(now: int | None = None) -> list[dict]:
    """Up to twenty years of daily closes in one-year windows, newest first, no gaps."""
    end = int(time.time()) if now is None else now
    first = end - HISTORY_YEARS * 365 * 86400
    merged: dict[str, float] = {}
    stop = end
    while stop > first:
        begin = max(first, stop - CHUNK_SECONDS)
        if merged:
            _sleep(REQUEST_INTERVAL)
        try:
            window = _window(begin, stop)
        except DataSourceError as exc:
            # An older window with no usable data marks where Yahoo's history starts.
            # Rate limits and connection failures still fail the whole run.
            if not merged or exc.code not in {"us_unavailable", "us_invalid_data"}:
                raise
            covered = date.fromisoformat(max(merged)) - date.fromisoformat(min(merged))
            if covered < timedelta(days=MIN_HISTORY_YEARS * 365):
                raise
            break
        merged.update((p["date"], p["close"]) for p in window)
        stop = begin
    points = [{"date": day, "close": float(merged[day])} for day in sorted(merged)]
    points = points[-MAX_POINTS:]
    validate_points(points)
    return points


def render(points: list[dict], generated_at: datetime) -> bytes:
    rows = ",\n".join(
        "    " + json.dumps([p["date"], float(format(p["close"], ".10g"))]) for p in points
    )
    header = {
        "schema_version": 1,
        "symbol": SYMBOL,
        "source": SOURCE,
        "generated_at": generated_at.isoformat(),
        "first_date": points[0]["date"],
        "last_date": points[-1]["date"],
        "rows": len(points),
    }
    body = json.dumps(header, indent=2, ensure_ascii=False)[:-2]
    raw = f'{body},\n  "closes": [\n{rows}\n  ]\n}}\n'.encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("Snapshot exceeds the size limit.")
    parse(raw, now=generated_at)  # Never write a file the site would reject.
    return raw


def refresh(output_dir: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    points = fetch_history(int(now.timestamp()))
    target = output_dir / FILE_NAME
    if target.exists():
        try:
            old_dates, old_closes, _ = parse(target.read_bytes(), now=now)
            new = [(p["date"], float(format(p["close"], ".10g"))) for p in points]
            if list(zip(old_dates, old_closes)) == new:
                return {"status": "unchanged", "last_date": points[-1]["date"]}
        except ValueError:
            pass  # Replace an invalid file.
    target.write_bytes(render(points, now))
    return {"status": "updated", "last_date": points[-1]["date"], "rows": len(points)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish 0050 daily history for /plan.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = refresh(args.output_dir)
    except DataSourceError as exc:
        print(json.dumps({"status": "unavailable", "reason": exc.code}))
        print(f"::error title=0050 history unavailable::{exc.code}")
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"status": "unavailable", "reason": "snapshot_generation_failed"}))
        print("::error title=0050 history snapshot failed::snapshot_generation_failed")
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


# --- Reader (website) -------------------------------------------------------


def parse(raw: bytes, now: datetime | None = None) -> tuple[list[str], list[float], dict]:
    """Validate a published snapshot; raise ValueError on any inconsistency."""
    now = now or datetime.now(timezone.utc)
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("Unsupported snapshot")
        if payload.get("symbol") != SYMBOL or payload.get("source") != SOURCE:
            raise ValueError("Unexpected snapshot source")
        generated = datetime.fromisoformat(payload["generated_at"])
        if generated.utcoffset() is None or generated > now + timedelta(minutes=5):
            raise ValueError("Invalid publication time")
        rows = payload["closes"]
        if not isinstance(rows, list) or any(
            not isinstance(row, list) or len(row) != 2 for row in rows
        ):
            raise ValueError("Invalid price rows")
        points = [{"date": row[0], "close": row[1]} for row in rows]
        if any(type(p["close"]) not in (int, float) or type(p["date"]) is not str for p in points):
            raise ValueError("Invalid price rows")
        validate_points(points)
        if (
            payload.get("rows") != len(points)
            or payload.get("first_date") != points[0]["date"]
            or payload.get("last_date") != points[-1]["date"]
            or date.fromisoformat(points[-1]["date"]) > generated.astimezone(TAIPEI).date()
        ):
            raise ValueError("Snapshot disagrees with its header")
    except (KeyError, TypeError, OverflowError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid snapshot") from exc
    metadata = {"generated_at": payload["generated_at"], "provider": SOURCE["provider"]}
    return [p["date"] for p in points], [float(p["close"]) for p in points], metadata


class _FixedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl != SOURCE_URL:
            raise URLError("Snapshot redirect is outside the configured source")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = build_opener(_FixedRedirect())


def _download() -> bytes:
    assert urlsplit(SOURCE_URL).netloc == "raw.githubusercontent.com"
    request = Request(SOURCE_URL, headers={"User-Agent": "StockPredict/0.1"})
    try:
        with _OPENER.open(request, timeout=HTTP_TIMEOUT) as response:
            raw = response.read(MAX_BYTES + 1)
    except HTTPError as exc:
        raise DataSourceError(
            "0050 歷史資料快照暫時無法使用。", code="auto_csv_unavailable", http_status=exc.code
        ) from None
    except (URLError, TimeoutError, OSError):
        raise DataSourceError(
            "0050 歷史資料快照暫時無法使用。", code="auto_csv_unavailable"
        ) from None
    if len(raw) > MAX_BYTES:
        raise DataSourceError("0050 歷史資料快照格式不符。", code="auto_csv_invalid_data")
    return raw


def load_history() -> tuple[list[str], list[float], dict]:
    raw = _download()
    try:
        return parse(raw)
    except ValueError:
        raise DataSourceError("0050 歷史資料快照格式不符。", code="auto_csv_invalid_data") from None


if __name__ == "__main__":
    raise SystemExit(main())
