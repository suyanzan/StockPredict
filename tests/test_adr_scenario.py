"""Signed ADR scenario assumptions remain separate from measured forecasts."""

from copy import deepcopy

import pytest
from test_overnight import fixture_data

from stockpredict.adr_scenario import directional_adr_forecast
from stockpredict.forecast import analyze


def quote_for(close=96.0, *, symbol="UMC"):
    return {
        "symbol": symbol,
        "currency": "USD",
        "session_date": "2026-10-30",
        "previous_session_date": "2026-10-29",
        "close": close,
        "previous_close": 100.0,
    }


@pytest.mark.parametrize("symbol", ["UMC", "TSM"])
@pytest.mark.parametrize(("close", "first_adjustment"), [(96, -2), (104, 2), (100, 0)])
def test_five_days_retain_the_observed_adr_direction_relative_to_flat_taiwan_baseline(
    symbol, close, first_adjustment
):
    points, _ = fixture_data(constant=True)
    path, method = directional_adr_forecast(points, quote_for(close, symbol=symbol))
    assert len(path) == 5
    assert method["adr_symbol"] == symbol
    assert method["adr_change_pct"] == pytest.approx(first_adjustment * 2)
    expected_adjustments = [first_adjustment * weight for weight in (1, 0.8, 0.64, 0.512, 0.4096)]
    assert [row["adr_adjustment_pct"] for row in path] == pytest.approx(expected_adjustments)
    assert [row["close"] for row in path] == pytest.approx(
        [50 + adjustment / 2 for adjustment in expected_adjustments]
    )
    for row in path:
        if first_adjustment < 0:
            assert row["close"] < 50
        elif first_adjustment > 0:
            assert row["close"] > 50
        else:
            assert row["close"] == pytest.approx(50)


@pytest.mark.parametrize(("close", "expected_first"), [(20, -5), (180, 5)])
def test_extreme_adr_move_is_capped_once_and_decays_instead_of_compounding(close, expected_first):
    points, _ = fixture_data(constant=True)
    path, method = directional_adr_forecast(points, quote_for(close))
    assert method["capped"] is True
    assert method["initial_adjustment_pct"] == expected_first
    assert path[0]["close"] == pytest.approx(50 * (1 + expected_first / 100))
    assert path[4]["adr_adjustment_pct"] == pytest.approx(expected_first * 0.4096)
    assert path[4]["close"] == pytest.approx(50 * (1 + expected_first * 0.4096 / 100))
    assert abs(path[4]["close"] - 50) < abs(path[0]["close"] - 50)


@pytest.mark.parametrize("horizon", [1, 5, 10, 30])
def test_directional_overlay_preserves_original_dates_and_history_for_each_horizon(horizon):
    points, _ = fixture_data()
    quote = quote_for()
    original_points, original_quote = deepcopy(points), deepcopy(quote)
    original_analysis = analyze(points, horizon)
    path, method = directional_adr_forecast(points, quote, horizon)
    assert len(path) == horizon
    assert [row["date"] for row in path] == [row["date"] for row in original_analysis["forecast"]]
    assert all(
        row["close"] < base["close"] for row, base in zip(path, original_analysis["forecast"])
    )
    assert method == {
        "id": "adr_directional_v1",
        "adr_symbol": "UMC",
        "session_date": "2026-10-30",
        "previous_session_date": "2026-10-29",
        "adr_change_pct": pytest.approx(-4),
        "sensitivity": 0.5,
        "daily_decay": 0.8,
        "max_adjustment_pct": 5.0,
        "uncapped_adjustment_pct": pytest.approx(-2),
        "initial_adjustment_pct": pytest.approx(-2),
        "capped": False,
    }
    assert points == original_points and quote == original_quote
    assert analyze(points, horizon) == original_analysis


def test_price_return_overrides_a_conflicting_supplied_percentage():
    points, _ = fixture_data(constant=True)
    quote = {**quote_for(96), "day_change_pct": 99, "day_change": 99}
    path, method = directional_adr_forecast(points, quote)
    assert method["adr_change_pct"] == pytest.approx(-4)
    assert all(row["close"] < 50 for row in path)


@pytest.mark.parametrize(("growth", "adr_close"), [(1.03, 98), (0.97, 102)])
def test_signed_adjustment_does_not_force_the_final_stock_trend(growth, adr_close):
    points, _ = fixture_data()
    for index, point in enumerate(points):
        point["close"] = 50 * growth**index
    baseline = analyze(points)["forecast"]
    path, _ = directional_adr_forecast(points, quote_for(adr_close))
    for row, base in zip(path, baseline):
        if growth > 1:
            assert points[-1]["close"] < row["close"] < base["close"]
        else:
            assert points[-1]["close"] > row["close"] > base["close"]


def test_monday_can_compare_friday_without_treating_weekend_as_missing_sessions():
    points, _ = fixture_data()
    quote = {
        **quote_for(),
        "session_date": "2026-11-02",
        "previous_session_date": "2026-10-30",
    }
    path, method = directional_adr_forecast(points, quote)
    assert len(path) == 5
    assert method["previous_session_date"] == "2026-10-30"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("symbol", "SOXX"),
        ("currency", "TWD"),
        ("session_date", "2026-10-31"),
        ("session_date", "20261030"),
        ("session_date", None),
        ("previous_session_date", "2026-10-28"),
        ("previous_session_date", "2026-10-30"),
        ("previous_session_date", "2026-11-02"),
        ("previous_session_date", None),
        ("close", 0),
        ("close", -1),
        ("close", float("nan")),
        ("close", float("inf")),
        ("close", True),
        ("previous_close", 0),
        ("previous_close", float("inf")),
        ("previous_close", None),
        ("previous_close", True),
    ],
)
def test_invalid_or_multi_session_quote_is_rejected_without_a_directional_path(field, value):
    points, _ = fixture_data()
    with pytest.raises(ValueError):
        directional_adr_forecast(points, {**quote_for(), field: value})


@pytest.mark.parametrize("horizon", [0, 31, True, 1.5])
def test_invalid_horizon_is_rejected(horizon):
    points, _ = fixture_data()
    with pytest.raises(ValueError):
        directional_adr_forecast(points, quote_for(), horizon)
