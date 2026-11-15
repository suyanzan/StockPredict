from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

from stockpredict import onboarding, scoreboard
from stockpredict.calendar import available_at, date_path, is_session
from stockpredict.data import DataSourceError
from stockpredict.main import app

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)


def history():
    start = date(2026, 6, 1)
    days = [start + timedelta(days=i) for i in range(166)]
    return [
        {"date": day.isoformat(), "close": 100 + i / 10}
        for i, day in enumerate(days)
        if is_session(day)
    ]


def test_preflight_dry_run_is_not_enrollment_and_cannot_access_storage(monkeypatch):
    points = history()
    monkeypatch.setattr(onboarding, "twse_data", lambda s: (points, {"name": "鴻海"}))

    def forbidden():
        raise AssertionError("Preflight must not access storage")

    monkeypatch.setattr(scoreboard, "connect", forbidden)
    report = onboarding.preflight("2317.TW", NOW)
    assert report["status"] == "review_required"
    assert all(report["checks"].values())
    assert report["enrolled"] is False
    assert report["read_only"] is True
    assert report["storage_verified_in_production"] is False
    assert report["forecast_target_dates"] == [
        "2026-11-16",
        "2026-11-17",
        "2026-11-18",
        "2026-11-19",
        "2026-11-20",
    ]
    assert report["capture_window_reason"] == "outside_capture_day"
    assert "2317.TW" not in scoreboard.SYMBOLS


def test_stale_or_incomplete_history_blocks_preflight(monkeypatch):
    for points in (history()[:-1], history()[-20:]):
        monkeypatch.setattr(onboarding, "twse_data", lambda s: (points, {}))
        result = onboarding.preflight("2317.TW", NOW)
        assert result["status"] == "blocked"
        assert result["forecast_target_dates"] == []


def test_future_prices_never_enter_preflight_model(monkeypatch):
    points = history()
    monkeypatch.setattr(
        onboarding, "twse_data", lambda s: (points + [{"date": "2026-11-16", "close": 999}], {})
    )
    seen = []

    def model(rows, horizon):
        seen.extend(rows)
        return [{"close": 100}] * horizon

    monkeypatch.setattr(onboarding, "forecast_path", model)
    report = onboarding.preflight("2317.TW", NOW)
    assert report["status"] == "review_required"
    assert max(p["date"] for p in seen) == "2026-11-13"


def test_invalid_code_and_source_failure_are_safe(monkeypatch):
    def unavailable(symbol):
        raise DataSourceError("sensitive provider details")

    monkeypatch.setattr(onboarding, "twse_data", unavailable)
    with TestClient(app) as client:
        assert client.get("/api/collection/readiness?symbol=AAPL").status_code == 422
        response = client.get("/api/collection/readiness?symbol=2317")
    assert response.status_code == 503
    assert response.json() == {"reason": "source_unavailable"}
    assert response.headers["cache-control"] == "no-store"


def test_model_failure_blocks_without_enrollment(monkeypatch):
    monkeypatch.setattr(onboarding, "twse_data", lambda s: (history(), {}))

    def fail(*args):
        raise ValueError("No model")

    monkeypatch.setattr(onboarding, "forecast_path", fail)
    result = onboarding.preflight("2317.TW", NOW)
    assert result["status"] == "blocked"
    assert result["checks"]["five_session_path"] is False


def test_candidate_archive_admission_in_isolated_schema(database, monkeypatch):
    points = history()
    path = date_path(onboarding.forecast_path(points, 5), points[-1]["date"], "XTAI")
    capture = datetime(2026, 11, 16, 0, 11, tzinfo=timezone.utc)
    with database() as connection:
        with pytest.raises(ValueError):
            scoreboard.save_prediction(connection, "2317.TW", "taiwan", points, path, capture, {})
    # This activation simulation changes only a test schema and monkeypatched process policy.
    monkeypatch.setattr(scoreboard, "SYMBOLS", (*scoreboard.SYMBOLS, "2317.TW"))
    original = scoreboard.scenarios_for
    monkeypatch.setattr(
        scoreboard, "scenarios_for", lambda s: ("taiwan",) if s == "2317.TW" else original(s)
    )
    with database() as connection:
        connection.execute("ALTER TABLE sp_predictions DROP CONSTRAINT sp_predictions_symbol_check")
        connection.execute("""ALTER TABLE sp_predictions ADD CONSTRAINT sp_predictions_symbol_check
            CHECK (symbol IN ('2303.TW','2330.TW','2308.TW','2317.TW'))""")
        assert (
            scoreboard.save_prediction(connection, "2317.TW", "taiwan", points, path, capture, {})
            == "saved"
        )
    with database() as connection:
        altered = [{**p, "close": 999} for p in path]
        assert (
            scoreboard.save_prediction(
                connection, "2317.TW", "taiwan", points, altered, capture, {}
            )
            == "already_saved"
        )
        assert (
            scoreboard.save_prediction(
                connection, "2317.TW", "taiwan", points, path, capture.replace(hour=1), {}
            )
            == "after_cutoff"
        )
        with pytest.raises(ValueError):
            scoreboard.save_prediction(connection, "2317.TW", "adr", points, path, capture, {})
    for sql in ["UPDATE sp_predictions SET base_close=999", "DELETE FROM sp_predictions"]:
        with database() as connection, pytest.raises(psycopg.Error):
            connection.execute(sql)
    day = date(2026, 11, 16)
    with database() as connection:
        assert not scoreboard.save_actual(
            connection,
            "2317.TW",
            {"date": day.isoformat(), "close": 200},
            available_at(day) - timedelta(seconds=1),
        )
        scoreboard.save_actual(
            connection, "2317.TW", {"date": day.isoformat(), "close": 200}, available_at(day)
        )
    with database() as connection:
        scoreboard.save_actual(
            connection,
            "2317.TW",
            {"date": day.isoformat(), "close": 999},
            available_at(day) + timedelta(minutes=1),
        )
        rows = connection.execute("SELECT * FROM sp_actual_closes").fetchall()
        assert len(rows) == 1 and rows[0]["close"] == 200
