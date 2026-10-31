"""Different Taiwan stocks must never inherit UMC's factors or cache entries."""

from copy import deepcopy
from datetime import date, datetime

import pytest
from test_overnight import fixture_data, ready_now

import stockpredict.market_data as market_data
from stockpredict.data import DataSourceError
from stockpredict.overnight import build_context
from stockpredict.reference_profiles import FACTOR_PAIRS


@pytest.mark.parametrize("pair", sorted(FACTOR_PAIRS))
def test_profile_uses_its_own_symbols_and_same_chronological_model(pair):
    points, original = fixture_data()
    expected = build_context(points, original, now=ready_now())
    renamed = {pair[0]: deepcopy(original["UMC"]), pair[1]: deepcopy(original["SOXX"])}
    result = build_context(points, renamed, now=ready_now(), factor_symbols=pair)
    assert result["status"] == "ready"
    assert [item["symbol"] for item in result["factors"]] == list(pair)
    assert result["forecast"] == expected["forecast"]
    assert result["backtest"] == expected["backtest"]
    assert all(item["last_session"] == "2026-10-29" for item in result["factors"])


def test_tsm_profile_does_not_substitute_umc_when_tsm_is_missing():
    points, factors = fixture_data()
    result = build_context(points, factors, now=ready_now(), factor_symbols=("TSM", "SOXX"))
    assert result["status"] == "unavailable" and result["reason"] == "missing_factors"
    assert result["forecast"] is None and result["factors"] == []


@pytest.mark.parametrize("pair", [("TSM", "SOXX"), ("SPY", "QQQ")])
def test_other_profiles_wait_without_reading_or_reusing_prior_day(pair):
    points, _ = fixture_data()

    class Unreadable(dict):
        def __getitem__(self, key):
            pytest.fail("US data inspected before the required close")

    result = build_context(
        points,
        Unreadable(),
        now=datetime.fromisoformat("2026-10-30T04:14:59+08:00"),
        factor_symbols=pair,
    )
    assert result["status"] == "waiting"
    assert result["factors"] == [] and result["backtest"] is None


@pytest.fixture
def cache(monkeypatch):
    market_data.clear_cache()
    clock = {"now": 1000.0}
    monkeypatch.setattr(market_data, "_clock", lambda: clock["now"])
    monkeypatch.setattr(market_data, "_today", lambda: date(2026, 10, 30))
    calls = []

    def prices(symbol):
        calls.append(symbol)
        return [
            {
                "date": "2026-10-29",
                "close": {"UMC": 11, "SOXX": 22, "TSM": 33, "SPY": 44, "QQQ": 55}[symbol],
            }
        ], {"currency": "USD", "exchange_timezone": "America/New_York"}

    monkeypatch.setattr(market_data, "yahoo_data", prices)
    yield calls, clock, prices
    market_data.clear_cache()


def test_pair_caches_are_isolated_and_return_copies(cache):
    calls, _, _ = cache
    umc = market_data.overnight_factors()
    tsm = market_data.overnight_factors(("TSM", "SOXX"))
    assert set(umc) == {"UMC", "SOXX"}
    assert set(tsm) == {"TSM", "SOXX"} and tsm["TSM"][0]["close"] == 33
    assert len(calls) == 4
    tsm["TSM"][0]["close"] = -1
    assert market_data.overnight_factors(("TSM", "SOXX"))["TSM"][0]["close"] == 33
    assert market_data.overnight_factors() == umc and len(calls) == 4


def test_rate_limit_cannot_be_bypassed_by_switching_reference_profile(cache, monkeypatch):
    calls, _, prices = cache
    cached_tsm = market_data.overnight_factors(("TSM", "SOXX"))

    def limited(symbol):
        calls.append(symbol)
        raise DataSourceError("Limited", code="us_rate_limited", http_status=429, retry_after=300)

    monkeypatch.setattr(market_data, "yahoo_data", limited)
    with pytest.raises(DataSourceError):
        market_data.overnight_factors()
    count = len(calls)
    monkeypatch.setattr(market_data, "yahoo_data", prices)
    with pytest.raises(DataSourceError) as caught:
        market_data.overnight_factors(("SPY", "QQQ"))
    assert caught.value.code == "us_rate_limited" and caught.value.retry_after == 300
    assert len(calls) == count
    assert market_data.overnight_factors(("TSM", "SOXX")) == cached_tsm
    assert len(calls) == count  # A still-valid cache needs no upstream request.


def test_non_rate_failure_is_limited_to_its_profile(cache, monkeypatch):
    calls, _, prices = cache

    def unavailable(symbol):
        calls.append(symbol)
        raise DataSourceError("Unavailable", code="us_connection_failed")

    monkeypatch.setattr(market_data, "yahoo_data", unavailable)
    with pytest.raises(DataSourceError):
        market_data.overnight_factors()
    monkeypatch.setattr(market_data, "yahoo_data", prices)
    result = market_data.overnight_factors(("TSM", "SOXX"))
    assert set(result) == {"TSM", "SOXX"} and len(calls) == 4


def test_pair_cache_eviction_is_bounded(cache, monkeypatch):
    calls, _, _ = cache
    monkeypatch.setattr(market_data, "MAX_CACHE_SIZE", 1)
    market_data.overnight_factors()
    market_data.overnight_factors(("TSM", "SOXX"))
    assert len(market_data._CACHE) == 1
    market_data.overnight_factors()
    assert len(calls) == 6


@pytest.mark.parametrize("pair", [("TSM", "UMC"), ("QQQ", "SPY"), ("EVIL", "SOXX")])
def test_unconfigured_pairs_are_rejected_before_network(cache, pair):
    calls, _, _ = cache
    with pytest.raises(ValueError):
        market_data.overnight_factors(pair)
    assert not calls
