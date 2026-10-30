"""Fixed-symbol quote download caching, coalescing, and failure boundaries."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest

import stockpredict.market_data as market_data
from stockpredict.data import DataSourceError


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    market_data.clear_cache()
    clock = {"now": 1000.0, "day": date(2026, 10, 30)}
    monkeypatch.setattr(market_data, "_clock", lambda: clock["now"])
    monkeypatch.setattr(market_data, "_today", lambda: clock["day"])
    yield clock
    market_data.clear_cache()


def mock_prices(monkeypatch, **metadata):
    calls = []

    def prices(symbol):
        calls.append(symbol)
        return [{"date": "2026-10-29", "close": 100.0}], {
            "currency": "USD",
            "exchange_timezone": "America/New_York",
            **metadata,
        }

    monkeypatch.setattr(market_data, "yahoo_data", prices)
    return calls


def test_only_fixed_symbols_fetched_and_cache_detached(monkeypatch, isolated_cache):
    calls = mock_prices(monkeypatch)
    first = market_data.overnight_factors()
    assert set(calls) == {"UMC", "SOXX"} and len(calls) == 2
    first["UMC"][0]["close"] = -1
    isolated_cache["now"] += 299
    assert market_data.overnight_factors()["UMC"][0]["close"] == 100
    assert len(calls) == 2
    isolated_cache["now"] += 1
    market_data.overnight_factors()
    assert len(calls) == 4


def test_us_date_rollover_invalidates_cache(monkeypatch, isolated_cache):
    calls = mock_prices(monkeypatch)
    market_data.overnight_factors()
    isolated_cache["day"] = date(2026, 10, 31)
    market_data.overnight_factors()
    assert len(calls) == 4


@pytest.mark.parametrize("metadata", [{"currency": "TWD"}, {"exchange_timezone": "Asia/Taipei"}])
def test_incorrect_currency_or_timezone_rejected(monkeypatch, metadata):
    mock_prices(monkeypatch, **metadata)
    with pytest.raises(DataSourceError):
        market_data.overnight_factors()


def test_failure_cooldown_and_expired_cache_never_returned(monkeypatch, isolated_cache):
    mock_prices(monkeypatch)
    market_data.overnight_factors()
    isolated_cache["now"] += 300
    calls = []

    def unavailable(symbol):
        calls.append(symbol)
        raise DataSourceError("Yahoo rate limited")

    monkeypatch.setattr(market_data, "yahoo_data", unavailable)
    with pytest.raises(DataSourceError):
        market_data.overnight_factors()
    count = len(calls)
    isolated_cache["now"] += 59
    with pytest.raises(DataSourceError):
        market_data.overnight_factors()
    assert len(calls) == count
    isolated_cache["now"] += 1
    mock_prices(monkeypatch)
    assert market_data.overnight_factors()["UMC"][0]["close"] == 100


def test_concurrent_callers_share_two_downloads(monkeypatch):
    calls = mock_prices(monkeypatch)
    start = Barrier(4)

    def download():
        start.wait(timeout=5)
        return market_data.overnight_factors()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [f.result(timeout=10) for f in [pool.submit(download) for _ in range(4)]]
    assert len(calls) == 2
    assert all(result == results[0] for result in results)
