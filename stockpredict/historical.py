"""Retrospective walk-forward evaluation, deliberately independent of the live archive."""

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from stockpredict.calendar import (
    available_at,
    date_path,
    is_session,
    opens_at,
    previous_session,
)
from stockpredict.data import DataSourceError
from stockpredict.forecast import MIN_POINTS, analyze, validate_points
from stockpredict.market_data import overnight_factors
from stockpredict.overnight import build_context
from stockpredict.reference_profiles import profile_for
from stockpredict.scoreboard import SYMBOLS, evaluate
from stockpredict.twse import twse_data

router = APIRouter()


def walk_forward(symbol, points, factors, start: date, end: date, *, factor_reason=None):
    """Fit each target using only its prefix and US bars eligible before its open.

    Actuals are evaluated separately after generating every path. Today's historic
    feeds may contain revisions; simulated cutoffs are not publication evidence.
    """
    if symbol not in SYMBOLS or not 0 <= (end - start).days <= 31:
        raise ValueError("Unsupported historical test window")
    validate_points(points)
    points = [p for p in points if p["date"] <= end.isoformat()]
    profile = profile_for(symbol)
    predictions, skipped, training = [], [], []
    target = start
    while target <= end:
        if not is_session(target):
            target += timedelta(days=1)
            continue
        prefix = [p for p in points if p["date"] < target.isoformat()]
        if len(prefix) < MIN_POINTS or prefix[-1]["date"] != str(previous_session(target)):
            skipped.append(
                {
                    "date": str(target),
                    "scenario": "all",
                    "reason": "insufficient_or_missing_training_history",
                }
            )
            target += timedelta(days=1)
            continue
        cutoff = opens_at(target) - timedelta(microseconds=1)
        base = analyze(prefix, 5)
        paths = {"taiwan": date_path(base["forecast"], prefix[-1]["date"], "XTAI")}
        # No future US rows are passed into the historical cross-market model.
        eligible = {
            code: [
                p
                for p in observations
                if p["date"] < str(target)
                and is_session(date.fromisoformat(p["date"]), "XNYS")
                and available_at(date.fromisoformat(p["date"]), "XNYS") <= cutoff
            ]
            for code, observations in (factors or {}).items()
        }
        context = (
            build_context(prefix, eligible, now=cutoff, horizon=5, factor_symbols=profile.symbols)
            if eligible
            else None
        )
        if context and context["status"] == "ready":
            paths["adr"] = context["scenario_forecast"]
        else:
            skipped.append(
                {
                    "date": str(target),
                    "scenario": "adr",
                    "reason": context["reason"]
                    if context
                    else factor_reason or "missing_us_sessions",
                }
            )
        training.append(
            {
                "date": str(target),
                "training_start": prefix[0]["date"],
                "training_end": prefix[-1]["date"],
                "training_samples": len(prefix),
            }
        )
        for scenario, path in paths.items():
            predictions.append(
                {
                    "id": len(predictions) + 1,
                    "symbol": symbol,
                    "scenario": scenario,
                    "created_at": cutoff,
                    "base_close": prefix[-1]["close"],
                    "snapshot": {"forecast": path},
                }
            )
        target += timedelta(days=1)
    actuals = [{"symbol": symbol, "session_date": p["date"], "close": p["close"]} for p in points]
    result = evaluate(predictions, actuals)
    result["summary"] = [s for s in result["summary"] if s["symbol"] == symbol]
    for row in result["predictions"]:
        row["simulated_cutoff"] = row.pop("created_at")
        if row["status"] == "pending":
            row["pending_reason"] = (
                "missing_actual_close"
                if points and row["target_date"] <= points[-1]["date"]
                else "not_yet_available"
            )
    for summary in result["summary"]:
        scored = [
            r
            for r in result["predictions"]
            if r["status"] == "scored"
            and (r["scenario"], r["horizon"]) == (summary["scenario"], summary["horizon"])
        ]
        summary["baseline_mae"] = (
            sum(abs(r["base_close"] - r["actual_close"]) for r in scored) / len(scored)
            if scored
            else None
        )
    return {
        "kind": "historical_walk_forward",
        "symbol": symbol,
        "test_start": str(start),
        "test_end": str(end),
        "data_as_of": points[-1]["date"] if points else None,
        "training": training,
        "skipped": skipped,
        **result,
        "assumed_availability": True,
        "writes_live_archive": False,
    }


def historical_report(symbol, *, now=None):
    now = now or datetime.now(timezone.utc)
    end = now.astimezone(ZoneInfo("Asia/Taipei")).date()
    start = end - timedelta(days=29)
    points, metadata = twse_data(symbol)
    # A provider bar is not an eligible actual until the TWSE publication gate.
    points = [p for p in points if available_at(date.fromisoformat(p["date"])) <= now]
    factors, reason = None, None
    try:
        factors = overnight_factors(profile_for(symbol).symbols)
    except DataSourceError as exc:
        reason = exc.code
    result = walk_forward(symbol, points, factors, start, end, factor_reason=reason)
    return {**result, "checked_at": datetime.now(timezone.utc).isoformat(), "source": metadata}


@router.get("/api/historical-backtest")
def historical_backtest(symbol: Literal["2303.TW", "2330.TW"] = "2303.TW"):
    try:
        return historical_report(symbol)
    except DataSourceError as exc:
        return JSONResponse(status_code=502, content={"status": "unavailable", "reason": exc.code})
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"status": "unavailable", "reason": "insufficient_or_missing_training_history"},
        )
