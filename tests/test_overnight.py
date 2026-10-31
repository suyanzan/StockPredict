"""Cross-market availability, honest missing data and chronological forecasts."""

from copy import deepcopy
from datetime import date, datetime, timedelta

import numpy as np
import pytest

import stockpredict.overnight as overnight
from stockpredict.forecast import analyze, fit_predict


def weekdays(start, end):
    days = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def fixture_data(last=date(2026, 10, 29), *, constant=False):
    rng = np.random.default_rng(712)
    us_days = weekdays(date(2026, 1, 1), last + timedelta(days=14))
    factors = {}
    for index, symbol in enumerate(overnight.FACTORS):
        returns = np.zeros(len(us_days)) if constant else rng.normal(0, 0.012, len(us_days))
        prices = (30 + 100 * index) * np.exp(np.cumsum(returns))
        factors[symbol] = [
            {"date": day.isoformat(), "close": float(price)} for day, price in zip(us_days, prices)
        ]
    tw_days = weekdays(date(2026, 2, 2), last)
    returns = np.zeros(len(tw_days)) if constant else rng.normal(0, 0.01, len(tw_days))
    prices = 50 * np.exp(np.cumsum(returns))
    points = [
        {"date": day.isoformat(), "close": float(price)} for day, price in zip(tw_days, prices)
    ]
    return points, factors


def ready_now():
    return datetime.fromisoformat("2026-10-30T08:00:00+08:00")


def test_ready_forecast_uses_the_night_after_taiwan_last_close():
    points, factors = fixture_data()
    result = overnight.build_context(points, factors, now=ready_now())
    assert result["status"] == "ready" and result["reason"] is None
    assert result["target_date"] == "2026-10-30"
    assert result["decision_cutoff"] == "2026-10-30T00:00:00+00:00"
    assert result["assumed_availability"] is True
    assert result["forecast"]["date"] == "2026-10-30"
    assert result["forecast"]["base_close"] == points[-1]["close"]
    for item in result["factors"]:
        assert item["first_session"] == item["last_session"] == "2026-10-29"
        assert item["available_at"] == "2026-10-29T20:15:00+00:00"
        assert item["samples"] == 60
        assert -1 <= item["correlation"] <= 1
        prices = {row["date"]: row["close"] for row in factors[item["symbol"]]}
        assert item["return_pct"] == pytest.approx(
            (prices["2026-10-29"] / prices["2026-10-28"] - 1) * 100
        )


@pytest.mark.parametrize(
    ("now_text", "expected"),
    [
        ("2026-10-30T04:14:59+08:00", "waiting"),
        ("2026-10-30T04:15:00+08:00", "ready"),
        ("2026-10-30T09:00:00+08:00", "ready"),
        ("2026-10-30T13:29:59+08:00", "ready"),
        ("2026-10-30T13:30:00+08:00", "unavailable"),
    ],
)
def test_current_us_session_buffer_and_taiwan_stale_history_boundary(now_text, expected):
    points, factors = fixture_data()
    result = overnight.build_context(points, factors, now=datetime.fromisoformat(now_text))
    assert result["status"] == expected
    if expected == "waiting":
        assert result["reason"] == "us_session_not_closed"
        assert result["forecast"] is None and result["backtest"] is None
        assert result["factors"] == [] and result["correlations_window"] is None
    elif expected == "unavailable":
        assert result["reason"] == "stale_history"
        assert result["forecast"] is None and result["factors"] == []


def test_future_taiwan_close_is_not_accepted_as_known_history():
    points, factors = fixture_data()
    result = overnight.build_context(
        points, factors, now=datetime.fromisoformat("2026-10-29T12:00:00+08:00")
    )
    assert result["status"] == "unavailable" and result["reason"] == "incomplete_history"


def test_pending_context_waits_without_inspecting_or_computing_old_us_data(monkeypatch):
    points, _ = fixture_data()
    now = datetime.fromisoformat("2026-10-30T04:14:59+08:00")
    monkeypatch.setattr(
        overnight, "_historical_rows", lambda *args: pytest.fail("Old US history was used")
    )
    context = overnight.pending_context(points, now=now)
    assert context["status"] == "waiting"
    assert context["reason"] == "us_session_not_closed"
    assert context["target_date"] == "2026-10-30"
    assert context["required_us_session_date"] == "2026-10-29"
    assert context["forecast"] is None and context["backtest"] is None
    assert context["factors"] == [] and context["correlations_window"] is None
    assert overnight.build_context(points, {}, now=now) == context


