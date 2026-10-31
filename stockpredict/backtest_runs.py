"""Bounded, public, immutable backtest snapshots; only server-computed drafts can be saved."""

import csv
import io
import secrets
from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

import stockpredict.scoreboard as storage
from stockpredict.provenance import canonical, digest, model_manifest

router = APIRouter()
MAX_RUNS = 200
MAX_SAVES_PER_MINUTE = 10
DRAFT_TTL = timedelta(minutes=15)
_DRAFTS = OrderedDict()
_LOCK = Lock()
CORE_KEYS = (
    "kind",
    "symbol",
    "test_start",
    "test_end",
    "coverage",
    "data_as_of",
    "training",
    "skipped",
    "model_review",
    "summary",
    "predictions",
    "comparison",
    "assumed_availability",
    "writes_live_archive",
    "corporate_actions",
)


def core(report):
    return {key: report[key] for key in CORE_KEYS if key in report}


def register_draft(report, inputs):
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(24)
    manifest = model_manifest()
    snapshot = {"inputs": deepcopy(inputs), "report": deepcopy(report), "manifest": manifest}
    snapshot["fingerprint"] = digest(
        {"inputs": inputs, "manifest": manifest, "result": core(report)}
    )
    with _LOCK:
        for key in list(_DRAFTS):
            if _DRAFTS[key][0] <= now:
                del _DRAFTS[key]
        _DRAFTS[token] = (now + DRAFT_TTL, snapshot)
        while len(_DRAFTS) > 8:
            _DRAFTS.popitem(last=False)
    return {
        **report,
        "archive": {
            "draft_id": token,
            "expires_at": (now + DRAFT_TTL).isoformat(),
            "fingerprint": snapshot["fingerprint"],
            "saved": False,
        },
    }


