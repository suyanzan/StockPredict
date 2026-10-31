"""US factor CSV imports bypass Yahoo without changing the Taiwan base model."""

from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_overnight import fixture_data, ready_now

import stockpredict.main as main
import stockpredict.overnight as overnight
from stockpredict.data import DataSourceError

ENDPOINT = "/api/analysis/overnight/csv"


def as_csv(points):
    return "Date,Close\n" + "\n".join(f"{point['date']},{point['close']}" for point in points)


@pytest.fixture
def client():
    with TestClient(main.app) as instance:
        yield instance


@pytest.fixture
def imported_factors(monkeypatch):
    points, factors = fixture_data()
    builder = main.build_context
    target_requests = []

    def provider(symbol, source):
        target_requests.append((source, symbol))
        return deepcopy(points), {
            "name": "聯電",
            "currency": "TWD",
            "source": source,
            "source_label": "Test Taiwan history",
        }

    monkeypatch.setattr(main, "twse_data", lambda symbol: provider(symbol, "twse"))
    monkeypatch.setattr(main, "yahoo_data", lambda symbol: provider(symbol, "yahoo"))
    monkeypatch.setattr(
        main, "build_context", lambda p, f, **kwargs: builder(p, f, now=ready_now(), **kwargs)
    )
    monkeypatch.setattr(
        main, "pending_context", lambda p: overnight.pending_context(p, now=ready_now())
    )
    monkeypatch.setattr(main, "overnight_factors", lambda: pytest.fail("Unexpected US download"))
    return {
        "points": points,
        "factors": factors,
        "requests": target_requests,
        "body": {"umc_csv": as_csv(factors["UMC"]), "soxx_csv": as_csv(factors["SOXX"])},
    }


def test_csv_route_uses_actual_factor_model_and_preserves_base_analysis(client, imported_factors):
    base = client.get("/api/analysis?symbol=2303&source=twse&horizon=5").json()
    response = client.post(ENDPOINT + "?lang=en", json=imported_factors["body"])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["symbol"] == "2303.TW" and result["source"] == "twse"
    context = result["market_context"]
    assert context["data_source"] == "csv"
    assert context["status"] == "ready"
    assert context["forecast"]["date"] == "2026-10-30"
    assert context["forecast"]["base_close"] == result["summary"]["last_close"]
    assert all(item["last_session"] == "2026-10-29" for item in context["factors"])
    assert context["backtest"]["observations"] == len(context["backtest"]["dates"])
    for key in ("forecast", "history", "summary", "backtest", "as_of"):
        assert result[key] == base[key]


