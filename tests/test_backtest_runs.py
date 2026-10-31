import csv
import io
from copy import deepcopy
from datetime import date
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

import stockpredict.backtest_runs as runs
import stockpredict.historical as history
from stockpredict.calendar import calendar
from stockpredict.corporate_actions import annotate_report
from stockpredict.main import app


@pytest.fixture
def draft():
    points = [
        {"date": str(d.date()), "close": 100 + i * 0.1}
        for i, d in enumerate(calendar("XTAI").sessions_in_range("2026-01-01", "2026-10-08"))
    ]
    start, end = date(2026, 10, 1), date(2026, 10, 8)
    actions = {
        "status": "ready",
        "source": "Yahoo Finance",
        "checked_at": "2026-10-08T09:00:00+00:00",
        "coverage_start": "2026-01-01",
        "coverage_end": "2026-10-08",
        "absence_is_not_proof": True,
        "events": [
            {
                "date": "2026-10-07",
                "type": "dividend",
                "amount": 2,
                "currency": "TWD",
                "source": "Yahoo Finance",
                "status": "provider_reported",
            }
        ],
    }
    report = annotate_report(history.walk_forward("2303.TW", points, None, start, end), actions)
    report.update(
        months=1, source={"source": "test_fixture"}, checked_at="2026-10-08T09:00:00+00:00"
    )
    inputs = dict(
        symbol="2303.TW",
        points=points,
        factors=None,
        start=str(start),
        end=str(end),
        factor_reason=None,
        corporate_actions=actions,
    )
    return runs.register_draft(report, inputs)


def test_saved_report_is_immutable_deduplicated_and_replays_without_providers(
    database, draft, monkeypatch
):
    client = TestClient(app)
    body = {"draft_id": draft["archive"]["draft_id"]}
    saved = client.post("/api/backtest-runs", json=body)
    assert saved.status_code == 200
    archived = saved.json()["report"]
    run_id = archived["archive"]["run_id"]
    assert archived["archive"]["saved"] and archived["archive"]["replay_compatible"]
    assert (
        client.post("/api/backtest-runs", json=body).json()["report"]["archive"]["run_id"] == run_id
    )
    fetched = client.get(f"/api/backtest-runs/{run_id}").json()
    assert fetched["inputs"]["points"]
    assert runs.core(fetched["report"]) == runs.core(draft)
    assert client.get("/api/backtest-runs").json()["runs"][0]["id"] == run_id

    monkeypatch.setattr(history, "twse_data", lambda *a: pytest.fail("No upstream requests"))
    monkeypatch.setattr(
        history, "overnight_factors", lambda *a: pytest.fail("No upstream requests")
    )
    monkeypatch.setattr(history, "actions_for", lambda *a: pytest.fail("No upstream requests"))
    replay = client.post(f"/api/backtest-runs/{run_id}/replay")
    assert replay.status_code == 200
    assert replay.json()["matches_saved_result"] and replay.json()["upstream_requests"] == 0
    assert replay.json()["saved_result_hash"] == replay.json()["replay_result_hash"]
    exported = client.get(f"/api/backtest-runs/{run_id}/export.csv")
    assert exported.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert len(rows) == len(draft["predictions"])
    assert "corporate_action_status" in rows[0]
    assert any("2026-10-07" in r["corporate_action_dates"] for r in rows)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE sp_backtest_runs SET symbol='bad'",
        "DELETE FROM sp_backtest_runs",
        "TRUNCATE sp_backtest_runs",
    ],
)
def test_backtest_database_refuses_mutations(database, draft, sql):
    assert (
        TestClient(app)
        .post("/api/backtest-runs", json={"draft_id": draft["archive"]["draft_id"]})
        .status_code
        == 200
    )
    with pytest.raises(psycopg.Error, match="append-only"), database() as connection:
        connection.execute(sql)


def test_replay_engine_mismatch_preserves_original_download(database, draft, monkeypatch):
    client = TestClient(app)
    saved = client.post(
        "/api/backtest-runs", json={"draft_id": draft["archive"]["draft_id"]}
    ).json()
    run_id = saved["report"]["archive"]["run_id"]
    monkeypatch.setattr(runs, "compatible", lambda m: False)
    assert client.post(f"/api/backtest-runs/{run_id}/replay").status_code == 409
    assert client.get(f"/api/backtest-runs/{run_id}/export.csv").status_code == 200


def test_client_cannot_submit_a_report_and_limits_are_bounded(database, draft, monkeypatch):
    client = TestClient(app)
    assert client.post("/api/backtest-runs", json={"report": draft}).status_code == 422
    assert (
        client.post("/api/backtest-runs", json={"draft_id": "unknown_token_1234567890"}).status_code
        == 410
    )
    monkeypatch.setattr(runs, "MAX_SAVES_PER_MINUTE", 0)
    response = client.post("/api/backtest-runs", json={"draft_id": draft["archive"]["draft_id"]})
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    monkeypatch.setattr(runs, "MAX_SAVES_PER_MINUTE", 10)
    monkeypatch.setattr(runs, "MAX_RUNS", 0)
    assert (
        client.post(
            "/api/backtest-runs", json={"draft_id": draft["archive"]["draft_id"]}
        ).status_code
        == 507
    )
    assert client.get(f"/api/backtest-runs/{uuid4()}").status_code == 404


def test_existing_archive_can_be_saved_with_select_insert_role_only(database, draft, monkeypatch):
    import stockpredict.scoreboard as storage

    role = "test_archive_" + uuid4().hex
    with database() as connection:
        schema = connection.execute("SELECT current_schema() AS name").fetchone()["name"]
        connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        connection.execute(
            sql.SQL("GRANT SELECT,INSERT ON sp_backtest_runs TO {}").format(sql.Identifier(role))
        )
    try:

        def limited():
            connection = database()
            connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
            return connection

        monkeypatch.setattr(storage, "connect", limited)
        response = TestClient(app).post(
            "/api/backtest-runs", json={"draft_id": draft["archive"]["draft_id"]}
        )
        assert response.status_code == 200
    finally:
        with database() as connection:
            connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_input_snapshot_is_a_copy_and_corruption_is_rejected(database, draft, monkeypatch):
    client = TestClient(app)
    result = client.post(
        "/api/backtest-runs", json={"draft_id": draft["archive"]["draft_id"]}
    ).json()
    run_id = result["report"]["archive"]["run_id"]
    original = runs.read_run(run_id)
    broken = deepcopy(original)
    broken["inputs"]["points"][-1]["close"] += 1
    monkeypatch.setattr(runs, "read_run", lambda value: broken)
    response = client.post(f"/api/backtest-runs/{run_id}/replay")
    assert (
        response.status_code == 409 and response.json()["reason"] == "backtest_snapshot_corrupted"
    )