def initialize(connection):
    connection.execute("SELECT pg_advisory_xact_lock(78346023)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS sp_backtest_runs (
            id UUID PRIMARY KEY, saved_at TIMESTAMPTZ NOT NULL,
            fingerprint TEXT NOT NULL UNIQUE,
            symbol TEXT NOT NULL, months INTEGER NOT NULL,
            inputs JSONB NOT NULL, report JSONB NOT NULL, manifest JSONB NOT NULL
        );
        CREATE OR REPLACE FUNCTION sp_reject_backtest_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Backtest snapshots are append-only'; END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS sp_backtest_immutable ON sp_backtest_runs;
        CREATE TRIGGER sp_backtest_immutable BEFORE UPDATE OR DELETE ON sp_backtest_runs
            FOR EACH ROW EXECUTE FUNCTION sp_reject_backtest_mutation();
        DROP TRIGGER IF EXISTS sp_backtest_no_truncate ON sp_backtest_runs;
        CREATE TRIGGER sp_backtest_no_truncate BEFORE TRUNCATE ON sp_backtest_runs
            FOR EACH STATEMENT EXECUTE FUNCTION sp_reject_backtest_mutation();
    """)


def ensure_initialized(connection):
    if (
        connection.execute("SELECT to_regclass('sp_backtest_runs') AS table_name").fetchone()[
            "table_name"
        ]
        is None
    ):
        initialize(connection)


def compatible(manifest):
    current = model_manifest()
    return {k: v for k, v in manifest.items() if k != "build_commit"} == {
        k: v for k, v in current.items() if k != "build_commit"
    }


def public_run(row, *, include_inputs=False):
    archive = {
        "run_id": str(row["id"]),
        "saved_at": row["saved_at"].isoformat(),
        "fingerprint": row["fingerprint"],
        "saved": True,
        "replay_compatible": compatible(row["manifest"]),
    }
    result = {"report": {**row["report"], "archive": archive}, "manifest": row["manifest"]}
    if include_inputs:
        result["inputs"] = row["inputs"]
    return result


def unavailable():
    return JSONResponse(status_code=503, content={"reason": "backtest_storage_unavailable"})


def read_run(run_id):
    with storage.connect() as connection:
        return connection.execute(
            "SELECT * FROM sp_backtest_runs WHERE id=%s", (run_id,)
        ).fetchone()


class SaveDraft(BaseModel):
    draft_id: str = Field(min_length=20, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/api/backtest-runs")
def save_run(body: SaveDraft):
    now = datetime.now(timezone.utc)
    with _LOCK:
        draft = _DRAFTS.get(body.draft_id)
        snapshot = deepcopy(draft[1]) if draft and draft[0] > now else None
    if snapshot is None:
        return JSONResponse(status_code=410, content={"reason": "backtest_draft_expired"})
    try:
        with storage.connect() as connection:
            ensure_initialized(connection)
            connection.execute("SELECT pg_advisory_xact_lock(78346024)")
            row = connection.execute(
                "SELECT * FROM sp_backtest_runs WHERE fingerprint=%s", (snapshot["fingerprint"],)
            ).fetchone()
            if row is None:
                counts = connection.execute(
                    """
                    SELECT count(*) AS total,
                        count(*) FILTER (WHERE saved_at > %s) AS recent FROM sp_backtest_runs
                """,
                    (now - timedelta(minutes=1),),
                ).fetchone()
                if counts["total"] >= MAX_RUNS:
                    return JSONResponse(
                        status_code=507, content={"reason": "backtest_archive_full"}
                    )
                if counts["recent"] >= MAX_SAVES_PER_MINUTE:
                    return JSONResponse(
                        status_code=429,
                        content={"reason": "backtest_save_rate_limited"},
                        headers={"Retry-After": "60"},
                    )
                row = connection.execute(
                    """
                    INSERT INTO sp_backtest_runs VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
                """,
                    (
                        uuid4(),
                        now,
                        snapshot["fingerprint"],
                        snapshot["report"]["symbol"],
                        snapshot["report"]["months"],
                        Jsonb(snapshot["inputs"]),
                        Jsonb(snapshot["report"]),
                        Jsonb(snapshot["manifest"]),
                    ),
                ).fetchone()
        return public_run(row)
    except (psycopg.Error, RuntimeError):
        return unavailable()


@router.get("/api/backtest-runs")
def list_runs():
    try:
        with storage.connect() as connection:
            rows = connection.execute("""
                SELECT id,saved_at,fingerprint,symbol,months FROM sp_backtest_runs
                ORDER BY saved_at DESC LIMIT 20
            """).fetchall()
        return {"runs": rows, "capacity": MAX_RUNS, "public_market_reports": True}
    except (psycopg.Error, RuntimeError):
        return unavailable()


@router.get("/api/backtest-runs/{run_id}")
def get_run(run_id: UUID):
    try:
        row = read_run(run_id)
        return (
            public_run(row, include_inputs=True)
            if row
            else JSONResponse(status_code=404, content={"reason": "backtest_run_not_found"})
        )
    except (psycopg.Error, RuntimeError):
        return unavailable()


CSV_FIELDS = (
    "origin_date",
    "symbol",
    "scenario",
    "horizon",
    "simulated_cutoff",
    "target_date",
    "base_close",
    "predicted_close",
    "actual_close",
    "status",
    "pending_reason",
    "error",
    "absolute_error_pct",
    "direction_hit",
    "corporate_action_dates",
    "corporate_action_types",
    "corporate_action_status",
)


def csv_bytes(report):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in report["predictions"]:
        values = {
            **row,
            "corporate_action_dates": ";".join(
                sorted({e["date"] for e in row.get("corporate_actions", [])})
            ),
            "corporate_action_types": ";".join(
                sorted({e["type"] for e in row.get("corporate_actions", [])})
            ),
        }
        values = {
            key: (str(value).lower() if isinstance(value, bool) else value)
            for key, value in values.items()
        }
        writer.writerow(values)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


@router.get("/api/backtest-runs/{run_id}/export.csv")
def export_run(run_id: UUID):
    try:
        row = read_run(run_id)
        if row is None:
            return JSONResponse(status_code=404, content={"reason": "backtest_run_not_found"})
        return Response(
            csv_bytes(row["report"]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="backtest-{run_id}.csv"'},
        )
    except (psycopg.Error, RuntimeError):
        return unavailable()


@router.post("/api/backtest-runs/{run_id}/replay")
def replay_run(run_id: UUID):
    try:
        row = read_run(run_id)
        if row is None:
            return JSONResponse(status_code=404, content={"reason": "backtest_run_not_found"})
        if not compatible(row["manifest"]):
            return JSONResponse(status_code=409, content={"reason": "backtest_engine_mismatch"})
        expected = digest(
            {"inputs": row["inputs"], "manifest": row["manifest"], "result": core(row["report"])}
        )
        if expected != row["fingerprint"]:
            return JSONResponse(status_code=409, content={"reason": "backtest_snapshot_corrupted"})
        inputs = row["inputs"]
        from stockpredict.historical import walk_forward

        result = walk_forward(
            inputs["symbol"],
            inputs["points"],
            inputs["factors"],
            date.fromisoformat(inputs["start"]),
            date.fromisoformat(inputs["end"]),
            factor_reason=inputs["factor_reason"],
        )
        if "corporate_actions" in row["report"]:
            from stockpredict.corporate_actions import annotate_report

            result = annotate_report(result, inputs["corporate_actions"])
        matches = canonical(core(result)) == canonical(core(row["report"]))
        return {
            "run_id": str(run_id),
            "matches_saved_result": matches,
            "replayed_from_snapshot": True,
            "upstream_requests": 0,
            "saved_result_hash": digest(core(row["report"])),
            "replay_result_hash": digest(core(result)),
        }
    except (psycopg.Error, RuntimeError):
        return unavailable()
