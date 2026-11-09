"""Taiwan symbols select explicit reference profiles without mixing US factors."""

import re
from copy import deepcopy
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from test_overnight import fixture_data, ready_now

import stockpredict.main as main
import stockpredict.overnight as overnight
from stockpredict.reference_profiles import (
    canonical_reference_symbol,
    profile_for,
    profile_payload,
    public_catalog,
)

pytestmark = pytest.mark.usefixtures("published_history_clock")

ENDPOINT = "/api/analysis/overnight/csv"
PROFILE_CASES = [
    ("台達電", "twse", "2308.TW", "taiwan_market", ("SPY", "QQQ")),
    ("2308", "yahoo", "2308.TW", "taiwan_market", ("SPY", "QQQ")),
    ("2330", "twse", "2330.TW", "tsmc", ("TSM", "SOXX")),
    ("0050", "twse", "0050.TW", "taiwan_market", ("SPY", "QQQ")),
    ("6488.TWO", "yahoo", "6488.TWO", "taiwan_market", ("SPY", "QQQ")),
    ("00679B.TW", "yahoo", "00679B.TW", "taiwan_market", ("SPY", "QQQ")),
]


def as_csv(points):
    return "Date,Close\n" + "\n".join(f"{point['date']},{point['close']}" for point in points)


@pytest.fixture
def client():
    with TestClient(main.app) as instance:
        yield instance


@pytest.fixture
def profile_history(monkeypatch):
    points, original = fixture_data()
    builder = main.build_context
    calls = {"targets": [], "factors": []}

    def target_prices(symbol, source):
        calls["targets"].append((source, symbol))
        return deepcopy(points), {
            "name": symbol,
            "currency": "TWD",
            "source": source,
            "source_label": "Test Taiwan history",
        }

    def factors(symbols=("UMC", "SOXX")):
        calls["factors"].append(tuple(symbols))
        return {symbol: deepcopy(original[seed]) for symbol, seed in zip(symbols, ("UMC", "SOXX"))}

    monkeypatch.setattr(main, "twse_data", lambda symbol: target_prices(symbol, "twse"))
    monkeypatch.setattr(main, "yahoo_data", lambda symbol: target_prices(symbol, "yahoo"))
    monkeypatch.setattr(main, "overnight_factors", factors)
    monkeypatch.setattr(
        main,
        "pending_context",
        lambda p: overnight.pending_context(p, now=ready_now()),
    )
    monkeypatch.setattr(
        main,
        "build_context",
        lambda p, f, **kwargs: builder(p, f, now=ready_now(), **kwargs),
    )
    return {"points": points, "original": original, "calls": calls}


def test_public_profile_catalog_is_shared_with_reference_selection(client):
    response = client.get("/api/reference-profiles")
    assert response.status_code == 200
    catalog = response.json()
    assert catalog == public_catalog()
    assert catalog["stock_profiles"] == {"2303.TW": "umc", "2330.TW": "tsmc"}
    assert catalog["default_taiwan_profile"] == "taiwan_market"
    expected = {"umc": ["UMC", "SOXX"], "tsmc": ["TSM", "SOXX"], "taiwan_market": ["SPY", "QQQ"]}
    for key, symbols in expected.items():
        item = catalog["profiles"][key]
        assert item["symbols"] == symbols
        assert set(item["names"]) == {"zh-TW", "en"}
        assert len(item["names"]["en"]) == len(item["names"]["zh-TW"]) == 2
        assert all(not re.search(r"[\u3400-\u9fff]", text) for text in item["names"]["en"])
    assert "TSM" in catalog["profiles"]["tsmc"]["names"]["en"][0]


@pytest.mark.parametrize(
    ("symbol", "canonical", "profile_id"),
    [
        (" 2330 ", "2330.TW", "tsmc"),
        ("2303.tw", "2303.TW", "umc"),
        ("0050", "0050.TW", "taiwan_market"),
        ("6488.two", "6488.TWO", "taiwan_market"),
        ("00679b", "00679B.TW", "taiwan_market"),
    ],
)
def test_reference_symbol_canonicalization_preserves_taiwan_markets(symbol, canonical, profile_id):
    assert canonical_reference_symbol(symbol) == canonical
    assert profile_for(symbol).id == profile_id


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT", "SPY", "2330.HK", "^GSPC"])
def test_non_taiwan_symbols_have_no_reference_profile(symbol):
    assert profile_for(symbol) is None


@pytest.mark.parametrize(("symbol", "source", "canonical", "profile_id", "symbols"), PROFILE_CASES)
def test_real_analysis_downloads_only_the_selected_profile_and_keeps_base_model(
    client, profile_history, symbol, source, canonical, profile_id, symbols
):
    params = {"symbol": symbol, "source": source, "horizon": 5}
    base = client.get("/api/analysis", params=params).json()
    response = client.get(
        "/api/analysis", params={**params, "market_context": "us_overnight", "lang": "en"}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    context = result["market_context"]
    assert result["symbol"] == canonical
    assert context["reference_profile"] == profile_payload(profile_for(canonical))
    assert context["reference_profile"]["id"] == profile_id
    assert context["status"] == "ready"
    assert tuple(item["symbol"] for item in context["factors"]) == symbols
    assert "UMC" not in context["reference_profile"]["symbols"]
    assert profile_history["calls"]["factors"] == [symbols]
    assert profile_history["calls"]["targets"][-1] == (source, canonical)
    for key in ("forecast", "history", "backtest", "summary", "as_of"):
        assert result[key] == base[key]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("symbol", "source", "canonical", "profile_id", "symbols"), PROFILE_CASES)