@pytest.mark.parametrize(
    ("now_text", "pending"),
    [
        ("2026-10-30T04:14:59+08:00", True),
        ("2026-10-30T04:15:00+08:00", False),
    ],
)
def test_preflight_only_permits_download_after_required_us_close_buffer(now_text, pending):
    points, _ = fixture_data()
    context = overnight.pending_context(points, now=datetime.fromisoformat(now_text))
    assert (context is not None) is pending


def test_previous_us_day_does_not_replace_the_required_day_after_close():
    points, factors = fixture_data()
    for symbol in factors:
        factors[symbol] = [row for row in factors[symbol] if row["date"] < "2026-10-29"]
    assert overnight.pending_context(points, now=ready_now()) is None
    context = overnight.build_context(points, factors, now=ready_now())
    assert context["status"] == "unavailable" and context["reason"] == "missing_us_sessions"
    assert context["forecast"] is None
    assert context["factors"] == [] and context["backtest"] is None
    assert context["correlations_window"] is None


def test_cutoff_is_frozen_at_taiwan_open_once_open_has_passed():
    points, factors = fixture_data()
    result = overnight.build_context(
        points, factors, now=datetime.fromisoformat("2026-10-30T12:00:00+08:00")
    )
    assert result["decision_cutoff"] == "2026-10-30T01:00:00+00:00"


@pytest.mark.parametrize(
    ("day", "available"),
    [
        (date(2026, 3, 6), "2026-03-06T21:15:00+00:00"),
        (date(2026, 3, 9), "2026-03-09T20:15:00+00:00"),
        (date(2026, 11, 27), "2026-11-27T21:15:00+00:00"),
    ],
)
def test_inferred_availability_tracks_dst_and_conservatively_waits_on_half_days(day, available):
    assert overnight._available_at(day).isoformat() == available


@pytest.mark.parametrize("missing_day", ["2026-10-28", "2026-10-29"])
def test_missing_baseline_or_us_weekday_is_unavailable_not_zero_or_stale_reuse(missing_day):
    points, factors = fixture_data()
    factors["SOXX"] = [row for row in factors["SOXX"] if row["date"] != missing_day]
    result = overnight.build_context(points, factors, now=ready_now())
    assert result["status"] == "unavailable" and result["reason"] == "missing_us_sessions"
    assert result["forecast"] is None
    assert result["factors"] == [] and result["backtest"] is None
    assert result["correlations_window"] is None


def test_unconfirmed_us_holidays_exclude_dates_from_all_comparison_models():
    points, factors = fixture_data()
    # Without a US calendar, this holiday is deliberately treated as missing.
    for symbol in factors:
        factors[symbol] = [row for row in factors[symbol] if row["date"] != "2026-10-12"]
    result = overnight.build_context(points, factors, now=ready_now())
    assert result["status"] == "ready"
    dates = result["backtest"]["dates"]
    assert "2026-10-13" not in dates and "2026-10-14" not in dates
    assert result["backtest"]["observations"] == len(dates)
    lookup = {point["date"]: index for index, point in enumerate(points)}
    prices = np.array([point["close"] for point in points])
    expected_ar = np.mean(
        [abs(fit_predict(prices[: lookup[day]]) - prices[lookup[day]]) for day in dates]
    )
    expected_baseline = np.mean(
        [abs(prices[lookup[day] - 1] - prices[lookup[day]]) for day in dates]
    )
    assert result["backtest"]["ar_mae"] == pytest.approx(expected_ar)
    assert result["backtest"]["baseline_mae"] == pytest.approx(expected_baseline)
    assert result["backtest"]["baseline_direction_accuracy_pct"] == pytest.approx(
        np.mean([prices[lookup[day]] == prices[lookup[day] - 1] for day in dates]) * 100
    )


