from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from stockpredict import quotes
from stockpredict.data import DataSourceError
from stockpredict.main import app

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)


def source(monkeypatch, points):
    monkeypatch.setattr(quotes, "twse_data", lambda symbol: (points, {"name": "鴻海"}))


def test_quote_uses_exact_previous_session_and_filters_unpublished_prices(monkeypatch):
    source(
        monkeypatch,
        [
            {"date": "2026-11-12", "close": 200.0},
            {"date": "2026-11-13", "close": 204.0},
            {"date": "2026-11-14", "close": 999.0},
            {"date": "2026-11-16", "close": 1000.0},
        ],
    )
    result = quotes.taiwan_quote("2317.TW", NOW)
    assert result["close"] == 204
    assert result["day_change"] == 4
    assert result["day_change_pct"] == 2
    assert result["session_date"] == "2026-11-13"
    assert result["fresh"] is True
    assert "forecast" not in result


def test_quote_does_not_use_multiday_change_or_hide_stale_date(monkeypatch):
    source(
        monkeypatch,
        [{"date": "2026-11-10", "close": 190}, {"date": "2026-11-12", "close": 200}],
    )
    result = quotes.taiwan_quote("2317.TW", NOW)
    assert result["fresh"] is False
    assert result["session_date"] == "2026-11-12"
    assert result["expected_session_date"] == "2026-11-13"
    assert result["day_change"] is None
    assert result["previous_close"] is None


@pytest.mark.parametrize("symbol", ["AAPL", "6488.TWO", "https://example.com", "<script>"])
def test_invalid_symbols_never_call_provider(monkeypatch, symbol):
    def unexpected(symbol):
        pytest.fail("Invalid symbol must not reach provider")

    monkeypatch.setattr(quotes, "twse_data", unexpected)
    with TestClient(app) as client:
        response = client.get("/api/quotes/taiwan", params={"symbol": symbol})
    assert response.status_code == 422


def test_quote_endpoint_normalizes_alias_and_does_not_cache(monkeypatch):
    seen = []

    def result(symbol):
        seen.append(symbol)
        return {"symbol": symbol, "status": "ready"}

    monkeypatch.setattr(quotes, "taiwan_quote", result)
    with TestClient(app) as client:
        response = client.get("/api/quotes/taiwan?symbol=0050")
    assert seen == ["0050.TW"]
    assert response.json()["symbol"] == "0050.TW"
    assert response.headers["cache-control"] == "no-store"


def test_provider_failure_exposes_no_internal_error(monkeypatch):
    def unavailable(symbol):
        raise DataSourceError("sensitive upstream exception")

    monkeypatch.setattr(quotes, "twse_data", unavailable)
    with TestClient(app) as client:
        response = client.get("/api/quotes/taiwan?symbol=2317")
    assert response.status_code == 503
    assert response.json() == {"reason": "quote_unavailable"}


def test_no_publishable_closes_is_unavailable(monkeypatch):
    source(monkeypatch, [{"date": "2026-11-16", "close": 200}])
    with pytest.raises(DataSourceError):
        quotes.taiwan_quote("2317.TW", NOW)