def test_unclosed_us_session_skips_every_profile_download_but_retains_labels(
    client, profile_history, monkeypatch, symbol, source, canonical, profile_id, symbols
):
    before_close = datetime.fromisoformat("2026-10-30T04:14:59+08:00")
    monkeypatch.setattr(
        main, "pending_context", lambda p: overnight.pending_context(p, now=before_close)
    )
    monkeypatch.setattr(main, "overnight_factors", lambda *args: pytest.fail("US still trading"))
    monkeypatch.setattr(main, "build_context", lambda *args, **kwargs: pytest.fail("Too early"))
    response = client.get(
        "/api/analysis",
        params={"symbol": symbol, "source": source, "market_context": "us_overnight"},
    )
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert context["status"] == "waiting" and context["reason"] == "us_session_not_closed"
    assert context["forecast"] is None and context["factors"] == []
    assert context["reference_profile"]["id"] == profile_id
    assert tuple(context["reference_profile"]["symbols"]) == symbols


@pytest.mark.parametrize(("symbol", "source", "canonical", "profile_id", "symbols"), PROFILE_CASES)
def test_generic_csv_uses_selected_profile_without_live_us_download(
    client, profile_history, monkeypatch, symbol, source, canonical, profile_id, symbols
):
    monkeypatch.setattr(
        main, "overnight_factors", lambda *args: pytest.fail("CSV must stay offline")
    )
    files = {
        factor: as_csv(profile_history["original"][seed])
        for factor, seed in zip(symbols, ("UMC", "SOXX"))
    }
    response = client.post(
        ENDPOINT, json={"symbol": symbol, "source": source, "horizon": 10, "factor_csvs": files}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["symbol"] == canonical and len(result["forecast"]) == 10
    context = result["market_context"]
    assert context["data_source"] == "csv" and context["status"] == "ready"
    assert context["reference_profile"]["id"] == profile_id
    assert tuple(item["symbol"] for item in context["factors"]) == symbols


@pytest.mark.parametrize(
    ("files", "status"),
    [
        ({"TSM": "valid"}, 422),
        ({"TSM": "valid", "SOXX": "valid", "UMC": "extra"}, 422),
        ({"UMC": "wrong", "SOXX": "wrong"}, 400),
        ({"tsm": "lowercase", "SOXX": "valid"}, 400),
        ({}, 422),
    ],
)
def test_generic_csv_requires_exact_profile_keys_before_any_download(
    client, profile_history, files, status
):
    response = client.post(ENDPOINT, json={"symbol": "2330", "factor_csvs": files})
    assert response.status_code == status, response.text
    assert profile_history["calls"]["targets"] == profile_history["calls"]["factors"] == []


@pytest.mark.parametrize("legacy_field", ["umc_csv", "soxx_csv"])
def test_generic_and_legacy_csv_fields_cannot_be_mixed(client, profile_history, legacy_field):
    files = {
        "UMC": as_csv(profile_history["original"]["UMC"]),
        "SOXX": as_csv(profile_history["original"]["SOXX"]),
    }
    response = client.post(
        ENDPOINT, json={"symbol": "2303", "factor_csvs": files, legacy_field: files["UMC"]}
    )
    assert response.status_code == 400
    assert profile_history["calls"]["targets"] == profile_history["calls"]["factors"] == []


def test_generic_umc_csv_matches_legacy_numbers_and_profile(client, profile_history, monkeypatch):
    monkeypatch.setattr(main, "overnight_factors", lambda *args: pytest.fail("No live US data"))
    files = {
        "UMC": as_csv(profile_history["original"]["UMC"]),
        "SOXX": as_csv(profile_history["original"]["SOXX"]),
    }
    generic = client.post(ENDPOINT, json={"symbol": "2303", "factor_csvs": files})
    legacy = client.post(
        ENDPOINT,
        json={"symbol": "2303", "umc_csv": files["UMC"], "soxx_csv": files["SOXX"]},
    )
    assert generic.status_code == legacy.status_code == 200
    generic_body, legacy_body = generic.json(), legacy.json()
    assert generic_body["data_status"].pop("checked_at")
    assert legacy_body["data_status"].pop("checked_at")
    assert generic_body == legacy_body
    assert generic.json()["market_context"]["reference_profile"]["id"] == "umc"


def test_generic_csv_missing_session_is_unavailable_and_does_not_substitute_umc(
    client, profile_history, monkeypatch
):
    monkeypatch.setattr(main, "overnight_factors", lambda *args: pytest.fail("No fallback"))
    files = {
        "TSM": as_csv(profile_history["original"]["UMC"]),
        "SOXX": as_csv(
            [row for row in profile_history["original"]["SOXX"] if row["date"] != "2026-10-29"]
        ),
    }
    response = client.post(ENDPOINT, json={"symbol": "2330", "factor_csvs": files})
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert context["status"] == "unavailable" and context["reason"] == "missing_us_sessions"
    assert context["forecast"] is None
    assert tuple(context["reference_profile"]["symbols"]) == ("TSM", "SOXX")


def test_generic_csv_error_names_current_factor_and_does_not_echo_body(client, profile_history):
    files = {
        "TSM": "Date,Close\n2026-10-29,PRIVATE_UPLOAD_SECRET",
        "SOXX": as_csv(profile_history["original"]["SOXX"]),
    }
    response = client.post(ENDPOINT + "?lang=en", json={"symbol": "2330", "factor_csvs": files})
    assert response.status_code == 400
    assert "TSM" in response.json()["detail"] and "UMC" not in response.json()["detail"]
    assert "PRIVATE_UPLOAD_SECRET" not in response.text
    assert profile_history["calls"]["targets"] == []
