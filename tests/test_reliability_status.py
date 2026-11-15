from datetime import datetime, timedelta, timezone

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from stockpredict import reliability, scoreboard
from stockpredict.main import app


def details():
    return [{"symbol": s, "status": "current"} for s in scoreboard.SYMBOLS]


def test_successful_check_requires_all_stocks_and_no_scenario_error():
    assert reliability.successful_check({"details": details()})
    assert not reliability.successful_check({"details": details()[:2]})
    assert not reliability.successful_check({"details": details() + details()[:1]})
    rows = details()
    rows[0]["adr"] = "source_unavailable"
    assert not reliability.successful_check({"details": rows})


def test_health_distinguishes_last_run_from_last_success_without_writing(database):
    now = datetime.now(timezone.utc)
    previous = now - timedelta(minutes=20)
    failed = details()
    failed[0]["status"] = "unavailable"
    with database() as connection:
        for stamp, rows in [(previous, details()), (now, failed)]:
            connection.execute(
                "INSERT INTO sp_scoreboard_checks(checked_at,details) VALUES (%s,%s)",
                (stamp, Jsonb(rows)),
            )
    with TestClient(app) as client:
        response = client.get("/api/reliability/health")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert datetime.fromisoformat(result["last_checked_at"]) == now
    assert datetime.fromisoformat(result["last_successful_checked_at"]) == previous
    assert result["alerts"]
    with database() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM sp_scoreboard_checks").fetchone()["n"]
            == 2
        )


def test_health_failure_does_not_claim_old_success(monkeypatch):
    monkeypatch.setattr(
        scoreboard, "scoreboard_health", lambda: JSONResponse(status_code=503, content={})
    )
    with TestClient(app) as client:
        response = client.get("/api/reliability/health")
    assert response.status_code == 503
    assert "last_successful_checked_at" not in response.json()