def test_taiwan_holiday_window_compounds_all_completed_us_sessions():
    points, factors = fixture_data()
    points = [point for point in points if point["date"] not in {"2026-10-28", "2026-10-29"}]
    result = overnight.build_context(
        points, factors, now=datetime.fromisoformat("2026-10-28T08:00:00+08:00")
    )
    # The public target is next weekday; historical long gaps are tested directly.
    assert result["target_date"] == "2026-10-28"
    mapped = {
        symbol: {date.fromisoformat(row["date"]): row["close"] for row in rows}
        for symbol, rows in factors.items()
    }
    baseline, sessions = overnight._session_window(date(2026, 10, 23), date(2026, 10, 29))
    assert baseline == date(2026, 10, 22)
    assert sessions == [
        date(2026, 10, 23),
        date(2026, 10, 26),
        date(2026, 10, 27),
        date(2026, 10, 28),
    ]
    values = overnight._window_returns(baseline, sessions, mapped)
    for index, symbol in enumerate(overnight.FACTORS):
        assert values[index] == pytest.approx(
            np.log(mapped[symbol][date(2026, 10, 28)] / mapped[symbol][date(2026, 10, 22)])
        )


def test_next_weekday_does_not_invent_weekend_us_sessions():
    points, factors = fixture_data(date(2026, 10, 30))
    result = overnight.build_context(
        points, factors, now=datetime.fromisoformat("2026-11-01T08:00:00+08:00")
    )
    assert result["status"] == "ready" and result["target_date"] == "2026-11-02"
    assert all(item["last_session"] == "2026-10-30" for item in result["factors"])


def test_future_us_price_perturbations_do_not_change_current_result():
    points, factors = fixture_data()
    expected = overnight.build_context(points, factors, now=ready_now())
    altered = deepcopy(factors)
    for rows in altered.values():
        for row in rows:
            if row["date"] >= "2026-10-30":
                row["close"] *= 500
    assert overnight.build_context(points, altered, now=ready_now()) == expected


def test_backtests_fit_and_standardize_each_earlier_prefix_only(monkeypatch):
    points, factors = fixture_data()
    supplied = []
    original = overnight._fit_predict

    def recording_fit(features, targets, next_features):
        supplied.append((features.copy(), targets.copy(), next_features.copy()))
        return original(features, targets, next_features)

    monkeypatch.setattr(overnight, "_fit_predict", recording_fit)
    result = overnight.build_context(points, factors, now=ready_now())
    final_features, final_targets, _ = supplied[-1]
    count = result["backtest"]["observations"]
    assert len(supplied) == count + 1
    for offset, (features, targets, next_features) in enumerate(supplied[:-1]):
        length = len(final_features) - count + offset
        np.testing.assert_array_equal(features, final_features[:length])
        np.testing.assert_array_equal(targets, final_targets[:length])
        np.testing.assert_array_equal(next_features, final_features[length])
        assert length >= 40
    # A separate fit check proves scaling uses only its actual feature argument.
    features, targets, next_features = supplied[0]
    mean, scale = features.mean(axis=0), features.std(axis=0)
    scale[scale < 1e-12] = 1
    design = np.column_stack([np.ones(len(features)), (features - mean) / scale])
    penalty = np.diag([0.0] + [1.0] * features.shape[1])
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
    expected = np.clip(np.r_[1.0, (next_features - mean) / scale] @ coefficients, -0.2, 0.2)
    assert original(features, targets, next_features) == pytest.approx(expected)


def test_future_taiwan_targets_do_not_change_earlier_backtest_predictions(monkeypatch):
    points, factors = fixture_data()
    recorded = []
    original = overnight._fit_predict

    def recording_fit(features, targets, next_features):
        prediction = original(features, targets, next_features)
        recorded.append(prediction)
        return prediction

    monkeypatch.setattr(overnight, "_fit_predict", recording_fit)
    first = overnight.build_context(points, factors, now=ready_now())
    original_predictions = recorded[:]
    recorded.clear()
    changed = deepcopy(points)
    changed[-1]["close"] *= 2
    second = overnight.build_context(changed, factors, now=ready_now())
    assert first["backtest"]["dates"] == second["backtest"]["dates"]
    # The changed last label cannot affect any held-out prediction, including
    # that label's own prediction. It is allowed to affect the final fitted model.
    np.testing.assert_array_equal(recorded[:-1], original_predictions[:-1])


def test_constant_series_has_null_correlation_and_finite_zero_change_forecast():
    points, factors = fixture_data(constant=True)
    result = overnight.build_context(points, factors, now=ready_now())
    assert result["status"] == "ready"
    assert result["forecast"]["close"] == pytest.approx(50)
    assert result["forecast"]["change_pct"] == pytest.approx(0)
    assert all(item["correlation"] is None for item in result["factors"])
    assert result["backtest"]["factor_mae"] == pytest.approx(0)
    assert result["backtest"]["baseline_direction_accuracy_pct"] == 100
    assert result["backtest"]["improvement_pct"] is None


