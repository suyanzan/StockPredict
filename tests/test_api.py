"""Exercise actual routes and dependencies without requiring an external quote API."""

import pytest
from fastapi.testclient import TestClient
from test_data import csv_text

import stockpredict.main as main
from stockpredict.data import DataSourceError
from stockpredict.main import app


@pytest.fixture
def client():
    with TestClient(app) as instance:
        yield instance


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize("symbol", ["2330.TW", "0050.TW", "AAPL", "MSFT"])
def test_demo_analysis_for_taiwan_and_us_stocks_is_repeatable(client, symbol):
    params = {"symbol": symbol, "source": "demo", "horizon": 10}
    response = client.get("/api/analysis", params=params)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result == client.get("/api/analysis", params=params).json()
    assert result["symbol"] == symbol
    assert result["source"] == "demo"
    assert result["currency"] == ("TWD" if symbol.endswith(".TW") else "USD")
    assert result["source_label"]
    assert len(result["history"]) >= 60
    assert len(result["forecast"]) == 10
    assert result["backtest"]["observations"] > 0
    assert result["warnings"]  # Synthetic data and model limitations stay visible.


@pytest.mark.parametrize(
    "params",
    [
        {"horizon": 0},
        {"horizon": 31},
        {"horizon": "not-a-number"},
        {"source": "unknown"},
    ],
)
def test_query_validation(client, params):
    response = client.get("/api/analysis", params=params)
    assert response.status_code == 422


def test_csv_analysis_uses_imported_prices(client):
    response = client.post(
        "/api/analysis/csv",
        json={"symbol": "CUSTOM", "horizon": 5, "csv": csv_text()},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source"] == "csv"
    assert result["symbol"] == "CUSTOM"
    assert len(result["history"]) == 60
    assert len(result["forecast"]) == 5
    assert result["summary"]["last_close"] == pytest.approx(105.9)


def test_csv_errors_are_reported_to_user(client):
    response = client.post(
        "/api/analysis/csv",
        json={"symbol": "CUSTOM", "horizon": 5, "csv": csv_text(count=59)},
    )
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]


def test_csv_horizon_is_validated(client):
    response = client.post(
        "/api/analysis/csv",
        json={"symbol": "CUSTOM", "horizon": 50, "csv": csv_text()},
    )
    assert response.status_code == 422


def test_yahoo_failure_is_reported_without_falling_back_to_demo(client, monkeypatch):
    def unavailable(symbol):
        raise DataSourceError("Yahoo temporarily unavailable")

    def forbidden_fallback(symbol):
        pytest.fail("A failed real quote request must not become synthetic data")

    monkeypatch.setattr(main, "yahoo_data", unavailable)
    monkeypatch.setattr(main, "demo_data", forbidden_fallback)
    response = client.get("/api/analysis", params={"symbol": "AAPL", "source": "yahoo"})
    assert response.status_code == 502
    assert "Yahoo" in response.json()["detail"]


def test_homepage_and_static_assets_are_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "StockPredict" in response.text
    for name in ("app.js", "styles.css"):
        asset = client.get(f"/static/{name}")
        assert asset.status_code == 200
        assert len(asset.content) > 100


@pytest.mark.parametrize("symbol", ["台達電", "台达电", "Delta Electronics", "2308", "2308.TW"])
@pytest.mark.parametrize("source", ["twse", "yahoo"])
def test_delta_identity_reaches_provider_without_substitution(client, monkeypatch, symbol, source):
    from stockpredict.data import parse_csv

    calls = []

    def prices(code):
        calls.append(code)
        return parse_csv(csv_text()), {
            "name": "台達電",
            "currency": "TWD",
            "source": source,
            "source_label": source,
        }

    monkeypatch.setattr(main, source + "_data", prices)
    response = client.get("/api/analysis", params={"symbol": symbol, "source": source})
    assert response.status_code == 200, response.text
    result = response.json()
    assert calls == ["2308.TW"]
    assert result["symbol"] == "2308.TW"
    assert result["name"] == "台達電"
    assert result["locales"]["en"]["name"] == "Delta Electronics"
    assert result["summary"]["last_close"] == pytest.approx(105.9)


def test_delta_has_no_synthetic_demo(client):
    response = client.get("/api/analysis", params={"symbol": "台達電", "source": "demo"})
    assert response.status_code == 400
    assert "示範" in response.json()["detail"]
