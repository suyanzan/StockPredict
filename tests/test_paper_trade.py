"""Reference paper trading replays the plan deterministically from its start."""

from datetime import date, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

import stockpredict.fund_plan as fund_plan
import stockpredict.paper_trade as paper
from stockpredict.main import app

TOKEN = "t" * 40


def trading_days(start, count):
    day, days = start, []
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    return days


def test_waits_for_the_first_close_on_or_after_the_start():
    assert paper.replay(["2026-11-18"], [95.0])["status"] == "waiting"


def test_whole_share_buys_respect_cash_and_minimum_fee():
    shares, cost = paper._buy(10_000, 95.0)
    assert shares == 105 and cost <= 10_000
    assert cost == 105 * 95 + paper._fee(105 * 95)
    assert paper._buy(50, 95.0) == (0, 0.0)
    assert paper._fee(10) == 1


def test_monthly_installments_and_final_remainder():
    days = trading_days(date(2026, 11, 19), 320)
    result = paper.replay(days, [100.0] * len(days), months=12)
    baseline = result["accounts"]["baseline"]
    assert baseline["installments_done"] == 12
    buys = [t for t in result["trades"] if t["account"] == "baseline"]
    assert len(buys) == 12 and buys[0]["date"] == "2026-11-19"
    assert [t["date"][:7] for t in buys] == sorted({t["date"][:7] for t in buys})
    assert 0 <= baseline["cash"] < 100  # Final installment spends the remainder.
    # Flat prices only lose the commissions.
    assert -0.2 < baseline["return_pct"] < 0


def test_partial_history_does_not_spend_future_installments():
    days = trading_days(date(2026, 11, 19), 30)
    result = paper.replay(days, [100.0] * len(days), months=12)
    baseline = result["accounts"]["baseline"]
    assert baseline["installments_done"] == 2
    assert baseline["cash"] > paper.CAPITAL * 0.8


def test_satellite_takes_profit_then_buys_back():
    days = trading_days(date(2026, 11, 19), 6)
    closes = [100.0, 104.0, 109.0, 103.0, 98.0, 99.0]
    result = paper.replay(days, closes, months=1, satellite=0.1, up=0.08, down=0.1)
    reasons = [t["reason"] for t in result["trades"] if t["account"] == "plan"]
    assert reasons == ["monthly", "satellite_start", "take_profit", "buy_back"]
    sale = next(t for t in result["trades"] if t["reason"] == "take_profit")
    start = next(t for t in result["trades"] if t["reason"] == "satellite_start")
    assert sale["date"] == days[2] and sale["shares"] == int(start["shares"] * 0.33)
    assert result["series"][-1]["date"] == days[-1]


def test_without_satellite_plan_matches_baseline():
    days = trading_days(date(2026, 11, 19), 120)
    closes = list(90 + 10 * np.sin(np.arange(120) / 9))
    result = paper.replay(days, closes, satellite=0)
    assert result["accounts"]["plan"] == result["accounts"]["baseline"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COMMUNITY_ADMIN_TOKEN", TOKEN)
    fund_plan._cache.clear()
    with TestClient(app) as instance:
        yield instance
    fund_plan._cache.clear()


def test_paper_endpoint_is_owner_only(client, monkeypatch):
    days = trading_days(date(2026, 11, 19), 40)
    monkeypatch.setattr(
        fund_plan,
        "yahoo_data",
        lambda symbol, **_: ([{"date": d, "close": 95.0} for d in days], {}),
    )
    assert client.get("/api/plan/paper").status_code == 401
    response = client.get("/api/plan/paper", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert set(response.json()["accounts"]) == {"plan", "baseline"}
