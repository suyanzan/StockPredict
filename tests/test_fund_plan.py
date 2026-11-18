"""Private 0050 plan: owner-only access and arithmetic of the simulations."""

from datetime import date, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

import stockpredict.fund_plan as fund_plan
from stockpredict.data import DataSourceError
from stockpredict.main import app

TOKEN = "t" * 40


def series(closes):
    day, dates = date(2010, 1, 4), []
    while len(dates) < len(closes):
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += timedelta(days=1)
    return dates, np.array(closes, dtype=float)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COMMUNITY_ADMIN_TOKEN", TOKEN)
    fund_plan._cache.clear()
    with TestClient(app) as instance:
        yield instance
    fund_plan._cache.clear()


def provide(monkeypatch, closes):
    dates, values = series(closes)
    calls = []

    def fake(symbol, **kwargs):
        calls.append((symbol, kwargs))
        return [{"date": d, "close": float(c)} for d, c in zip(dates, values)], {}

    monkeypatch.setattr(fund_plan, "yahoo_data", fake)
    return calls


def test_plan_requires_the_owner_key(client, monkeypatch):
    provide(monkeypatch, [100.0] * 1200)
    assert client.get("/api/plan/0050").status_code == 401
    wrong = client.get("/api/plan/0050", headers={"Authorization": "Bearer " + "x" * 40})
    assert wrong.status_code == 401
    monkeypatch.delenv("COMMUNITY_ADMIN_TOKEN")
    assert client.get("/api/plan/0050").status_code == 503


def test_plan_page_is_private_and_uncached(client):
    response = client.get("/plan")
    assert response.status_code == 200
    assert "0050 資金計畫" in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_plan_returns_percentages_and_caches_history(client, monkeypatch):
    calls = provide(monkeypatch, list(np.linspace(50, 100, 1500)))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    body = client.get("/api/plan/0050?months=12&horizon_months=24", headers=headers).json()
    assert body["symbol"] == "0050.TW" and body["latest"]["close"] == 100.0
    assert calls == [("0050.TW", {"history_range": "max"})]
    sim = body["simulation"]
    # Steadily rising prices: buying everything up front beats spreading it out.
    assert sim["lump_sum"]["median"] > sim["monthly"]["median"] > 0
    assert sim["monthly_beats_lump_pct"] == 0
    assert [row["share_pct"] for row in sim["satellite"]] == [0, 10, 20]
    assert sim["satellite"][0]["beats_monthly_pct"] is None
    assert body["max_drawdown"]["pct"] == 0
    client.get("/api/plan/0050", headers=headers)
    assert len(calls) == 1  # Served from cache.


def test_plan_rejects_horizon_shorter_than_buying_period(client, monkeypatch):
    provide(monkeypatch, [100.0] * 1200)
    response = client.get(
        "/api/plan/0050?months=24&horizon_months=12",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 422


def test_plan_reports_unavailable_history(client, monkeypatch):
    def failing(symbol, **kwargs):
        raise DataSourceError("hidden provider text", code="us_rate_limited")

    monkeypatch.setattr(fund_plan, "yahoo_data", failing)
    response = client.get("/api/plan/0050", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503
    assert "hidden" not in response.text


def test_max_drawdown_finds_peak_trough_and_recovery():
    dates, closes = series([100, 120, 60, 90, 121, 130])
    result = fund_plan.max_drawdown(dates, closes)
    assert result["pct"] == -50.0
    assert (result["peak_date"], result["trough_date"]) == (dates[1], dates[2])
    assert result["recovery_date"] == dates[4] and result["recovery_trading_days"] == 3


def test_max_drawdown_without_recovery():
    dates, closes = series([100, 80, 90])
    assert fund_plan.max_drawdown(dates, closes)["recovery_date"] is None


def test_satellite_sells_into_strength_and_buys_back():
    closes = np.array([100.0, 110.0, 98.0, 98.0])
    value, trades = fund_plan._satellite(closes, 0, 3, up=0.08, down=0.10, fraction=0.5)
    assert trades == 2
    shares = 1 / (100 * (1 + fund_plan.BUY_FEE))
    cash = shares * 0.5 * 110 * (1 - fund_plan.SELL_COST)
    expected = (shares * 0.5 + cash / (98 * (1 + fund_plan.BUY_FEE))) * 98
    assert value == pytest.approx(expected)


def test_simulation_needs_enough_history():
    with pytest.raises(ValueError):
        fund_plan.simulate(
            np.ones(100), months=12, horizon_months=36, up=0.08, down=0.1, fraction=0.33
        )
