from copy import deepcopy
from datetime import date, datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient

import stockpredict.historical as history
import stockpredict.scoreboard as scoreboard
from stockpredict.calendar import available_at, calendar, date_path
from stockpredict.data import DataSourceError
from stockpredict.main import app


@pytest.fixture
def points(monkeypatch):
    from stockpredict.corporate_actions import unavailable

    monkeypatch.setattr(history, "actions_for", lambda symbol: unavailable())
    dates = calendar("XTAI").sessions_in_range("2026-04-01", "2026-10-30")
    rng = np.random.default_rng(918)
    prices = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(dates))))
    return [{"date": str(d.date()), "close": float(p)} for d, p in zip(dates, prices)]


def test_real_model_scores_one_and_five_day_horizons_without_touching_archive(points, monkeypatch):
    monkeypatch.setattr(scoreboard, "connect", lambda: pytest.fail("Must not touch live archive"))
    report = history.walk_forward("2303.TW", points, None, date(2026, 10, 1), date(2026, 10, 30))
    sessions = calendar("XTAI").sessions_in_range("2026-10-01", "2026-10-30")
    summary = {(s["scenario"], s["horizon"]): s for s in report["summary"]}
    assert summary["taiwan", 1]["samples"] == len(sessions)
    assert summary["taiwan", 5]["samples"] == len(sessions) - 4
    assert summary["taiwan", 5]["pending"] == 4
    assert summary["adr", 1]["samples"] == 0
    assert summary["taiwan", 1]["baseline_mae"] > 0
    assert report["writes_live_archive"] is False
    assert report["kind"] == "historical_walk_forward"
    assert all(
        t["training_end"] < t["date"] and t["training_samples"] >= 60 for t in report["training"]
    )
    assert all("created_at" not in r and "simulated_cutoff" in r for r in report["predictions"])


def test_future_taiwan_prices_do_not_change_earlier_forecasts(points):
    start = date(2026, 10, 1)
    before = history.walk_forward("2303.TW", points, None, start, start)
    changed = deepcopy(points)
    for p in changed:
        if p["date"] >= str(start):
            p["close"] *= 2
    after = history.walk_forward("2303.TW", changed, None, start, start)
    assert [r["predicted_close"] for r in before["predictions"]] == [
        r["predicted_close"] for r in after["predictions"]
    ]
    assert before["predictions"][0]["actual_close"] != after["predictions"][0]["actual_close"]


def test_missing_actual_not_replaced_and_missing_base_skips_next_origin(points):
    points = [p for p in points if p["date"] != "2026-10-01"]
    report = history.walk_forward("2330.TW", points, None, date(2026, 10, 1), date(2026, 10, 2))
    assert report["predictions"][0]["target_date"] == "2026-10-01"
    assert report["predictions"][0]["status"] == "pending"
    assert report["predictions"][0]["pending_reason"] == "missing_actual_close"
    assert any(s["date"] == "2026-10-02" and s["scenario"] == "all" for s in report["skipped"])


def test_only_eligible_us_rows_are_passed_to_model(points, monkeypatch):
    seen = []

    def context(prefix, factors, *, now, **kwargs):
        for rows in factors.values():
            assert all(available_at(date.fromisoformat(p["date"]), "XNYS") <= now for p in rows)
        seen.append(factors)
        return {
            "status": "ready",
            "scenario_forecast": date_path(
                [{"close": prefix[-1]["close"]}] * 5, prefix[-1]["date"], "XTAI"
            ),
        }

    monkeypatch.setattr(history, "build_context", context)
    factors = {
        s: [
            {"date": "2026-09-29", "close": 100},
            {"date": "2026-09-30", "close": 101},
            {"date": "2026-10-01", "close": 999},
            {"date": "2099-01-01", "close": 999},
        ]
        for s in ("UMC", "SOXX")
    }
    report = history.walk_forward("2303.TW", points, factors, date(2026, 10, 1), date(2026, 10, 1))
    assert all(
        [p["date"] for p in rows] == ["2026-09-29", "2026-09-30"] for rows in seen[0].values()
    )
    assert any(r["scenario"] == "adr" for r in report["predictions"])


