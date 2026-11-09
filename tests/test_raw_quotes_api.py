"""Expose USD source closes independently from model availability or scenarios."""

from copy import deepcopy
from datetime import date, datetime
from math import exp

import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_overnight import fixture_data

import stockpredict.main as main
import stockpredict.overnight as overnight
from stockpredict.data import DataSourceError

pytestmark = pytest.mark.usefixtures("published_history_clock")

NOW = datetime.fromisoformat("2026-10-31T08:00:00+08:00")
PROFILE_CASES = [
    ("2303", "umc", ("UMC", "SOXX")),
    ("2330", "tsmc", ("TSM", "SOXX")),
    ("0050", "taiwan_market", ("SPY", "QQQ")),
]


def as_csv(rows):
    return "Date,Close\n" + "\n".join(f"{row['date']},{row['close']}" for row in rows)


@pytest.fixture
def client():
    with TestClient(main.app) as instance:
        yield instance


@pytest.fixture
def quote_history(monkeypatch):
    points, seeds = fixture_data(last=date(2026, 10, 30))
    factors = {
        symbol: [deepcopy(row) for row in seeds[seed] if row["date"] <= "2026-10-30"]
        for symbol, seed in (
            ("UMC", "UMC"),
            ("TSM", "UMC"),
            ("SPY", "UMC"),
            ("SOXX", "SOXX"),
            ("QQQ", "SOXX"),
        )
    }
    for row in factors["UMC"]:
        if row["date"] == "2026-10-29":
            row["close"] = 18.04
        elif row["date"] == "2026-10-30":
            row["close"] = 16.68
    builder = main.build_context
    calls = {"auto": [], "yahoo": []}

    def target(symbol, source):
        return deepcopy(points), {
            "name": symbol,
            "currency": "TWD",
            "source": source,
            "source_label": "Test Taiwan history",
        }

    def auto(pair, required):
        calls["auto"].append((tuple(pair), required))
        return {symbol: deepcopy(factors[symbol]) for symbol in pair}, {
            "snapshot_session_date": "2026-10-30",
            "generated_at": "2026-10-30T20:20:00+00:00",
            "provider": "Yahoo Finance",
        }

    def yahoo(pair=("UMC", "SOXX")):
        calls["yahoo"].append(tuple(pair))
        return {symbol: deepcopy(factors[symbol]) for symbol in pair}

    monkeypatch.setattr(main, "twse_data", lambda symbol: target(symbol, "twse"))
    monkeypatch.setattr(main, "yahoo_data", lambda symbol: target(symbol, "yahoo"))
    monkeypatch.setattr(main, "auto_csv_factors", auto)
    monkeypatch.setattr(main, "overnight_factors", yahoo)
    monkeypatch.setattr(main, "pending_context", lambda p: overnight.pending_context(p, now=NOW))
    monkeypatch.setattr(main, "reference_timing", lambda p: overnight.reference_timing(p, now=NOW))
    monkeypatch.setattr(main, "build_context", lambda p, f, **kw: builder(p, f, now=NOW, **kw))
    return {"points": points, "factors": factors, "calls": calls}


def request_context(client, history, *, symbol="2303", source="auto_csv", horizon=5):
    pairs = {"2303": ("UMC", "SOXX"), "2330": ("TSM", "SOXX"), "0050": ("SPY", "QQQ")}
    if source == "csv":
        return client.post(
            "/api/analysis/overnight/csv",
            json={
                "symbol": symbol,
                "horizon": horizon,
                "factor_csvs": {
                    factor: as_csv(history["factors"][factor]) for factor in pairs[symbol]
                },
            },
        )
    return client.get(
        "/api/analysis",
        params={
            "symbol": symbol,
            "source": "twse",
            "horizon": horizon,
            "market_context": "us_overnight",
            "factor_source": source,
        },
    )


@pytest.mark.parametrize("source", ["auto_csv", "yahoo", "csv"])
def test_umc_raw_usd_close_is_not_the_tw_price_or_an_adr_conversion(client, quote_history, source):
    response = request_context(client, quote_history, source=source)
    assert response.status_code == 200, response.text
    result = response.json()
    context = result["market_context"]
    quote = next(item for item in context["quotes"] if item["symbol"] == "UMC")
    assert quote["currency"] == "USD" and quote["data_source"] == source
    assert quote["session_date"] == "2026-10-30" and quote["close"] == 16.68
    assert quote["previous_session_date"] == "2026-10-29" and quote["previous_close"] == 18.04
    assert quote["day_change"] == pytest.approx(16.68 - 18.04)
    assert quote["day_change_pct"] == pytest.approx((16.68 / 18.04 - 1) * 100)
    assert result["summary"]["last_close"] == quote_history["points"][-1]["close"]
    assert result["currency"] == "TWD"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("symbol", "profile_id", "pair"), PROFILE_CASES)
