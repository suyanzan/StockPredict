"""Read-only Taiwan stock preflight. This module never enrolls a collector."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from stockpredict.calendar import date_path, is_session, latest_published, previous_session
from stockpredict.data import DataSourceError
from stockpredict.forecast import forecast_path, validate_points
from stockpredict.scoreboard import SYMBOLS, capture_reason
from stockpredict.twse import normalize_twse_symbol, twse_data

router = APIRouter()


def preflight(symbol, now=None):
    now = now or datetime.now(timezone.utc)
    expected = latest_published(now)
    points, metadata = twse_data(symbol)
    points = [p for p in points if date.fromisoformat(p["date"]) <= expected]
    checks = {}
    try:
        validate_points(points)
        checks["valid_history"] = True
    except ValueError:
        checks["valid_history"] = False
    checks["exchange_sessions"] = bool(points) and all(
        is_session(date.fromisoformat(p["date"])) for p in points
    )
    checks["latest_session"] = bool(points) and points[-1]["date"] == expected.isoformat()
    checks["previous_close"] = any(
        p["date"] == previous_session(expected).isoformat() for p in points
    )
    targets = []
    inputs_ready = all(checks.values())
    checks["five_session_path"] = False
    if inputs_ready:
        try:
            targets = [
                p["date"] for p in date_path(forecast_path(points, 5), points[-1]["date"], "XTAI")
            ]
            checks["five_session_path"] = len(targets) == 5
        except (ValueError, ArithmeticError):
            pass
    ready = all(checks.values())
    return {
        "status": "review_required" if ready else "blocked",
        "symbol": symbol,
        "name": metadata.get("name", symbol),
        "checked_at": now.isoformat(),
        "enrolled": symbol in SYMBOLS,
        "scenario": "taiwan",
        "checks": checks,
        "history_samples": len(points),
        "session_date": points[-1]["date"] if points else None,
        "expected_session_date": expected.isoformat(),
        "forecast_target_dates": targets,
        "capture_window_reason": capture_reason(points, now) if ready else None,
        "storage_verified_in_production": False,
        "remaining_steps": [
            "policy_review",
            "isolated_storage_test",
            "activation",
            "live_evidence",
        ],
        "read_only": True,
    }


@router.get("/api/collection/readiness")
def readiness(symbol: str = Query(min_length=1, max_length=20)):
    try:
        symbol = normalize_twse_symbol(symbol)
    except ValueError:
        return JSONResponse(status_code=422, content={"reason": "invalid_twse_symbol"})
    try:
        return preflight(symbol)
    except DataSourceError:
        return JSONResponse(status_code=503, content={"reason": "source_unavailable"})


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    try:
        report = preflight(normalize_twse_symbol(args.symbol))
        print(json.dumps(report, ensure_ascii=False))
        raise SystemExit(0 if report["status"] == "review_required" else 2)
    except (DataSourceError, ValueError):
        print(json.dumps({"status": "unavailable", "read_only": True}))
        raise SystemExit(2)