def test_actual_adr_model_runs_on_constant_historical_series(points):
    points = [{**p, "close": 100.0} for p in points]
    dates = calendar("XNYS").sessions_in_range("2026-03-01", "2026-10-30")
    factors = {s: [{"date": str(d.date()), "close": 100.0} for d in dates] for s in ("TSM", "SOXX")}
    report = history.walk_forward("2330.TW", points, factors, date(2026, 10, 1), date(2026, 10, 8))
    for summary in report["summary"]:
        assert summary["samples"] > 0
        assert summary["mae"] == pytest.approx(0, abs=1e-8)
        assert summary["direction_accuracy"] == 1
    assert not report["skipped"]


def test_api_preserves_taiwan_results_when_us_provider_fails(points, monkeypatch):
    monkeypatch.setattr(history, "twse_data", lambda s: (points, {"source": "twse"}))

    def failed(*args):
        raise DataSourceError("Rate limited", code="us_rate_limited")

    monkeypatch.setattr(history, "overnight_factors", failed)
    original = history.historical_report
    monkeypatch.setattr(
        history,
        "historical_report",
        lambda symbol: original(symbol, now=datetime.fromisoformat("2026-10-31T12:00:00+08:00")),
    )
    response = TestClient(app).get("/api/historical-backtest?symbol=2330.TW")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["test_start"] == "2026-10-02" and body["test_end"] == "2026-10-31"
    assert body["predictions"]
    assert all(s["reason"] == "us_rate_limited" for s in body["skipped"])


def test_api_source_failure_and_invalid_symbol(monkeypatch):
    def failed(symbol):
        raise DataSourceError("Unavailable")

    monkeypatch.setattr(history, "twse_data", failed)
    client = TestClient(app)
    assert client.get("/api/historical-backtest").status_code == 502
    assert client.get("/api/historical-backtest?symbol=AAPL").status_code == 422


@pytest.mark.parametrize("months,days", [(3, 90), (6, 180), (12, 365)])
def test_long_periods_request_long_history_and_show_partial_coverage(
    points, monkeypatch, months, days
):
    monkeypatch.setattr(history, "_long_history", lambda *a: (points, {"source": "yahoo"}))
    monkeypatch.setattr(history, "twse_data", lambda *a: pytest.fail("Short TWSE data used"))
    monkeypatch.setattr(history, "overnight_factors", lambda *a: {})
    report = history.historical_report(
        "2303.TW", months=months, now=datetime.fromisoformat("2026-10-31T12:00:00+08:00")
    )
    assert (
        date.fromisoformat(report["test_end"]) - date.fromisoformat(report["test_start"])
    ).days == days - 1
    assert report["source"]["source"] == "yahoo"
    assert report["coverage"]["tested_sessions"] <= report["coverage"]["requested_sessions"]
    if months >= 6:
        assert not report["coverage"]["complete_training_coverage"]


def test_fast_forecast_is_identical_to_original_model(points):
    from stockpredict.forecast import analyze, forecast_path

    fast = forecast_path(points, 5)
    original = analyze(points, 5)["forecast"]
    assert [p["close"] for p in fast] == [p["close"] for p in original]


@pytest.mark.parametrize("months", [1, 3, 6, 12])
def test_api_accepts_each_period_as_query_string(monkeypatch, months):
    monkeypatch.setattr(
        history, "historical_report", lambda symbol, **kw: {"months": kw.get("months", 1)}
    )
    response = TestClient(app).get("/api/historical-backtest", params={"months": months})
    assert response.status_code == 200 and response.json()["months"] == months
    assert TestClient(app).get("/api/historical-backtest?months=2").status_code == 422
