"""Opt-in US data never silently replaces or prevents the base stock analysis."""

from copy import deepcopy
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from test_overnight import fixture_data, ready_now

import stockpredict.main as main
import stockpredict.overnight as overnight
from stockpredict.data import DataSourceError, demo_data
from stockpredict.reference_profiles import profile_for, profile_payload


@pytest.fixture
def client():
    with TestClient(main.app) as instance:
        yield instance


@pytest.fixture
def real_history(monkeypatch):
    points, _ = demo_data("2330.TW")
    metadata = {"name": "聯電", "currency": "TWD", "source": "twse", "source_label": "證交所"}
    monkeypatch.setattr(main, "twse_data", lambda _: (points, metadata))
    # These tests isolate provider/result wiring; timing is exercised separately.
    monkeypatch.setattr(main, "pending_context", lambda _: None)
    return points


def test_default_real_analysis_does_not_download_optional_us_data(
    client, real_history, monkeypatch
):
    monkeypatch.setattr(
        main, "overnight_factors", lambda: pytest.fail("Optional US data requested")
    )
    response = client.get("/api/analysis", params={"symbol": "2303", "source": "twse"})
    assert response.status_code == 200
    assert "market_context" not in response.json()


def test_factor_result_is_separate_from_base_forecasts(client, real_history, monkeypatch):
    context = {
        "status": "ready",
        "reason": None,
        "target_date": "2026-11-02",
        "decision_cutoff": "2026-11-02T01:00:00+00:00",
        "assumed_availability": True,
        "forecast": {"date": "2026-11-02", "close": 120.0, "base_close": 110.0, "change_pct": 1.0},
        "factors": [],
        "backtest": None,
        "correlations_window": None,
    }
    downloaded = {"UMC": [{"date": "2026-10-30", "close": 20.0}]}
    calls = []
    monkeypatch.setattr(main, "overnight_factors", lambda: downloaded)

    def build(points, factors, **kwargs):
        calls.append((deepcopy(points), deepcopy(factors)))
        assert kwargs == {"horizon": 10}
        return deepcopy(context)

    monkeypatch.setattr(main, "build_context", build)
    params = {"symbol": "2303", "source": "twse", "horizon": 10}
    base = client.get("/api/analysis", params=params).json()
    response = client.get(
        "/api/analysis", params={**params, "market_context": "us_overnight", "lang": "en"}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["market_context"] == {
        **context,
        "data_source": "yahoo",
        "reference_profile": profile_payload(profile_for("2303.TW")),
    }
    for key in ("forecast", "backtest", "history", "summary", "as_of"):
        assert result[key] == base[key]
    assert result["model"]["name"] == "Ridge AR(5)"
    assert calls == [(real_history, downloaded)]


@pytest.mark.parametrize("source", ["twse", "yahoo"])
def test_bare_umc_symbol_is_canonicalized_when_reference_requested(
    client, monkeypatch, real_history, source
):
    calls = []

    def prices(symbol):
        calls.append(symbol)
        return real_history, {
            "name": "聯電",
            "currency": "TWD",
            "source": source,
            "source_label": "Real daily data",
        }

    monkeypatch.setattr(main, source + "_data", prices)
    monkeypatch.setattr(main, "overnight_factors", lambda: {})
    monkeypatch.setattr(main, "build_context", lambda *args: {"status": "waiting"})
    response = client.get(
        "/api/analysis",
        params={"source": source, "symbol": "2303", "market_context": "us_overnight"},
    )
    assert response.status_code == 200
    assert calls == ["2303.TW"] and response.json()["symbol"] == "2303.TW"


@pytest.mark.parametrize(
    ("source", "symbol"),
    [("demo", "2303.TW"), ("demo", "2330.TW"), ("yahoo", "AAPL"), ("yahoo", "MSFT")],
)
def test_context_rejects_unsupported_security_before_network(client, monkeypatch, source, symbol):
    monkeypatch.setattr(main, "overnight_factors", lambda: pytest.fail("Unexpected download"))
    monkeypatch.setattr(main, source + "_data", lambda _: pytest.fail("Unexpected stock download"))
    response = client.get(
        "/api/analysis",
        params={"source": source, "symbol": symbol, "market_context": "us_overnight", "lang": "en"},
    )
    assert response.status_code == 400
    assert "Taiwan" in response.json()["detail"]


def test_us_download_failure_keeps_base_analysis_and_reports_unavailable(
    client, monkeypatch, real_history
):
    def unavailable():
        raise DataSourceError("Yahoo HTTP 429")

    monkeypatch.setattr(main, "overnight_factors", unavailable)
    monkeypatch.setattr(main, "build_context", lambda *args: pytest.fail("No factors to fit"))
    params = {"source": "twse", "symbol": "2303"}
    base = client.get("/api/analysis", params=params).json()
    response = client.get("/api/analysis", params={**params, "market_context": "us_overnight"})
    assert response.status_code == 200
    result = response.json()
    assert result["market_context"]["status"] == "unavailable"
    assert result["market_context"]["reason"] == "data_unavailable"
    assert result["market_context"]["forecast"] is None
    assert result["forecast"] == base["forecast"]
    assert result["backtest"] == base["backtest"]


def test_unknown_context_is_rejected_by_schema(client):
    assert client.get("/api/analysis?market_context=pretend").status_code == 422


def test_api_wires_real_alignment_and_model_with_known_input_series(client, monkeypatch):
    points, factors = fixture_data()
    actual_builder = main.build_context
    metadata = {"name": "聯電", "currency": "TWD", "source": "twse", "source_label": "Test fixture"}
    monkeypatch.setattr(main, "twse_data", lambda _: (points, metadata))
    monkeypatch.setattr(main, "overnight_factors", lambda: factors)
    monkeypatch.setattr(
        main, "pending_context", lambda p: overnight.pending_context(p, now=ready_now())
    )
    monkeypatch.setattr(main, "build_context", lambda p, f: actual_builder(p, f, now=ready_now()))
    response = client.get(
        "/api/analysis",
        params={"source": "twse", "symbol": "2303", "market_context": "us_overnight", "lang": "en"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    context = result["market_context"]
    assert context["status"] == "ready"
    assert context["forecast"]["date"] == result["forecast"][0]["date"] == "2026-10-30"
    assert context["forecast"]["base_close"] == result["summary"]["last_close"]
    assert context["backtest"]["observations"] == len(context["backtest"]["dates"])
    assert all(f["last_session"] == "2026-10-29" for f in context["factors"])


def test_unclosed_us_session_skips_download_and_does_not_return_old_factor_data(
    client, monkeypatch
):
    points, _ = fixture_data()
    before_close = datetime.fromisoformat("2026-10-30T04:14:59+08:00")
    metadata = {"name": "聯電", "currency": "TWD", "source": "twse", "source_label": "Test"}
    monkeypatch.setattr(main, "twse_data", lambda _: (points, metadata))
    monkeypatch.setattr(
        main, "pending_context", lambda p: overnight.pending_context(p, now=before_close)
    )
    monkeypatch.setattr(main, "overnight_factors", lambda: pytest.fail("US session still open"))
    monkeypatch.setattr(main, "build_context", lambda *args: pytest.fail("Old factor data used"))
    params = {"symbol": "2303", "source": "twse"}
    base = client.get("/api/analysis", params=params).json()
    response = client.get("/api/analysis", params={**params, "market_context": "us_overnight"})
    assert response.status_code == 200
    result = response.json()
    context = result["market_context"]
    assert context["status"] == "waiting" and context["reason"] == "us_session_not_closed"
    assert context["required_us_session_date"] == "2026-10-29"
    assert context["data_source"] == "yahoo"
    assert context["reference_profile"]["symbols"] == ["UMC", "SOXX"]
    assert context["factors"] == []
    assert context["forecast"] is context["backtest"] is context["correlations_window"] is None
    assert result["forecast"] == base["forecast"] and result["backtest"] == base["backtest"]
