"""Regression cases from the V1.1 reliability audit."""

from datetime import date, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import stockpredict.main as main
from stockpredict.calendar import calendar, data_status
from stockpredict.comparison import metrics
from stockpredict.monitoring import collection_failures, health_alerts


@pytest.mark.parametrize("source", ["twse", "yahoo"])
@pytest.mark.parametrize("lang", ["zh-TW", "en"])
def test_stale_provider_never_returns_a_usable_forecast(source, lang, monkeypatch):
    days = calendar("XTAI").sessions_in_range("2026-06-01", "2026-11-06")
    points = [{"date": str(d.date()), "close": 100.0} for d in days]
    monkeypatch.setattr(main, source + "_data", lambda _: (points, {}))
    now = datetime.fromisoformat("2026-11-09T16:00:00+08:00")
    monkeypatch.setattr(main, "data_status", lambda p, m, **kw: data_status(p, m, now, **kw))
    with patch.object(main, "build_context", side_effect=AssertionError("stale factors")):
        response = TestClient(main.app).get(
            f"/api/analysis?symbol=2330.TW&source={source}&lang={lang}"
        )
    assert response.status_code == 503
    assert response.json()["forecast"] == []
    assert response.json()["data_status"]["expected_session_date"] == str(date(2026, 11, 9))
    assert response.headers["cache-control"] == "no-store"
    assert "latest session" in response.json()["locales"]["en"]


@pytest.mark.parametrize(
    "reason",
    [
        "source_unavailable",
        "source_changed_during_capture",
        "auto_csv_unavailable",
        "us_rate_limited",
    ],
)
def test_adr_fault_fails_writer_and_independent_monitor(reason):
    now = datetime.fromisoformat("2026-11-09T08:30:00+08:00")
    check = {"symbol": "2303.TW", "status": "current", "taiwan": "saved", "adr": reason}
    assert collection_failures([check]) == ["2303.TW"]
    alerts = health_alerts([], {"checked_at": now, "details": [check]}, now, now=now)
    assert any(a["severity"] == "critical" for a in alerts)


def test_missed_preopen_fails_even_after_successful_close_collection():
    assert collection_failures(
        [
            {
                "symbol": "2303.TW",
                "status": "current",
                "taiwan": "outside_capture_day",
                "preopen_missing": True,
            }
        ]
    )
    assert not collection_failures(
        [{"symbol": "2303.TW", "status": "current", "taiwan": "outside_capture_day"}]
    )


def test_rmse_uses_same_samples_and_empty_is_null():
    rows = [
        {
            "absolute_error": v,
            "absolute_error_pct": v,
            "direction_hit": True,
            "base_close": 100,
            "actual_close": 100,
        }
        for v in (3, 4)
    ]
    assert metrics(rows)["rmse"] == pytest.approx((25 / 2) ** 0.5)
    assert metrics([])["rmse"] is None