def test_too_little_overlapping_history_is_explicitly_unavailable():
    points, factors = fixture_data()
    for symbol in factors:
        factors[symbol] = factors[symbol][-65:]
    result = overnight.build_context(points, factors, now=ready_now())
    assert result["status"] == "unavailable"
    assert result["reason"] == "insufficient_aligned_history"
    assert result["forecast"] is None and result["backtest"] is None


def test_missing_factors_and_naive_clock_are_not_silently_accepted():
    points, factors = fixture_data()
    assert overnight.build_context(points, {}, now=ready_now())["reason"] == "missing_factors"
    with pytest.raises(ValueError, match="timezone"):
        overnight.build_context(points, factors, now=datetime(2026, 10, 30, 8))


def test_known_overnight_signal_is_learned_and_changes_only_the_live_forecast():
    """A planted causal direction validates the model, not real-market accuracy."""
    points, factors = fixture_data()
    rng = np.random.default_rng(902)
    mapped = {
        symbol: {date.fromisoformat(row["date"]): row["close"] for row in rows}
        for symbol, rows in factors.items()
    }
    price = 50.0
    observed_us_returns, observed_tw_returns = [], []
    for point in points:
        # Independent alignment: preceding US business date, not the US bar
        # with the same calendar date as the Taiwan target.
        session = date.fromisoformat(point["date"]) - timedelta(days=1)
        while session.weekday() >= 5:
            session -= timedelta(days=1)
        previous = session - timedelta(days=1)
        while previous.weekday() >= 5:
            previous -= timedelta(days=1)
        us_return = np.log(mapped["UMC"][session] / mapped["UMC"][previous])
        sector_return = np.log(mapped["SOXX"][session] / mapped["SOXX"][previous])
        tw_return = 0.85 * us_return + 0.10 * sector_return + rng.normal(0, 0.0001)
        price *= np.exp(tw_return)
        point["close"] = float(price)
        observed_us_returns.append(us_return)
        observed_tw_returns.append(tw_return)

    result = overnight.build_context(points, factors, now=ready_now())
    assert result["status"] == "ready"
    umc = next(item for item in result["factors"] if item["symbol"] == "UMC")
    assert umc["correlation"] > 0.97
    expected_correlation = np.corrcoef(observed_us_returns[-60:], observed_tw_returns[-60:])[0, 1]
    assert umc["correlation"] == pytest.approx(expected_correlation)
    metrics = result["backtest"]
    assert metrics["factor_mae"] < 0.2 * metrics["ar_mae"]
    assert metrics["factor_mae"] < 0.2 * metrics["baseline_mae"]
    assert metrics["improvement_pct"] > 80

    # This US close is available now but comes after every historical Taiwan
    # target's information cutoff. Raising it must change the live prediction
    # in the learned direction without changing history or measured backtests.
    altered = deepcopy(factors)
    for row in altered["UMC"]:
        if row["date"] == "2026-10-29":
            row["close"] *= np.exp(0.03)
    updated = overnight.build_context(points, altered, now=ready_now())
    assert updated["status"] == "ready"
    assert updated["forecast"]["close"] > result["forecast"]["close"]
    assert updated["forecast"]["change_pct"] - result["forecast"]["change_pct"] > 2
    assert updated["forecast"]["base_close"] == result["forecast"]["base_close"]
    assert updated["backtest"] == result["backtest"]
    assert updated["correlations_window"] == result["correlations_window"]
    assert [item["correlation"] for item in updated["factors"]] == [
        item["correlation"] for item in result["factors"]
    ]


def test_current_raw_us_close_is_exposed_in_usd_without_rounding_or_conversion():
    points, factors = fixture_data()
    for item in factors["UMC"]:
        if item["date"] == "2026-10-28":
            item["close"] = 18.04
        elif item["date"] == "2026-10-29":
            item["close"] = 16.68
    result = overnight.build_context(points, factors, now=ready_now())
    quote = next(item for item in result["quotes"] if item["symbol"] == "UMC")
    assert quote == {
        "symbol": "UMC",
        "currency": "USD",
        "session_date": "2026-10-29",
        "close": 16.68,
        "previous_session_date": "2026-10-28",
        "previous_close": 18.04,
        "day_change": pytest.approx(-1.36),
        "day_change_pct": pytest.approx((16.68 / 18.04 - 1) * 100),
    }