def test_raw_quote_symbols_follow_the_selected_profile(
    client, quote_history, symbol, profile_id, pair
):
    response = request_context(client, quote_history, symbol=symbol)
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert context["reference_profile"]["id"] == profile_id
    assert tuple(quote["symbol"] for quote in context["quotes"]) == pair
    assert all(quote["currency"] == "USD" for quote in context["quotes"])
    assert all(quote["session_date"] == "2026-10-30" for quote in context["quotes"])
    assert all(quote["data_source"] == "auto_csv" for quote in context["quotes"])


@pytest.mark.parametrize("horizon", [1, 5, 10])
@pytest.mark.parametrize(("symbol", "profile_id", "pair"), PROFILE_CASES)
def test_conditional_path_matches_requested_dates_and_does_not_change_original_forecast(
    client, quote_history, horizon, symbol, profile_id, pair
):
    base = client.get(
        "/api/analysis", params={"symbol": symbol, "source": "twse", "horizon": horizon}
    ).json()
    response = request_context(client, quote_history, symbol=symbol, horizon=horizon)
    assert response.status_code == 200, response.text
    result = response.json()
    context = result["market_context"]
    assert context["status"] == "ready"
    scenario = context["scenario_forecast"]
    assert len(scenario) == horizon
    assert [row["date"] for row in scenario] == [row["date"] for row in base["forecast"]]
    assert scenario[0]["date"] == context["forecast"]["date"] == "2026-11-02"
    for key in ("forecast", "history", "summary", "backtest", "as_of"):
        assert result[key] == base[key]

    if profile_id in ("umc", "tsmc"):
        method = context["scenario_method"]
        assert method["id"] == "adr_directional_v1" and method["adr_symbol"] == pair[0]
        quote = next(item for item in context["quotes"] if item["symbol"] == pair[0])
        expected_adjustment = float(np.clip(quote["day_change_pct"] * 0.5, -5, 5))
        for index, (row, original) in enumerate(zip(scenario, base["forecast"])):
            assert row["adr_adjustment_pct"] == pytest.approx(expected_adjustment * 0.8**index)
            assert row["close"] == pytest.approx(
                original["close"] * (1 + expected_adjustment * 0.8**index / 100)
            )
        return

    assert context.get("scenario_method") is None
    assert scenario[0]["close"] == context["forecast"]["close"]
    # Independently reproduce only the Taiwan continuation after the US-informed
    # first step, using coefficients fitted once on the original historical data.
    prices = np.array([row["close"] for row in quote_history["points"]])
    returns = np.diff(np.log(prices))
    design = np.array([[1.0, *returns[index - 5 : index]] for index in range(5, len(returns))])
    coefficients = np.linalg.solve(
        design.T @ design + np.diag([0.0] + [0.01] * 5), design.T @ returns[5:]
    )
    future = np.append(prices, scenario[0]["close"])
    for step in scenario[1:]:
        feature = np.r_[1.0, np.diff(np.log(future))[-5:]]
        expected = future[-1] * exp(float(np.clip(feature @ coefficients, -0.2, 0.2)))
        assert step["close"] == pytest.approx(expected)
        future = np.append(future, expected)


def test_valid_raw_quotes_remain_when_model_overlap_is_insufficient(client, quote_history):
    for symbol in ("UMC", "SOXX"):
        quote_history["factors"][symbol] = quote_history["factors"][symbol][-60:]
    response = request_context(client, quote_history, source="csv")
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert (
        context["status"] == "unavailable" and context["reason"] == "insufficient_aligned_history"
    )
    assert context["forecast"] is None and context["scenario_forecast"] == []
    assert context.get("scenario_method") is None
    assert [quote["symbol"] for quote in context["quotes"]] == ["UMC", "SOXX"]
    assert context["quotes"][0]["close"] == 16.68
    assert all(quote["data_source"] == "csv" for quote in context["quotes"])


def test_partial_current_csv_quotes_do_not_disappear_when_the_pair_cannot_be_modeled(
    client, quote_history
):
    quote_history["factors"]["SOXX"] = [
        row for row in quote_history["factors"]["SOXX"] if row["date"] != "2026-10-30"
    ]
    response = request_context(client, quote_history, source="csv")
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert context["status"] == "unavailable" and context["reason"] == "missing_us_sessions"
    assert context["forecast"] is None and context["scenario_forecast"] == []
    assert context.get("scenario_method") is None
    assert len(context["quotes"]) == 1
    assert context["quotes"][0]["symbol"] == "UMC"
    assert context["quotes"][0]["close"] == 16.68
    assert context["quotes"][0]["data_source"] == "csv"


