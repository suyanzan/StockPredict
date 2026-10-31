"""Published CSV factors are explicit, date-matched, and never a silent fallback."""

from copy import deepcopy
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from test_overnight import fixture_data, ready_now

import stockpredict.main as main
import stockpredict.overnight as overnight
from stockpredict.data import DataSourceError

PROFILE_CASES = [
    ("2303", "twse", "2303.TW", "umc", ("UMC", "SOXX")),
    ("2330", "twse", "2330.TW", "tsmc", ("TSM", "SOXX")),
    ("0050", "twse", "0050.TW", "taiwan_market", ("SPY", "QQQ")),
    ("6488.TWO", "yahoo", "6488.TWO", "taiwan_market", ("SPY", "QQQ")),
]
SNAPSHOT = {
    "snapshot_session_date": "2026-10-29",
    "generated_at": "2026-10-29T20:20:00+00:00",
    "provider": "Yahoo Finance",
}


@pytest.fixture
def client():
    with TestClient(main.app) as instance:
        yield instance


@pytest.fixture
def snapshot_history(monkeypatch):
    points, seeds = fixture_data()
    calls = {"target": [], "auto": [], "yahoo": []}
    builder = main.build_context

    def target_prices(symbol, source):
        calls["target"].append((source, symbol))
        return deepcopy(points), {
            "name": symbol,
            "currency": "TWD",
            "source": source,
            "source_label": "Test Taiwan history",
        }

    def factors(symbols):
        return {
            symbol: [
                deepcopy(row)
                for row in seeds[seed]
                if row["date"] <= SNAPSHOT["snapshot_session_date"]
            ]
            for symbol, seed in zip(symbols, ("UMC", "SOXX"))
        }

    def auto(symbols, required):
        calls["auto"].append((tuple(symbols), required))
        return factors(symbols), deepcopy(SNAPSHOT)

    def yahoo(symbols=("UMC", "SOXX")):
        calls["yahoo"].append(tuple(symbols))
        return factors(symbols)

    monkeypatch.setattr(main, "twse_data", lambda symbol: target_prices(symbol, "twse"))
    monkeypatch.setattr(main, "yahoo_data", lambda symbol: target_prices(symbol, "yahoo"))
    monkeypatch.setattr(main, "auto_csv_factors", auto)
    monkeypatch.setattr(main, "overnight_factors", yahoo)
    monkeypatch.setattr(
        main, "pending_context", lambda p: overnight.pending_context(p, now=ready_now())
    )
    monkeypatch.setattr(
        main, "reference_timing", lambda p: overnight.reference_timing(p, now=ready_now())
    )
    monkeypatch.setattr(
        main, "build_context", lambda p, f, **kwargs: builder(p, f, now=ready_now(), **kwargs)
    )
    return {"points": points, "seeds": seeds, "calls": calls}