def test_raw_quotes_remain_available_when_model_has_too_few_aligned_rows():
    points, factors = fixture_data()
    factors = {symbol: rows[-65:] for symbol, rows in factors.items()}
    result = overnight.build_context(points, factors, now=ready_now())
    assert result["status"] == "unavailable"
    assert result["reason"] == "insufficient_aligned_history"
    assert [item["symbol"] for item in result["quotes"]] == ["UMC", "SOXX"]
    assert all(item["session_date"] == "2026-10-29" for item in result["quotes"])
    assert result["forecast"] is None and result["scenario_forecast"] == []


@pytest.mark.parametrize("problem", ["missing", "invalid", "missing_current"])
def test_one_verified_quote_is_exposed_when_the_other_factor_cannot_be_used(problem):
    points, factors = fixture_data()
    if problem == "missing":
        del factors["SOXX"]
    elif problem == "invalid":
        factors["SOXX"][0]["close"] = float("nan")
    else:
        factors["SOXX"] = [row for row in factors["SOXX"] if row["date"] != "2026-10-29"]
    result = overnight.build_context(points, factors, now=ready_now())
    assert result["status"] == "unavailable"
    assert [item["symbol"] for item in result["quotes"]] == ["UMC"]
    assert result["quotes"][0]["session_date"] == "2026-10-29"
    assert result["forecast"] is None and result["scenario_forecast"] == []


def test_raw_day_change_uses_previous_observed_row_not_the_whole_overnight_window():
    points, factors = fixture_data()
    # Missing a baseline prevents the combined model, but does not hide an
    # independently valid current quote or mislabel the previous observed date.
    factors["UMC"] = [row for row in factors["UMC"] if row["date"] != "2026-10-28"]
    lookup = {row["date"]: row["close"] for row in factors["UMC"]}
    result = overnight.build_context(points, factors, now=ready_now())
    quote = next(item for item in result["quotes"] if item["symbol"] == "UMC")
    assert result["reason"] == "missing_us_sessions"
    assert quote["previous_session_date"] == "2026-10-27"
    assert quote["day_change_pct"] == pytest.approx(
        (lookup["2026-10-29"] / lookup["2026-10-27"] - 1) * 100
    )
    assert result["scenario_forecast"] == []


def test_raw_current_quotes_never_reuse_previous_day_or_expose_future_prices():
    points, factors = fixture_data()
    for symbol in factors:
        factors[symbol] = [row for row in factors[symbol] if row["date"] != "2026-10-29"]
    result = overnight.build_context(points, factors, now=ready_now())
    assert result["reason"] == "missing_us_sessions"
    assert result["quotes"] == [] and result["scenario_forecast"] == []
    waiting = overnight.build_context(
        points, factors, now=datetime.fromisoformat("2026-10-30T04:14:59+08:00")
    )
    assert waiting["status"] == "waiting" and waiting["quotes"] == []


@pytest.mark.parametrize("horizon", [1, 5, 10, 30])
def test_directional_adr_path_matches_horizon_without_replacing_the_arx_diagnostic(horizon):
    points, factors = fixture_data()
    result = overnight.build_context(points, factors, now=ready_now(), horizon=horizon)
    path = result["scenario_forecast"]
    assert len(path) == horizon
    assert path[0]["date"] == result["forecast"]["date"]
    assert all(set(item) == {"date", "close", "adr_adjustment_pct"} for item in path)
    quote = next(item for item in result["quotes"] if item["symbol"] == "UMC")
    adjustment = np.clip(quote["day_change_pct"] * 0.5, -5, 5)
    baseline = analyze(points, horizon)["forecast"]
    for index, (item, original) in enumerate(zip(path, baseline)):
        assert item["date"] == original["date"]
        assert item["close"] == pytest.approx(
            original["close"] * (1 + adjustment * 0.8**index / 100)
        )
    base = overnight.build_context(points, factors, now=ready_now(), horizon=5)
    assert result["backtest"] == base["backtest"]
    assert result["quotes"] == base["quotes"]
    assert result["forecast"] == base["forecast"]


@pytest.mark.parametrize("horizon", [0, 31, True, 1.5])
def test_context_rejects_invalid_scenario_horizon(horizon):
    points, factors = fixture_data()
    with pytest.raises(ValueError):
        overnight.build_context(points, factors, now=ready_now(), horizon=horizon)
