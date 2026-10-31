from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from stockpredict.calendar import (
    available_at,
    data_status,
    date_path,
    is_session,
    latest_published,
    next_session,
    opens_at,
)
from stockpredict.main import app


@pytest.mark.parametrize("day", ["2026-01-01", "2026-02-16", "2026-02-20", "2026-10-09"])
def test_taiwan_holidays(day):
    assert not is_session(date.fromisoformat(day))


def test_lunar_new_year_forecast_skips_settlement_and_holidays():
    assert next_session(date(2026, 2, 11)) == date(2026, 2, 23)
    path = date_path([{"close": 100}] * 5, "2026-02-11", "XTAI")
    assert path[0]["date"] == "2026-02-23"
    assert path[-1]["date"] == "2026-03-02"


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ("2026-03-06", "2026-03-06T21:15:00+00:00"),
        ("2026-03-09", "2026-03-09T20:15:00+00:00"),
        ("2026-11-02", "2026-11-02T21:15:00+00:00"),
        ("2026-11-27", "2026-11-27T18:15:00+00:00"),
    ],
)
def test_us_dst_and_early_close(day, expected):
    assert available_at(date.fromisoformat(day), "XNYS").isoformat() == expected


def test_us_holiday_is_not_expected_missing_data():
    now = datetime.fromisoformat("2026-11-27T05:00:00+08:00")
    assert latest_published(now, "XNYS") == date(2026, 11, 25)


def test_gate_is_not_proof_of_received_data():
    now = datetime.fromisoformat("2026-10-30T15:00:00+08:00")
    status = data_status([{"date": "2026-10-29", "close": 50}], "XTAI", now)
    assert status["status"] == "missing"
    assert status["expected_session_date"] == "2026-10-30"
    assert status["session_date"] == "2026-10-29"
    assert status["checked_at"] == now.isoformat()


def test_early_close_gate_boundary():
    before = datetime.fromisoformat("2026-11-27T18:14:59+00:00")
    after = datetime.fromisoformat("2026-11-27T18:15:00+00:00")
    assert latest_published(before, "XNYS") == date(2026, 11, 25)
    assert latest_published(after, "XNYS") == date(2026, 11, 27)


def test_yahoo_and_twse_publication_gates_are_distinct():
    now = datetime.fromisoformat("2026-10-30T14:00:00+08:00")
    points = [{"date": "2026-10-30", "close": 50}]
    assert data_status(points, "XTAI", now, publication_delay=15)["status"] == "current"
    assert data_status(points, "XTAI", now)["expected_session_date"] == "2026-10-29"


def test_calendar_api_and_preopen_time():
    response = TestClient(app).get("/api/calendar")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert {m["exchange"] for m in response.json()["markets"]} == {"XTAI", "XNYS"}
    assert opens_at(date(2026, 10, 30)).isoformat() == "2026-10-30T01:00:00+00:00"