@pytest.mark.parametrize(("symbol", "source", "canonical", "profile_id", "pair"), PROFILE_CASES)
def test_auto_csv_profile_uses_required_session_and_real_model_without_changing_base(
    client, snapshot_history, symbol, source, canonical, profile_id, pair
):
    params = {"symbol": canonical, "source": source, "horizon": 10}
    base = client.get("/api/analysis", params=params).json()
    response = client.get(
        "/api/analysis",
        params={
            **params,
            "symbol": symbol,
            "market_context": "us_overnight",
            "factor_source": "auto_csv",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["symbol"] == canonical
    context = result["market_context"]
    assert context["status"] == "ready" and context["data_source"] == "auto_csv"
    assert context["snapshot_metadata"] == SNAPSHOT
    assert context["reference_profile"]["id"] == profile_id
    assert tuple(item["symbol"] for item in context["factors"]) == pair
    assert all(item["last_session"] == "2026-10-29" for item in context["factors"])
    assert context["forecast"]["date"] == result["forecast"][0]["date"] == "2026-10-30"
    assert snapshot_history["calls"]["auto"] == [(pair, "2026-10-29")]
    assert snapshot_history["calls"]["yahoo"] == []
    for key in ("history", "forecast", "summary", "backtest", "as_of"):
        assert result[key] == base[key]


@pytest.mark.parametrize(("symbol", "source", "canonical", "profile_id", "pair"), PROFILE_CASES)
def test_default_factor_source_preserves_yahoo_compatibility(
    client, snapshot_history, monkeypatch, symbol, source, canonical, profile_id, pair
):
    monkeypatch.setattr(
        main, "auto_csv_factors", lambda *args: pytest.fail("Auto source not selected")
    )
    response = client.get(
        "/api/analysis",
        params={"symbol": symbol, "source": source, "market_context": "us_overnight"},
    )
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert context["status"] == "ready" and context["data_source"] == "yahoo"
    assert "snapshot_metadata" not in context
    assert snapshot_history["calls"]["yahoo"] == [pair]


def test_auto_source_without_reference_option_never_reads_any_factor_data(
    client, snapshot_history, monkeypatch
):
    monkeypatch.setattr(main, "auto_csv_factors", lambda *args: pytest.fail("No overlay requested"))
    monkeypatch.setattr(
        main, "overnight_factors", lambda *args: pytest.fail("No overlay requested")
    )
    monkeypatch.setattr(main, "reference_timing", lambda *args: pytest.fail("No overlay timing"))
    response = client.get("/api/analysis?symbol=2303&source=twse&factor_source=auto_csv")
    assert response.status_code == 200
    assert "market_context" not in response.json()


@pytest.mark.parametrize(("symbol", "source", "canonical", "profile_id", "pair"), PROFILE_CASES)
def test_preclose_preflight_prevents_snapshot_or_yahoo_reads_for_every_profile(
    client, snapshot_history, monkeypatch, symbol, source, canonical, profile_id, pair
):
    before_close = datetime.fromisoformat("2026-10-30T04:14:59+08:00")
    monkeypatch.setattr(
        main, "pending_context", lambda p: overnight.pending_context(p, now=before_close)
    )
    monkeypatch.setattr(
        main, "auto_csv_factors", lambda *args: pytest.fail("No snapshot reads yet")
    )
    monkeypatch.setattr(
        main, "reference_timing", lambda *args: pytest.fail("No manifest timing read")
    )
    monkeypatch.setattr(
        main, "build_context", lambda *args, **kwargs: pytest.fail("Too early to fit")
    )

    def yahoo_rate_limit(*args):
        raise DataSourceError("Private upstream details", code="us_rate_limited", http_status=429)

    monkeypatch.setattr(main, "overnight_factors", yahoo_rate_limit)
    response = client.get(
        "/api/analysis",
        params={
            "symbol": symbol,
            "source": source,
            "market_context": "us_overnight",
            "factor_source": "auto_csv",
        },
    )
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert context["status"] == "waiting" and context["reason"] == "us_session_not_closed"
    assert context["data_source"] == "auto_csv"
    assert context["reference_profile"]["id"] == profile_id
    assert tuple(context["reference_profile"]["symbols"]) == pair
    assert context["forecast"] is context["backtest"] is None
    assert context["factors"] == [] and "snapshot_metadata" not in context
    assert context.get("http_status") is None and "Private upstream" not in response.text


@pytest.mark.parametrize(
    "code", ["auto_csv_unavailable", "auto_csv_missing_session", "auto_csv_invalid_data"]
)
def test_failed_or_stale_snapshot_keeps_base_and_never_falls_back_to_yahoo(
    client, snapshot_history, monkeypatch, code
):
    base = client.get("/api/analysis?symbol=2330&source=twse").json()
    calls = []

    def failed(symbols, required):
        calls.append((tuple(symbols), required))
        raise DataSourceError(
            "PRIVATE_CSV_ERROR https://private.invalid/secret",
            code=code,
            http_status=404,
            retry_after=60,
        )

    monkeypatch.setattr(main, "auto_csv_factors", failed)
    monkeypatch.setattr(main, "overnight_factors", lambda *args: pytest.fail("No Yahoo fallback"))
    monkeypatch.setattr(
        main, "build_context", lambda *args, **kwargs: pytest.fail("No stale model")
    )
    response = client.get(
        "/api/analysis",
        params={
            "symbol": "2330",
            "source": "twse",
            "market_context": "us_overnight",
            "factor_source": "auto_csv",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    context = result["market_context"]
    assert context["status"] == "unavailable" and context["reason"] == code
    assert context["data_source"] == "auto_csv"
    assert context["retry_after_seconds"] == 60 and context["http_status"] == 404
    assert context["required_us_session_date"] == "2026-10-29"
    assert context["available_after"] == "2026-10-29T20:15:00+00:00"
    assert context["reference_profile"]["symbols"] == ["TSM", "SOXX"]
    assert context["forecast"] is None and context["factors"] == []
    assert "snapshot_metadata" not in context
    assert "PRIVATE_CSV_ERROR" not in response.text and "private.invalid" not in response.text
    assert calls == [(("TSM", "SOXX"), "2026-10-29")]
    for key in ("forecast", "history", "summary", "backtest"):
        assert result[key] == base[key]


def test_manual_csv_route_still_never_uses_either_automatic_source(
    client, snapshot_history, monkeypatch
):
    def as_csv(rows):
        return "Date,Close\n" + "\n".join(f"{row['date']},{row['close']}" for row in rows)

    monkeypatch.setattr(
        main, "auto_csv_factors", lambda *args: pytest.fail("Manual files supplied")
    )
    monkeypatch.setattr(
        main, "overnight_factors", lambda *args: pytest.fail("Manual files supplied")
    )
    monkeypatch.setattr(main, "reference_timing", lambda *args: pytest.fail("No snapshot lookup"))
    response = client.post(
        "/api/analysis/overnight/csv",
        json={
            "symbol": "2330",
            "factor_csvs": {
                "TSM": as_csv(snapshot_history["seeds"]["UMC"]),
                "SOXX": as_csv(snapshot_history["seeds"]["SOXX"]),
            },
        },
    )
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert context["status"] == "ready" and context["data_source"] == "csv"
    assert "snapshot_metadata" not in context


def test_invalid_factor_source_is_schema_rejected_before_network(client, snapshot_history):
    response = client.get(
        "/api/analysis",
        params={
            "symbol": "2303",
            "source": "twse",
            "market_context": "us_overnight",
            "factor_source": "other",
        },
    )
    assert response.status_code == 422
    assert snapshot_history["calls"]["target"] == []
    assert snapshot_history["calls"]["auto"] == snapshot_history["calls"]["yahoo"] == []
