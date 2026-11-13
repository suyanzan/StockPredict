"""Publish one bounded, complete daily CSV snapshot for the five reference symbols.

This command is intended for a scheduled job, not a web request. It makes
bounded, paced requests per symbol and publishes nothing
unless every symbol includes the required completed New York trading date.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from stockpredict.calendar import available_at, is_session, latest_published
from stockpredict.data import DataSourceError, parse_csv, yahoo_data
from stockpredict.forecast import validate_points

SYMBOLS = ("UMC", "TSM", "SOXX", "SPY", "QQQ")
SOURCE = {
    "provider": "Yahoo Finance",
    "currency": "USD",
    "price_type": "unadjusted_close",
    "session_timezone": "America/New_York",
}
NEW_YORK = ZoneInfo("America/New_York")
SNAPSHOT_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-f0-9]{16}$")
MAX_MANIFEST_BYTES = 32_000
MAX_CSV_BYTES = 2_000_000
PRIOR_SNAPSHOTS = 5
REQUEST_INTERVAL = 3.0
_sleep = time.sleep


def _download(symbol: str, session_date: str, attempts: int):
    for attempt in range(1, attempts + 1):
        details = {"symbol": symbol, "expected_session": session_date, "attempt": attempt}
        try:
            points, metadata = yahoo_data(symbol)
            validate_points(points)
            details.update(
                actual_session=points[-1]["date"],
                currency=metadata.get("currency"),
                exchange_timezone=metadata.get("exchange_timezone"),
            )
            if (
                metadata.get("currency") != "USD"
                or metadata.get("exchange_timezone") != NEW_YORK.key
            ):
                raise DataSourceError("Unexpected market metadata", code="us_invalid_data")
            if points[-1]["date"] != session_date:
                raise DataSourceError("Completed close is unavailable", code="us_unavailable")
            return points
        except DataSourceError as exc:
            delay = max(60, exc.retry_after or 0)
            retryable = (
                exc.code in {"us_unavailable", "us_connection_failed", "us_rate_limited"}
                and (exc.http_status is None or exc.http_status == 429 or exc.http_status >= 500)
                and delay <= 120
                and details.get("actual_session", session_date) <= session_date
            )
            retry = retryable and attempt < attempts
            print(
                json.dumps(
                    {
                        **details,
                        "status": "retrying" if retry else "unavailable",
                        "reason": exc.code,
                        "http_status": exc.http_status,
                        "retry_after_seconds": exc.retry_after,
                        "next_attempt_seconds": delay if retry else None,
                    }
                ),
                file=sys.stderr,
            )
            if not retry:
                raise
            _sleep(delay)


def _csv_bytes(points: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(("Date", "Close"))
    writer.writerows((point["date"], format(float(point["close"]), ".17g")) for point in points)
    raw = stream.getvalue().encode("utf-8")
    if len(raw) > MAX_CSV_BYTES:
        raise ValueError("CSV exceeds the snapshot size limit.")
    return raw


def _snapshot_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for symbol in SYMBOLS:
        digest.update((symbol + "\n").encode("ascii"))
        digest.update(files[symbol])
    return digest.hexdigest()[:16]


def _current_manifest(root: Path, session_date: str, now: datetime) -> dict | None:
    """Only skip network work for an intact snapshot, never a date label alone."""
    path = root / "manifest.json"
    try:
        if path.is_symlink() or path.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        manifest = json.loads(path.read_bytes())
        if (
            type(manifest["schema_version"]) is not int
            or manifest["schema_version"] != 1
            or manifest["session_date"] != session_date
            or manifest["source"] != SOURCE
            or set(manifest["files"]) != set(SYMBOLS)
        ):
            return None
        snapshot_id = manifest["snapshot_id"]
        if (
            not isinstance(snapshot_id, str)
            or not SNAPSHOT_PATTERN.fullmatch(snapshot_id)
            or not snapshot_id.startswith(session_date + "-")
        ):
            return None
        generated = datetime.fromisoformat(manifest["generated_at"])
        threshold = available_at(date.fromisoformat(session_date), "XNYS")
        if (
            generated.tzinfo is None
            or generated.utcoffset() is None
            or generated < threshold
            or generated > now + timedelta(minutes=5)
        ):
            return None
        snapshot_path = root / "snapshots" / snapshot_id
        if (root / "snapshots").is_symlink() or snapshot_path.is_symlink():
            return None
        contents = {}
        for symbol in SYMBOLS:
            record = manifest["files"][symbol]
            expected_path = f"snapshots/{snapshot_id}/{symbol}.csv"
            if record["path"] != expected_path:
                return None
            csv_path = root / expected_path
            if csv_path.is_symlink() or csv_path.stat().st_size > MAX_CSV_BYTES:
                return None
            raw = csv_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != record["sha256"]:
                return None
            points = parse_csv(raw.decode("utf-8"))
            if (
                type(record["rows"]) is not int
                or len(points) != record["rows"]
                or points[0]["date"] != record["first_date"]
                or points[-1]["date"] != record["last_date"]
                or record["last_date"] != session_date
            ):
                return None
            contents[symbol] = raw
        if snapshot_id != session_date + "-" + _snapshot_digest(contents):
            return None
        return manifest
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        return None


def _prune_snapshots(root: Path, current_id: str) -> None:
    snapshots = root / "snapshots"
    prior = sorted(
        (
            path
            for path in snapshots.iterdir()
            if path.name != current_id
            and SNAPSHOT_PATTERN.fullmatch(path.name)
            and path.is_dir()
            and not path.is_symlink()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    for path in prior[PRIOR_SNAPSHOTS:]:
        shutil.rmtree(path)


def refresh(
    output_dir: Path | str,
    *,
    now: datetime | None = None,
    attempts: int = 1,
    latest_completed: bool = False,
) -> dict:
    """Generate all five CSVs, then atomically publish their immutable manifest.

    A successful return has status updated/already_current. Waiting or weekends
    return without touching files or contacting Yahoo. Exhausted upstream errors
    propagate so the caller can avoid committing or publishing any changes.
    """
    if not 1 <= attempts <= 3:
        raise ValueError("attempts must be between 1 and 3.")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone.")
    local_now = now.astimezone(NEW_YORK)
    session = latest_published(now, "XNYS") if latest_completed else local_now.date()
    session_date = session.isoformat()
    if not is_session(session, "XNYS"):
        return {"status": "no_session", "session_date": session_date}
    threshold = available_at(session, "XNYS")
    if local_now < threshold:
        return {"status": "waiting", "session_date": session_date}
    root = Path(output_dir)
    if root.is_symlink():
        raise ValueError("Output directory must not be a symbolic link.")
    current = _current_manifest(root, session_date, now)
    if current is not None:
        return {
            "status": "already_current",
            "session_date": session_date,
            "snapshot_id": current["snapshot_id"],
        }

    contents, rows = {}, {}
    for index, symbol in enumerate(SYMBOLS):
        if index:
            _sleep(REQUEST_INTERVAL)
        points = _download(symbol, session_date, attempts)
        contents[symbol] = _csv_bytes(points)
        rows[symbol] = points

    snapshot_id = session_date + "-" + _snapshot_digest(contents)
    manifest = {
        "schema_version": 1,
        "session_date": session_date,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "snapshot_id": snapshot_id,
        "source": dict(SOURCE),
        "files": {
            symbol: {
                "path": f"snapshots/{snapshot_id}/{symbol}.csv",
                "sha256": hashlib.sha256(contents[symbol]).hexdigest(),
                "rows": len(rows[symbol]),
                "first_date": rows[symbol][0]["date"],
                "last_date": rows[symbol][-1]["date"],
            }
            for symbol in SYMBOLS
        },
    }
    root.mkdir(parents=True, exist_ok=True)
    snapshots = root / "snapshots"
    if snapshots.is_symlink() or (snapshots.exists() and not snapshots.is_dir()):
        raise ValueError("Snapshot directory is invalid.")
    snapshots.mkdir(exist_ok=True)
    destination = snapshots / snapshot_id
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError("Existing snapshot path is invalid.")
        # The content hash names an immutable path; do not replace incompatible
        # bytes that might already have been cached under that name.
        for symbol in SYMBOLS:
            existing = destination / f"{symbol}.csv"
            if existing.is_symlink() or existing.read_bytes() != contents[symbol]:
                raise ValueError("Existing snapshot has incompatible contents.")
    else:
        with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=snapshots) as temporary:
            staging = Path(temporary) / snapshot_id
            staging.mkdir()
            for symbol in SYMBOLS:
                (staging / f"{symbol}.csv").write_bytes(contents[symbol])
            os.replace(staging, destination)
    temporary_manifest = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=root, delete=False
        ) as output:
            temporary_manifest = Path(output.name)
            json.dump(manifest, output, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_manifest, root / "manifest.json")
        temporary_manifest = None
    finally:
        if temporary_manifest is not None:
            temporary_manifest.unlink(missing_ok=True)
    _prune_snapshots(root, snapshot_id)
    return {"status": "updated", "session_date": session_date, "snapshot_id": snapshot_id}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh completed US reference-price CSVs.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--attempts", type=int, choices=range(1, 4), default=3)
    parser.add_argument(
        "--latest-completed",
        action="store_true",
        help="Recover the most recent published exchange session, including before open/weekends.",
    )
    args = parser.parse_args()
    try:
        result = refresh(
            args.output_dir, attempts=args.attempts, latest_completed=args.latest_completed
        )
    except DataSourceError as exc:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": exc.code,
                    "http_status": exc.http_status,
                    "retry_after_seconds": exc.retry_after,
                }
            )
        )
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"status": "unavailable", "reason": "snapshot_generation_failed"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
