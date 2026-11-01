"""Retrospective walk-forward evaluation, deliberately independent of the live archive."""

import time
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
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
from stockpredict.corporate_actions import actions_for, annotate_report
from stockpredict.data import DataSourceError, yahoo_data
from stockpredict.forecast import MIN_POINTS, forecast_path, validate_points
from stockpredict.market_data import overnight_factors
from stockpredict.model_review import review_models
from stockpredict.overnight import build_context
from stockpredict.reference_profiles import profile_for
from stockpredict.scoreboard import evaluate
from stockpredict.twse import twse_data

SYMBOLS = ("2303.TW", "2330.TW")
router = APIRouter()
PERIOD_DAYS = {1: 30, 3: 90, 6: 180, 12: 365}


@lru_cache(maxsize=8)
def _long_history(symbol, bucket):
    points, metadata = yahoo_data(symbol)
    if metadata.get("currency") != "TWD" or metadata.get("exchange_timezone") != "Asia/Taipei":
        raise DataSourceError("Invalid Taiwan history", code="us_invalid_data")
    return points, metadata


def walk_forward(symbol, points, factors, start: date, end: date, *, factor_reason=None):
    """Fit each target using only its prefix and US bars eligible before its open.

    Actuals are evaluated separately after generating every path. Today's historic
    feeds may contain revisions; simulated cutoffs are not publication evidence.
    """
    if symbol not in SYMBOLS or not 0 <= (end - start).days <= 365:
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
        paths = {"taiwan": date_path(forecast_path(prefix, 5), prefix[-1]["date"], "XTAI")}
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
            build_context(
                prefix,
                eligible,
                now=cutoff,
                horizon=5,
                factor_symbols=profile.symbols,
                diagnostics=False,
            )
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
        "coverage": {
            "requested_sessions": len(calendar_sessions(start, end)),
            "tested_sessions": len(training),
            "first_tested_origin": training[0]["date"] if training else None,
            "complete_training_coverage": len(training) == len(calendar_sessions(start, end)),
        },
        "data_as_of": points[-1]["date"] if points else None,
        "training": training,
        "skipped": skipped,
        "model_review": review_models(points, result["predictions"]),
        **result,
        "assumed_availability": True,
        "writes_live_archive": False,
    }


def calendar_sessions(start, end):
    from stockpredict.calendar import calendar

    return calendar("XTAI").sessions_in_range(start, end)


def historical_report(symbol, *, now=None, months=1):
    now = now or datetime.now(timezone.utc)
    end = now.astimezone(ZoneInfo("Asia/Taipei")).date()
    if months not in PERIOD_DAYS:
        raise ValueError("Unsupported period")
    start = end - timedelta(days=PERIOD_DAYS[months] - 1)
    points, metadata = (
        twse_data(symbol)
        if months == 1
        else deepcopy(_long_history(symbol, int(time.monotonic() // 300)))
    )
    # A provider bar is not an eligible actual until the TWSE publication gate.
    points = [p for p in points if available_at(date.fromisoformat(p["date"])) <= now]
    factors, reason = None, None
    try:
        factors = overnight_factors(profile_for(symbol).symbols)
    except DataSourceError as exc:
        reason = exc.code
    result = walk_forward(symbol, points, factors, start, end, factor_reason=reason)
    actions = metadata.get("corporate_actions") or actions_for(symbol)
    result = annotate_report(result, actions)
    report = {
        **result,
        "months": months,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": metadata,
    }
    from stockpredict.backtest_runs import register_draft

    return register_draft(
        report,
        {
            "symbol": symbol,
            "points": points,
            "factors": factors,
            "start": str(start),
            "end": str(end),
            "factor_reason": reason,
            "corporate_actions": actions,
        },
    )


@router.get("/api/historical-backtest")
def historical_backtest(
    symbol: Literal["2303.TW", "2330.TW"] = "2303.TW",
    months: Literal["1", "3", "6", "12"] = "1",
):
    try:
        return (
            historical_report(symbol)
            if months == "1"
            else historical_report(symbol, months=int(months))
        )
    except DataSourceError as exc:
        return JSONResponse(status_code=502, content={"status": "unavailable", "reason": exc.code})
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"status": "unavailable", "reason": "insufficient_or_missing_training_history"},
        )