def test_unclosed_session_returns_no_quotes_or_scenario_without_reading_provider(
    client, quote_history, monkeypatch
):
    before_close = datetime.fromisoformat("2026-10-31T04:14:59+08:00")
    monkeypatch.setattr(
        main, "pending_context", lambda p: overnight.pending_context(p, now=before_close)
    )
    monkeypatch.setattr(main, "auto_csv_factors", lambda *args: pytest.fail("Session still open"))
    response = request_context(client, quote_history)
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert context["status"] == "waiting"
    assert context["quotes"] == context["scenario_forecast"] == []
    assert context.get("scenario_method") is None


def test_provider_failure_does_not_show_old_quotes_or_comparison_path(
    client, quote_history, monkeypatch
):
    def unavailable(*args):
        raise DataSourceError("No matching snapshot", code="auto_csv_missing_session")

    monkeypatch.setattr(main, "auto_csv_factors", unavailable)
    response = request_context(client, quote_history)
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert context["status"] == "unavailable" and context["reason"] == "auto_csv_missing_session"
    assert context["quotes"] == context["scenario_forecast"] == []
    assert context["forecast"] is None
    assert context.get("scenario_method") is None


def test_unseen_future_us_prices_do_not_change_raw_quotes_or_conditional_path(
    client, quote_history
):
    first = request_context(client, quote_history, horizon=10).json()["market_context"]
    for symbol in ("UMC", "SOXX"):
        quote_history["factors"][symbol].append({"date": "2026-11-02", "close": 999999.0})
    second = request_context(client, quote_history, horizon=10).json()["market_context"]
    assert second["quotes"] == first["quotes"]
    assert second["forecast"] == first["forecast"]
    assert second["scenario_forecast"] == first["scenario_forecast"]
    assert second["scenario_method"] == first["scenario_method"]


@pytest.mark.parametrize("source", ["auto_csv", "yahoo", "csv"])
@pytest.mark.parametrize("symbol", ["2303", "2330"])
@pytest.mark.parametrize(("close", "direction"), [(96, -1), (104, 1), (100, 0)])
def test_signed_adr_effect_reaches_all_five_days_independently_of_opposing_sector_move(
    client, quote_history, source, symbol, close, direction
):
    adr = "UMC" if symbol == "2303" else "TSM"
    for row in quote_history["factors"][adr]:
        if row["date"] == "2026-10-29":
            row["close"] = 100
        elif row["date"] == "2026-10-30":
            row["close"] = close
    for row in quote_history["factors"]["SOXX"]:
        if row["date"] == "2026-10-29":
            row["close"] = 100
        elif row["date"] == "2026-10-30":
            row["close"] = 130 if direction <= 0 else 70
    response = request_context(client, quote_history, symbol=symbol, source=source)
    assert response.status_code == 200, response.text
    result = response.json()
    context = result["market_context"]
    assert context["status"] == "ready"
    assert len(context["scenario_forecast"]) == 5
    assert context["scenario_method"]["adr_change_pct"] == pytest.approx(close - 100)
    for adjusted, original in zip(context["scenario_forecast"], result["forecast"]):
        assert adjusted["date"] == original["date"]
        if direction < 0:
            assert adjusted["close"] < original["close"]
        elif direction > 0:
            assert adjusted["close"] > original["close"]
        else:
            assert adjusted["close"] == original["close"]
    # Sector data and its learned model remain independently available; they
    # must not be silently described as ingredients of this ADR-only rule.
    assert any(item["symbol"] == "SOXX" for item in context["factors"])
    assert context["forecast"] is not None and context["backtest"] is not None


def test_directional_rule_uses_latest_adr_session_not_cumulative_model_return(
    client, quote_history, monkeypatch
):
    original = overnight._window_returns

    def opposing_window(baseline, sessions, factors, factor_symbols=overnight.FACTORS):
        value = original(baseline, sessions, factors, factor_symbols)
        if value is not None and sessions[-1] == date(2026, 10, 30):
            # A cumulative model input and the latest session need not have the
            # same sign. Isolate that distinction independently of alignment.
            return np.log(np.array([1.2, 1.1]))
        return value

    monkeypatch.setattr(overnight, "_window_returns", opposing_window)
    response = request_context(client, quote_history)
    assert response.status_code == 200, response.text
    result = response.json()
    context = result["market_context"]
    assert context["factors"][0]["return_pct"] == pytest.approx(20)
    assert context["scenario_method"]["adr_change_pct"] == pytest.approx((16.68 / 18.04 - 1) * 100)
    assert all(
        row["close"] < original["close"]
        for row, original in zip(context["scenario_forecast"], result["forecast"])
    )
