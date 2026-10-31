"""Numerical and chronological invariants for the baseline forecasting workflow."""

from datetime import date, timedelta

import numpy as np
import pytest

import stockpredict.forecast as forecast
from stockpredict.forecast import analyze, conditional_forecast, fit_predict


def points_for(prices, start=date(2025, 1, 6)):
    result = []
    day = start
    for price in prices:
        while day.weekday() > 4:
            day += timedelta(days=1)
        result.append({"date": day.isoformat(), "close": float(price)})
        day += timedelta(days=1)
    return result


def variable_prices(length=100):
    rng = np.random.default_rng(31)
    return 120 * np.exp(np.cumsum(rng.normal(0.0008, 0.018, length)))


def test_flat_prices_forecast_stays_flat_and_backtest_has_zero_error():
    result = analyze(points_for(np.full(100, 100.0)), horizon=10)

    assert len(result["forecast"]) == 10
    for point in result["forecast"]:
        assert point["close"] == pytest.approx(100)
        assert point["lower"] == pytest.approx(100)
        assert point["upper"] == pytest.approx(100)
        assert point["lower"] <= point["close"] <= point["upper"]
    assert result["summary"]["annualized_volatility_pct"] == pytest.approx(0)
    assert result["summary"]["forecast_change_pct"] == pytest.approx(0)
    assert result["backtest"]["mae"] == pytest.approx(0, abs=1e-10)
    assert result["backtest"]["baseline_mae"] == pytest.approx(0)
    assert result["backtest"]["direction_accuracy_pct"] == pytest.approx(100)


def test_forecasts_are_finite_positive_and_ordered_after_history():
    history = points_for(variable_prices())
    result = analyze(history, horizon=30)

    assert result["history"] == history
    assert result["as_of"] == history[-1]["date"]
    assert len(result["forecast"]) == 30
    previous_date = date.fromisoformat(history[-1]["date"])
    for point in result["forecast"]:
        day = date.fromisoformat(point["date"])
        assert day > previous_date
        assert day.weekday() < 5
        assert np.isfinite([point["close"], point["lower"], point["upper"]]).all()
        assert 0 < point["lower"] <= point["close"] <= point["upper"]
        previous_date = day
    assert result["summary"]["last_close"] == pytest.approx(history[-1]["close"])
    assert result["summary"]["day_change_pct"] == pytest.approx(
        100 * (history[-1]["close"] / history[-2]["close"] - 1)
    )


def test_backtest_refits_using_only_prices_available_before_each_observation():
    """Recompute reported errors from independent chronological predictions."""
    prices = variable_prices(120)
    result = analyze(points_for(prices), horizon=5)
    count = min(30, len(prices) // 5)
    indexes = range(len(prices) - count, len(prices))
    predictions = np.array([fit_predict(prices[:index]) for index in indexes])
    actual = prices[-count:]
    baseline = prices[-count - 1 : -1]
    error = predictions - actual

    assert result["backtest"]["observations"] == count
    assert result["backtest"]["mae"] == pytest.approx(np.mean(np.abs(error)))
    assert result["backtest"]["rmse"] == pytest.approx(np.sqrt(np.mean(error**2)))
    assert result["backtest"]["mape_pct"] == pytest.approx(100 * np.mean(np.abs(error / actual)))
    assert result["backtest"]["baseline_mae"] == pytest.approx(np.mean(np.abs(baseline - actual)))
    assert result["backtest"]["model_beats_baseline"] == (
        result["backtest"]["mae"] < result["backtest"]["baseline_mae"]
    )


def test_backtest_does_not_depend_on_requested_future_horizon():
    history = points_for(variable_prices())
    assert analyze(history, horizon=1)["backtest"] == analyze(history, horizon=30)["backtest"]


def test_each_backtest_model_receives_only_its_historical_prefix(monkeypatch):
    prices = variable_prices(120)
    supplied_prices = []

    def record_fit(history):
        supplied_prices.append(history.copy())
        return fit_predict(history)

    monkeypatch.setattr(forecast, "fit_predict", record_fit)
    analyze(points_for(prices), horizon=5)
    count = min(30, len(prices) // 5)
    assert len(supplied_prices) == count
    for index, history in enumerate(supplied_prices, start=len(prices) - count):
        np.testing.assert_array_equal(history, prices[:index])


@pytest.mark.parametrize("horizon", [0, 31, -5])
def test_analyze_rejects_unsupported_horizons(horizon):
    with pytest.raises(ValueError):
        analyze(points_for(variable_prices()), horizon=horizon)


@pytest.mark.parametrize("price", [0.0, -1.0, float("nan"), float("inf"), 1e-10, 1e13])
def test_analyze_rejects_non_positive_or_non_finite_prices(price):
    history = points_for(variable_prices())
    history[50]["close"] = price
    with pytest.raises(ValueError):
        analyze(history, horizon=5)


def test_analyze_rejects_insufficient_data():
    with pytest.raises(ValueError):
        analyze(points_for(variable_prices(59)), horizon=5)


def test_analyze_rejects_duplicate_dates():
    history = points_for(variable_prices())
    history[50]["date"] = history[49]["date"]
    with pytest.raises(ValueError):
        analyze(history, horizon=5)


def test_analyze_rejects_out_of_order_data():
    with pytest.raises(ValueError):
        analyze(list(reversed(points_for(variable_prices()))), horizon=5)


def test_analyze_rejects_invalid_date():
    history = points_for(variable_prices())
    history[50]["date"] = "2025-02-30"
    with pytest.raises(ValueError):
        analyze(history, horizon=5)


def test_conditional_path_uses_first_estimate_then_original_history_coefficients(monkeypatch):
    points = points_for(variable_prices())
    prices = np.array([point["close"] for point in points])
    original_points = [point.copy() for point in points]
    first_close = float(prices[-1]) * 0.95
    coefficients = forecast._fit(prices)
    expected = [first_close]
    recursive_prices = np.append(prices, first_close)
    for _ in range(4):
        next_close = forecast._next_price(recursive_prices, coefficients)
        expected.append(next_close)
        recursive_prices = np.append(recursive_prices, next_close)

    calls = []
    actual_fit = forecast._fit

    def record_fit(training):
        calls.append(training.copy())
        return actual_fit(training)

    monkeypatch.setattr(forecast, "_fit", record_fit)
    path = conditional_forecast(points, first_close, horizon=5)
    assert [item["close"] for item in path] == pytest.approx(expected)
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0], prices)
    assert points == original_points
    assert all(set(item) == {"date", "close"} for item in path)


@pytest.mark.parametrize("horizon", [1, 5, 10, 30])
def test_conditional_dates_match_base_and_do_not_change_base_analysis(horizon):
    points = points_for(variable_prices())
    base = analyze(points, horizon=horizon)
    path = conditional_forecast(points, base["forecast"][0]["close"] * 0.95, horizon)
    assert [item["date"] for item in path] == [item["date"] for item in base["forecast"]]
    assert path[0]["close"] == pytest.approx(base["forecast"][0]["close"] * 0.95)
    assert analyze(points, horizon=horizon) == base


@pytest.mark.parametrize("first_close", [0, -1, float("nan"), float("inf"), True, None, "bad"])
def test_conditional_path_rejects_invalid_first_price(first_close):
    with pytest.raises(ValueError):
        conditional_forecast(points_for(variable_prices()), first_close)


@pytest.mark.parametrize("horizon", [0, 31, -1, True, 1.5])
def test_conditional_path_rejects_invalid_horizon(horizon):
    with pytest.raises(ValueError):
        conditional_forecast(points_for(variable_prices()), 100, horizon)