@pytest.mark.parametrize("source", ["twse", "yahoo"])
@pytest.mark.parametrize("symbol", ["2303", "2303.TW"])
def test_csv_route_canonicalizes_umc_for_supported_target_sources(
    client, imported_factors, source, symbol
):
    response = client.post(
        ENDPOINT,
        json={**imported_factors["body"], "source": source, "symbol": symbol, "horizon": 10},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["symbol"] == "2303.TW"
    assert result["source"] == source and len(result["forecast"]) == 10
    assert imported_factors["requests"] == [(source, "2303.TW")]


def test_csv_import_accepts_bom_extra_columns_and_reverse_dates(client, imported_factors):
    factors = imported_factors["factors"]

    def alternate(rows):
        return "\ufeffdate,cLoSe,Unused\n" + "\n".join(
            f"{point['date']},{point['close']},ignored" for point in reversed(rows)
        )

    body = {"umc_csv": alternate(factors["UMC"]), "soxx_csv": alternate(factors["SOXX"])}
    response = client.post(ENDPOINT, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["market_context"]["status"] == "ready"


@pytest.mark.parametrize("source", ["demo", "csv", "unrecognized"])
def test_unsupported_target_source_is_rejected_before_network(client, imported_factors, source):
    response = client.post(ENDPOINT, json={**imported_factors["body"], "source": source})
    assert response.status_code == 422
    assert imported_factors["requests"] == []


@pytest.mark.parametrize("symbol", ["AAPL", "2330.TW", "2303.TWO"])
def test_legacy_umc_files_are_rejected_for_other_stocks_before_network(
    client, imported_factors, symbol
):
    response = client.post(ENDPOINT, json={**imported_factors["body"], "symbol": symbol})
    assert response.status_code == 400
    assert imported_factors["requests"] == []


@pytest.mark.parametrize("horizon", [0, 31, True, 5.0, "5"])
def test_csv_factor_horizon_is_strictly_validated(client, imported_factors, horizon):
    response = client.post(ENDPOINT, json={**imported_factors["body"], "horizon": horizon})
    assert response.status_code == 422
    assert imported_factors["requests"] == []


@pytest.mark.parametrize("field", ["umc_csv", "soxx_csv"])
@pytest.mark.parametrize("lang", ["zh-TW", "en"])
def test_malformed_csv_identifies_factor_without_echoing_contents(
    client, imported_factors, field, lang
):
    rows = imported_factors["body"][field].splitlines()
    rows[20] = rows[20].split(",")[0] + ",PRIVATE_UPLOAD_SENTINEL<script>"
    body = {**imported_factors["body"], field: "\n".join(rows)}
    response = client.post(ENDPOINT + "?lang=" + lang, json=body)
    assert response.status_code == 400
    payload = response.json()
    assert ("UMC" if field == "umc_csv" else "SOXX") in payload["detail"]
    assert set(payload["locales"]) == {"zh-TW", "en"}
    assert "PRIVATE_UPLOAD_SENTINEL" not in response.text and "<script>" not in response.text
    assert imported_factors["requests"] == []


@pytest.mark.parametrize("invalid", ["too_short", "duplicate_date", "nan", "negative"])
def test_factor_csv_validation_never_uses_partial_or_invalid_history(
    client, imported_factors, invalid
):
    rows = deepcopy(imported_factors["factors"]["UMC"])
    if invalid == "too_short":
        rows = rows[:59]
    elif invalid == "duplicate_date":
        rows[20]["date"] = rows[19]["date"]
    elif invalid == "nan":
        rows[20]["close"] = "nan"
    else:
        rows[20]["close"] = -1
    response = client.post(ENDPOINT, json={**imported_factors["body"], "umc_csv": as_csv(rows)})
    assert response.status_code == 400
    assert imported_factors["requests"] == []


@pytest.mark.parametrize("field", ["umc_csv", "soxx_csv"])
def test_empty_factor_csv_is_rejected(client, imported_factors, field):
    response = client.post(ENDPOINT, json={**imported_factors["body"], field: ""})
    assert response.status_code == 422
    assert imported_factors["requests"] == []


def test_csv_size_limit_counts_utf8_bytes_not_only_characters(client, imported_factors):
    response = client.post(ENDPOINT, json={**imported_factors["body"], "umc_csv": "中" * 666_667})
    assert response.status_code in {400, 422}
    assert imported_factors["requests"] == []


def test_more_than_five_thousand_rows_is_rejected_before_network(client, imported_factors):
    rows = [
        {"date": (date(2000, 1, 1) + timedelta(days=index)).isoformat(), "close": 100.0}
        for index in range(5001)
    ]
    response = client.post(ENDPOINT, json={**imported_factors["body"], "umc_csv": as_csv(rows)})
    assert response.status_code == 400
    assert imported_factors["requests"] == []


def test_valid_minimum_csv_returns_model_history_status_instead_of_validation_error(
    client, imported_factors
):
    response = client.post(
        ENDPOINT,
        json={
            "umc_csv": as_csv(imported_factors["factors"]["UMC"][-60:]),
            "soxx_csv": as_csv(imported_factors["factors"]["SOXX"][-60:]),
        },
    )
    assert response.status_code == 200
    context = response.json()["market_context"]
    assert context["status"] == "unavailable"
    assert context["reason"] == "insufficient_aligned_history" and context["forecast"] is None


def test_oversized_csv_string_is_schema_rejected(client, imported_factors):
    response = client.post(ENDPOINT, json={**imported_factors["body"], "soxx_csv": "x" * 2_000_001})
    assert response.status_code == 422
    assert "x" * 100 not in response.text
    assert imported_factors["requests"] == []


def test_csv_import_does_not_hide_target_stock_provider_failure(
    client, imported_factors, monkeypatch
):
    def unavailable(_):
        raise DataSourceError("TWSE unavailable")

    monkeypatch.setattr(main, "twse_data", unavailable)
    response = client.post(ENDPOINT, json=imported_factors["body"])
    assert response.status_code == 502
    assert "TWSE" in response.json()["detail"]


def test_csv_missing_required_session_is_unavailable_not_a_yahoo_fallback(client, imported_factors):
    rows = [point for point in imported_factors["factors"]["SOXX"] if point["date"] != "2026-10-29"]
    response = client.post(ENDPOINT, json={**imported_factors["body"], "soxx_csv": as_csv(rows)})
    assert response.status_code == 200, response.text
    context = response.json()["market_context"]
    assert context["data_source"] == "csv"
    assert context["status"] == "unavailable"
    assert context["reason"] == "missing_us_sessions" and context["forecast"] is None


def test_yahoo_context_reports_download_source(client, imported_factors, monkeypatch):
    monkeypatch.setattr(main, "overnight_factors", lambda: imported_factors["factors"])
    response = client.get("/api/analysis?symbol=2303&source=twse&market_context=us_overnight")
    assert response.status_code == 200
    context = response.json()["market_context"]
    assert context["data_source"] == "yahoo" and context["status"] == "ready"


def test_typed_yahoo_failure_retains_safe_reason_and_retry_without_leaking_text(
    client, imported_factors, monkeypatch
):
    def unavailable():
        raise DataSourceError(
            "SECRET_PROVIDER_DETAIL https://not-for-response.invalid",
            code="us_rate_limited",
            http_status=429,
            retry_after=300,
        )

    monkeypatch.setattr(main, "overnight_factors", unavailable)
    response = client.get("/api/analysis?symbol=2303&source=twse&market_context=us_overnight")
    assert response.status_code == 200
    payload = response.json()
    context = payload["market_context"]
    assert context["status"] == "unavailable" and context["reason"] == "us_rate_limited"
    assert context["retry_after_seconds"] == 300 and context["http_status"] == 429
    assert context["data_source"] == "yahoo"
    assert context["forecast"] is None and payload["forecast"]
    assert "SECRET_PROVIDER_DETAIL" not in response.text
    assert "not-for-response.invalid" not in response.text


def test_csv_does_not_supply_old_us_data_while_required_session_is_unclosed(
    client, imported_factors, monkeypatch
):
    before_close = datetime.fromisoformat("2026-10-30T04:14:59+08:00")
    monkeypatch.setattr(
        main, "pending_context", lambda p: overnight.pending_context(p, now=before_close)
    )
    monkeypatch.setattr(
        main, "build_context", lambda *args: pytest.fail("CSV factors used too soon")
    )
    response = client.post(ENDPOINT, json=imported_factors["body"])
    assert response.status_code == 200, response.text
    result = response.json()
    context = result["market_context"]
    assert context["data_source"] == "csv"
    assert context["status"] == "waiting" and context["reason"] == "us_session_not_closed"
    assert context["required_us_session_date"] == "2026-10-29"
    assert context["factors"] == []
    assert context["forecast"] is context["backtest"] is context["correlations_window"] is None
    assert result["forecast"] and result["backtest"]
