"""Append-only PostgreSQL forecast archive. Writes are restricted to the CLI job."""

import json
import os
from datetime import date, datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from stockpredict.calendar import available_at, date_path, next_session, opens_at, previous_session
from stockpredict.comparison import paired_comparison
from stockpredict.provenance import model_manifest, release_identity

router = APIRouter()
SYMBOLS = ("2303.TW", "2330.TW", "2308.TW")
SCENARIOS = ("taiwan", "adr")
MODEL = "ar5_adr_directional_v1"


def scenarios_for(symbol):
    return ("taiwan",) if symbol == "2308.TW" else SCENARIOS


def connect():
    url = os.getenv("SCOREBOARD_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    if not url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("PostgreSQL is not configured")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


def initialize(connection):
    connection.execute("SELECT pg_advisory_xact_lock(78346021)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS sp_predictions (
            id BIGSERIAL PRIMARY KEY,
            symbol TEXT NOT NULL CHECK (symbol IN ('2303.TW','2330.TW','2308.TW')),
            scenario TEXT NOT NULL CHECK (scenario IN ('taiwan','adr')),
            target_date DATE NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            base_date DATE NOT NULL, base_close DOUBLE PRECISION NOT NULL CHECK (base_close > 0),
            model_version TEXT NOT NULL, snapshot JSONB NOT NULL,
            UNIQUE(symbol, scenario, target_date)
        );
        CREATE TABLE IF NOT EXISTS sp_actual_closes (
            symbol TEXT NOT NULL, session_date DATE NOT NULL,
            close DOUBLE PRECISION NOT NULL CHECK (close > 0),
            observed_at TIMESTAMPTZ NOT NULL, source TEXT NOT NULL,
            PRIMARY KEY(symbol, session_date)
        );
        CREATE TABLE IF NOT EXISTS sp_scoreboard_checks (
            id BIGSERIAL PRIMARY KEY, checked_at TIMESTAMPTZ NOT NULL,
            details JSONB NOT NULL
        );
        CREATE OR REPLACE FUNCTION sp_reject_archive_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Forecast archive is append-only'; END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS sp_predictions_immutable ON sp_predictions;
        CREATE TRIGGER sp_predictions_immutable BEFORE UPDATE OR DELETE ON sp_predictions
            FOR EACH ROW EXECUTE FUNCTION sp_reject_archive_mutation();
        DROP TRIGGER IF EXISTS sp_predictions_no_truncate ON sp_predictions;
        CREATE TRIGGER sp_predictions_no_truncate BEFORE TRUNCATE ON sp_predictions
            FOR EACH STATEMENT EXECUTE FUNCTION sp_reject_archive_mutation();
        DROP TRIGGER IF EXISTS sp_actual_closes_immutable ON sp_actual_closes;
        CREATE TRIGGER sp_actual_closes_immutable BEFORE UPDATE OR DELETE ON sp_actual_closes
            FOR EACH ROW EXECUTE FUNCTION sp_reject_archive_mutation();
        DROP TRIGGER IF EXISTS sp_actual_closes_no_truncate ON sp_actual_closes;
        CREATE TRIGGER sp_actual_closes_no_truncate BEFORE TRUNCATE ON sp_actual_closes
            FOR EACH STATEMENT EXECUTE FUNCTION sp_reject_archive_mutation();
    """)
    connection.execute("""
        ALTER TABLE sp_predictions DROP CONSTRAINT IF EXISTS sp_predictions_symbol_check;
        ALTER TABLE sp_predictions ADD CONSTRAINT sp_predictions_symbol_check
            CHECK (symbol IN ('2303.TW','2330.TW','2308.TW'));
        ALTER TABLE sp_predictions DROP CONSTRAINT IF EXISTS sp_predictions_delta_scenario_check;
        ALTER TABLE sp_predictions ADD CONSTRAINT sp_predictions_delta_scenario_check
            CHECK (symbol <> '2308.TW' OR scenario = 'taiwan');
    """)
    from stockpredict.backtest_runs import ensure_initialized

    ensure_initialized(connection)


def capture_reason(points, now):
    base = date.fromisoformat(points[-1]["date"])
    target = next_session(base)
    if now >= opens_at(target):
        return "after_cutoff"
    if now.astimezone(ZoneInfo("Asia/Taipei")).date() != target:
        return "outside_capture_day"
    if previous_session(target) != base or now < available_at(base):
        return "missing_base_session"
    return None


def save_prediction(connection, symbol, scenario, points, path, now, provenance):
    """First on-time snapshot wins. Late/stale/partial forecasts cannot enter the archive."""
    if symbol not in SYMBOLS or scenario not in scenarios_for(symbol) or now.utcoffset() is None:
        raise ValueError("Invalid prediction context")
    reason = capture_reason(points, now)
    if reason:
        return reason
    base = date.fromisoformat(points[-1]["date"])
    target = next_session(base)
    if len(path) != 5 or path != date_path(path, base.isoformat(), "XTAI"):
        raise ValueError("Prediction must contain five exact trading sessions")
    values = [points[-1]["close"], *(p["close"] for p in path)]
    if any(isinstance(v, bool) or not isfinite(float(v)) or float(v) <= 0 for v in values):
        raise ValueError("Invalid forecast price")
    snapshot = {
        "history": points,
        "forecast": path,
        "provenance": provenance,
        "engine_manifest": model_manifest(),
    }
    row = connection.execute(
        """
        INSERT INTO sp_predictions
            (symbol,scenario,target_date,created_at,base_date,base_close,model_version,snapshot)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (symbol,scenario,target_date) DO NOTHING RETURNING id
    """,
        (symbol, scenario, target, now, base, points[-1]["close"], MODEL, Jsonb(snapshot)),
    ).fetchone()
    return "saved" if row else "already_saved"


def save_actual(connection, symbol, point, now):
    day = date.fromisoformat(point["date"])
    if symbol not in SYMBOLS or now < available_at(day):
        return False
    value = point["close"]
    if isinstance(value, bool) or not isfinite(float(value)) or value <= 0:
        raise ValueError("Invalid actual close")
    connection.execute(
        """
        INSERT INTO sp_actual_closes VALUES (%s,%s,%s,%s,'TWSE')
        ON CONFLICT (symbol,session_date) DO NOTHING
    """,
        (symbol, day, value, now),
    )
    return True


def evaluate(predictions, actuals):
    lookup = {(r["symbol"], str(r["session_date"])): r for r in actuals}
    rows, summary = [], []
    for prediction in predictions:
        for horizon in (1, 5):
            point = prediction["snapshot"]["forecast"][horizon - 1]
            actual = lookup.get((prediction["symbol"], point["date"]))
            close = actual["close"] if actual else None
            base, predicted = prediction["base_close"], point["close"]
            error = predicted - close if actual else None

            def sign(value):
                return (value > 0) - (value < 0)

            rows.append(
                {
                    "id": prediction["id"],
                    "symbol": prediction["symbol"],
                    "origin_date": prediction["snapshot"]["forecast"][0]["date"],
                    "scenario": prediction["scenario"],
                    "horizon": horizon,
                    "created_at": prediction["created_at"].isoformat(),
                    "target_date": point["date"],
                    "base_close": base,
                    "predicted_close": predicted,
                    "actual_close": close,
                    "status": "scored" if actual else "pending",
                    "error": error,
                    "absolute_error": abs(error) if actual else None,
                    "absolute_error_pct": abs(error) / close * 100 if actual else None,
                    "direction_hit": sign(predicted - base) == sign(close - base)
                    if actual
                    else None,
                }
            )
    for symbol in SYMBOLS:
        for scenario in scenarios_for(symbol):
            for horizon in (1, 5):
                group = [
                    r
                    for r in rows
                    if (r["symbol"], r["scenario"], r["horizon"]) == (symbol, scenario, horizon)
                ]
                scored = [r for r in group if r["status"] == "scored"]
                n = len(scored)
                summary.append(
                    {
                        "symbol": symbol,
                        "scenario": scenario,
                        "horizon": horizon,
                        "samples": n,
                        "pending": len(group) - n,
                        "mae": sum(r["absolute_error"] for r in scored) / n if n else None,
                        "rmse": (sum(r["absolute_error"] ** 2 for r in scored) / n) ** 0.5
                        if n
                        else None,
                        "mape": sum(r["absolute_error_pct"] for r in scored) / n if n else None,
                        "direction_accuracy": sum(r["direction_hit"] for r in scored) / n
                        if n
                        else None,
                    }
                )
    return {
        "summary": summary,
        "predictions": rows,
        "comparison": paired_comparison([r for r in rows if "adr" in scenarios_for(r["symbol"])]),
    }


@router.get("/api/scoreboard")
def scoreboard():
    try:
        with connect() as connection:
            predictions = connection.execute(
                "SELECT * FROM sp_predictions ORDER BY target_date DESC, id DESC"
            ).fetchall()
            actuals = connection.execute("SELECT * FROM sp_actual_closes").fetchall()
            check = connection.execute(
                "SELECT checked_at,details FROM sp_scoreboard_checks ORDER BY id DESC LIMIT 1"
            ).fetchone()
            first = connection.execute(
                "SELECT min(checked_at) AS started_at FROM sp_scoreboard_checks"
            ).fetchone()
        from stockpredict.monitoring import health_alerts

        result = evaluate(predictions, actuals)
        return {
            "status": "ready",
            **result,
            "last_check": check,
            "alerts": health_alerts(result["predictions"], check, first["started_at"]),
        }
    except (psycopg.Error, RuntimeError):
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "reason": "scoreboard_storage_unavailable",
                "summary": [],
                "predictions": [],
            },
        )


@router.get("/api/predictions/{prediction_id}")
def prediction_detail(prediction_id: int):
    try:
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM sp_predictions WHERE id=%s", (prediction_id,)
            ).fetchone()
            if row is None:
                return JSONResponse(status_code=404, content={"reason": "prediction_not_found"})
            path = row["snapshot"]["forecast"]
            actuals = connection.execute(
                "SELECT * FROM sp_actual_closes WHERE symbol=%s AND session_date BETWEEN %s AND %s",
                (row["symbol"], path[0]["date"], path[-1]["date"]),
            ).fetchall()
        lookup = {str(a["session_date"]): a for a in actuals}
        now = datetime.now(timezone.utc)
        days = []
        for index, point in enumerate(path, 1):
            actual = lookup.get(point["date"])
            reason = (
                None
                if actual
                else "awaiting_publication"
                if now < available_at(date.fromisoformat(point["date"]))
                else "missing_actual_close"
            )
            days.append(
                {
                    "horizon": index,
                    "target_date": point["date"],
                    "predicted_close": point["close"],
                    "actual_close": actual["close"] if actual else None,
                    "observed_at": actual["observed_at"] if actual else None,
                    "actual_source": actual["source"] if actual else None,
                    "evaluation_horizon": index in (1, 5),
                    "pending_reason": reason,
                }
            )
        provenance = row["snapshot"].get("provenance", {})
        context = provenance.get("market_context", {})
        history = row["snapshot"]["history"]
        return {
            "id": row["id"],
            "symbol": row["symbol"],
            "scenario": row["scenario"],
            "created_at": row["created_at"],
            "origin_date": row["target_date"],
            "base_date": row["base_date"],
            "base_close": row["base_close"],
            "model_version": row["model_version"],
            "engine_manifest": row["snapshot"].get("engine_manifest"),
            "training": {
                "start": history[0]["date"],
                "end": history[-1]["date"],
                "samples": len(history),
            },
            "source": provenance.get("metadata", {}).get("source", "unknown"),
            "reference_status": context.get("status"),
            "reference_reason": context.get("reason"),
            "required_us_session_date": context.get("required_us_session_date"),
            "reference_source": context.get("data_source"),
            "reference_quotes": [
                {
                    k: q.get(k)
                    for k in (
                        "symbol",
                        "session_date",
                        "previous_session_date",
                        "close",
                        "currency",
                    )
                }
                for q in context.get("quotes", [])
            ],
            "forecast": days,
            "evaluation": evaluate([row], actuals)["predictions"],
            "immutable": True,
            "checked_at": now.isoformat(),
        }
    except (psycopg.Error, RuntimeError):
        return JSONResponse(status_code=503, content={"reason": "scoreboard_storage_unavailable"})


@router.get("/api/scoreboard/health")
def scoreboard_health():
    from stockpredict.monitoring import health_alerts

    try:
        with connect() as connection:
            # Only dates and existence are needed; never transfer history snapshots.
            rows = connection.execute("""
                SELECT p.symbol, p.scenario, p.target_date::text AS origin_date,
                    f.point->>'date' AS target_date,
                    CASE WHEN a.session_date IS NULL THEN 'pending' ELSE 'scored' END AS status
                FROM sp_predictions p
                CROSS JOIN LATERAL jsonb_array_elements(p.snapshot->'forecast')
                    WITH ORDINALITY AS f(point, horizon)
                LEFT JOIN sp_actual_closes a ON a.symbol=p.symbol
                    AND a.session_date=(f.point->>'date')::date
                WHERE f.horizon IN (1,5)
            """).fetchall()
            check = connection.execute(
                "SELECT checked_at,details FROM sp_scoreboard_checks ORDER BY id DESC LIMIT 1"
            ).fetchone()
            first = connection.execute(
                "SELECT min(checked_at) AS started_at FROM sp_scoreboard_checks"
            ).fetchone()
        return {
            "status": "ready",
            "alerts": health_alerts(rows, check, first["started_at"]),
            "last_checked_at": check["checked_at"] if check else None,
        }
    except (psycopg.Error, RuntimeError):
        return JSONResponse(status_code=503, content={"reason": "scoreboard_storage_unavailable"})


def run_job(*, phase="all"):
    """Run periodically; source failures are recorded without substituting older sessions."""
    if phase not in {"all", "preopen", "close"}:
        raise ValueError("Invalid collection phase")
    from stockpredict.calendar import data_status
    from stockpredict.main import _market_analysis
    from stockpredict.twse import twse_data

    checks = []
    with connect() as connection:
        initialize(connection)
    for symbol in SYMBOLS:
        try:
            points, metadata = twse_data(symbol)
            now = datetime.now(timezone.utc)
            status = data_status(points, "XTAI", now)
            with connect() as connection:
                # Exact historic dates are retained; missing target dates stay pending.
                for point in points:
                    save_actual(connection, symbol, point, now)
            details = {"symbol": symbol, **status}
            reason = capture_reason(points, now)
            if reason:
                details.update({scenario: reason for scenario in scenarios_for(symbol)})
            if phase != "close" and status["status"] == "current" and reason is None:
                for scenario in scenarios_for(symbol):
                    result = _market_analysis(
                        symbol,
                        "twse",
                        5,
                        "zh-TW",
                        "none" if scenario == "taiwan" else "us_overnight",
                        # Fetch completed US sessions in this scheduled process.
                        # The web UI's optional CSV source is independent of capture.
                        factor_download_source="yahoo",
                    )
                    if not isinstance(result, dict):
                        details[scenario] = "source_unavailable"
                        continue
                    if result.get("history") != points:
                        details[scenario] = "source_changed_during_capture"
                        continue
                    context = result.get("market_context", {})
                    path = (
                        result["forecast"]
                        if scenario == "taiwan"
                        else context.get("scenario_forecast")
                    )
                    if not path or (scenario == "adr" and context.get("status") != "ready"):
                        details[scenario] = context.get("reason", "missing_us_sessions")
                        continue
                    with connect() as connection:
                        details[scenario] = save_prediction(
                            connection,
                            symbol,
                            scenario,
                            points,
                            path,
                            datetime.now(timezone.utc),
                            {"metadata": metadata, "market_context": context},
                        )
            checks.append(details)
        except Exception as exc:
            # Do not expose DSNs or provider payloads in diagnostics.
            checks.append(
                {
                    "symbol": symbol,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "status": "unavailable",
                    "reason": getattr(exc, "code", "source_unavailable"),
                }
            )
    for check in checks:
        check.update(phase=phase, release=release_identity())
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo("Asia/Taipei")).date()
    from stockpredict.calendar import is_session

    if is_session(day) and now >= opens_at(day):
        with connect() as connection:
            saved = connection.execute(
                "SELECT symbol FROM sp_predictions WHERE target_date=%s AND scenario='taiwan'",
                (day,),
            ).fetchall()
        captured = {row["symbol"] for row in saved}
        for check in checks:
            if check["symbol"] not in captured:
                check["preopen_missing"] = True
    with connect() as connection:
        connection.execute(
            "INSERT INTO sp_scoreboard_checks (checked_at,details) VALUES (%s,%s)",
            (datetime.now(timezone.utc), Jsonb(checks)),
        )
    return checks


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("init", "run"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--phase", choices=("all", "preopen", "close"), default="all")
    args = parser.parse_args()
    if args.command == "init":
        with connect() as connection:
            initialize(connection)
        print("Scoreboard schema ready")
    else:
        checks = run_job(phase=args.phase)
        print(json.dumps(checks, ensure_ascii=False))
        if args.strict:
            from stockpredict.monitoring import collection_failures

            if collection_failures(checks):
                print("::error::Required market data collection failed; inspect scoreboard status")
                raise SystemExit(1)
