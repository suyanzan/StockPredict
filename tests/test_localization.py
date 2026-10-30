"""Language changes must preserve analysis data and useful failure details."""

import re
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_data import csv_text

import stockpredict.main as main
from stockpredict.data import DataSourceError, demo_data
from stockpredict.forecast import analyze
from stockpredict.localization import add_localizations, localize_error

CJK = re.compile(r"[\u3400-\u9fff]")


@pytest.fixture
def client():
    with TestClient(main.app) as instance:
        yield instance


def assert_english_presentation(result):
    texts = [
        result["name"],
        result["source_label"],
        result["model"]["description"],
        result["model"]["interval_description"],
        *result["warnings"],
    ]
    assert all(isinstance(text, str) and text.strip() for text in texts)
    assert all(not CJK.search(text) for text in texts)


@pytest.mark.parametrize("symbol", ["2330.TW", "0050.TW", "AAPL", "MSFT"])
def test_english_demo_translates_all_presentation_without_changing_numbers(client, symbol):
    params = {"symbol": symbol, "source": "demo", "horizon": 10}
    zh = client.get("/api/analysis", params=params).json()
    response = client.get("/api/analysis", params={**params, "lang": "en"})
    assert response.status_code == 200, response.text
    en = response.json()
    assert_english_presentation(en)
    assert "synthetic" in en["source_label"].lower()
    assert "not actual" in en["warnings"][0].lower()
    for key in (
        "symbol",
        "currency",
        "source",
        "as_of",
        "history",
        "forecast",
        "summary",
        "backtest",
    ):
        assert zh[key] == en[key]
    assert en["locales"] == zh["locales"]
    for key in ("name", "source_label", "model", "warnings"):
        assert zh[key] == en["locales"]["zh-TW"][key]
        assert en[key] == en["locales"]["en"][key]


def test_chinese_is_default_and_explicit_locale_is_repeatable(client):
    implicit = client.get("/api/analysis").json()
    explicit = client.get("/api/analysis", params={"lang": "zh-TW"}).json()
    assert implicit == explicit
    assert CJK.search(implicit["source_label"])
    assert set(implicit["locales"]) == {"zh-TW", "en"}


def test_localized_metadata_does_not_mutate_source_or_other_language():
    points, metadata = demo_data("2330.TW")
    original = {"symbol": "2330.TW", **metadata, **analyze(points, horizon=5)}
    before = deepcopy(original)
    translated = add_localizations(original, "en")
    assert original == before
    assert translated["locales"]["zh-TW"]["model"] is not original["model"]
    assert translated["locales"]["zh-TW"]["warnings"] is not original["warnings"]
    translated["locales"]["zh-TW"]["warnings"].append("changed")
    translated["locales"]["zh-TW"]["model"]["description"] = "changed"
    assert original == before
    assert "changed" not in translated["locales"]["en"]["warnings"]
    assert translated["locales"]["en"]["model"]["description"] != "changed"


def test_csv_presentation_is_english_while_imported_prices_are_preserved(client):
    body = {"symbol": "CUSTOM", "horizon": 5, "csv": csv_text()}
    zh = client.post("/api/analysis/csv", json=body).json()
    response = client.post("/api/analysis/csv?lang=en", json=body)
    assert response.status_code == 200, response.text
    en = response.json()
    assert_english_presentation(en)
    assert "CSV" in en["source_label"]
    assert "user" in en["warnings"][0].lower()
    assert en["currency"] == ""
    for key in ("history", "forecast", "summary", "backtest"):
        assert en[key] == zh[key]


def test_yahoo_rate_limit_is_actionable_in_both_languages_without_refetch(client, monkeypatch):
    message = (
        "Yahoo 已限流（HTTP 429）。上市台股請改用「證交所每日行情」，美股請稍後重試或匯入 CSV。"
    )
    requests = []

    def unavailable(symbol):
        requests.append(symbol)
        raise DataSourceError(message)

    monkeypatch.setattr(main, "yahoo_data", unavailable)
    response = client.get(
        "/api/analysis", params={"symbol": "2303.TW", "source": "yahoo", "lang": "en"}
    )
    assert response.status_code == 502
    body = response.json()
    assert "429" in body["detail"] and "TWSE" in body["detail"]
    assert not CJK.search(body["detail"])
    assert body["locales"]["en"] == body["detail"]
    assert body["locales"]["zh-TW"] == message
    assert requests == ["2303.TW"]


@pytest.mark.parametrize(
    ("csv", "expected_fragment"),
    [
        (csv_text(count=59), "60"),
        (csv_text(bad_row="2025-02-30,101"), "Row 22"),
        (csv_text(bad_row="2025-01-21,not-a-number"), "Row 22"),
        (csv_text(header="Date,Price"), "Date and Close"),
    ],
)
def test_invalid_csv_errors_keep_useful_details_in_english(client, csv, expected_fragment):
    response = client.post("/api/analysis/csv?lang=en", json={"csv": csv})
    assert response.status_code == 400
    body = response.json()
    assert expected_fragment in body["detail"]
    assert not CJK.search(body["detail"])
    assert body["locales"]["en"] == body["detail"]
    assert CJK.search(body["locales"]["zh-TW"])


@pytest.mark.parametrize("symbol", ["AAPL", "2303.TWO"])
def test_unsupported_twse_market_has_english_error_before_network(client, monkeypatch, symbol):
    def forbidden_request(*args, **kwargs):
        pytest.fail("An unsupported market must not reach TWSE")

    monkeypatch.setattr(main, "twse_data", forbidden_request)
    response = client.get(
        "/api/analysis", params={"source": "twse", "symbol": symbol, "lang": "en"}
    )
    assert response.status_code == 400
    body = response.json()
    assert "TWSE" in body["detail"] and "OTC" in body["detail"]
    assert not CJK.search(body["detail"])
    assert CJK.search(body["locales"]["zh-TW"])


@pytest.mark.parametrize("method", ["get", "post"])
def test_unsupported_language_is_rejected(client, method):
    if method == "get":
        response = client.get("/api/analysis?lang=fr")
    else:
        response = client.post("/api/analysis/csv?lang=fr", json={"csv": csv_text()})
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("第 17 列欄位數與標題不符。", "Row 17"),
        ("第 4 列需要 YYYY-MM-DD 日期與有效收盤價。", "Row 4"),
        ("Yahoo 行情暫時無法使用（HTTP 403），請改用 CSV 或示範資料。", "HTTP 403"),
        ("證交所行情暫時無法使用（HTTP 503），請稍後重試或匯入 CSV。", "HTTP 503"),
    ],
)
def test_dynamic_errors_retain_row_numbers_and_http_status(message, expected):
    result = localize_error(message, "en")
    assert expected in result and not CJK.search(result)
    assert localize_error(message, "zh-TW") == message


def test_unknown_chinese_error_uses_safe_english_fallback():
    result = localize_error("未預期的資料錯誤。", "en")
    assert "analysis" in result.lower() and not CJK.search(result)


def test_already_english_error_remains_actionable():
    message = "TWSE temporarily unavailable"
    assert localize_error(message, "en") == message
