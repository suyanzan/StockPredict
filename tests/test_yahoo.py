"""Verify the optional adapter's data/error handling using captured-format fixtures."""

import json
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

import stockpredict.data as data


def yahoo_payload():
    dates = [date(2025, 1, 1) + timedelta(days=index) for index in range(70)]
    today = datetime.now(timezone.utc).date()
    dates.append(today)
    timestamps = [
        int(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        for day in dates
    ]
    closes = [100.0 + index for index in range(70)] + [999.0]
    closes[20] = None
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "longName": "Example Corporation",
                        "currency": "USD",
                        "exchangeTimezoneName": "UTC",
                    },
                    "timestamp": timestamps,
                    "indicators": {"quote": [{"close": closes}]},
                }
            ],
        }
    }


def mock_response(monkeypatch, payload):
    requests = []

    def open_response(request, timeout):
        requests.append((request, timeout))
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(data, "urlopen", open_response)
    return requests


def test_yahoo_filters_null_prices_and_incomplete_today_candle(monkeypatch):
    requests = mock_response(monkeypatch, yahoo_payload())
    points, metadata = data.yahoo_data("AAPL")

    assert len(points) == 69
    assert points[0] == {"date": "2025-01-01", "close": 100.0}
    assert points[-1]["close"] == 169.0
    assert metadata["source"] == "yahoo"
    assert metadata["currency"] == "USD"
    assert metadata["name"] == "Example Corporation"
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url.startswith("https://query1.finance.yahoo.com/")
    assert "/AAPL?" in request.full_url
    assert timeout > 0


@pytest.mark.parametrize(
    ("long_name", "short_name", "currency", "expected_name", "expected_currency"),
    [
        (["malformed"], "Valid Short Name", "USD", "Valid Short Name", "USD"),
        ({"name": "malformed"}, None, ["USD"], "AAPL", ""),
        (None, {"name": "malformed"}, {"code": "USD"}, "AAPL", ""),
        ("", "", None, "AAPL", ""),
    ],
)
def test_yahoo_uses_safe_strings_for_display_metadata(
    monkeypatch, long_name, short_name, currency, expected_name, expected_currency
):
    payload = yahoo_payload()
    payload["chart"]["result"][0]["meta"].update(
        longName=long_name, shortName=short_name, currency=currency
    )
    mock_response(monkeypatch, payload)

    _, metadata = data.yahoo_data("AAPL")
    assert metadata["name"] == expected_name
    assert metadata["currency"] == expected_currency


@pytest.mark.parametrize("code", [403, 404, 429, 500])
def test_yahoo_http_errors_become_safe_actionable_errors(monkeypatch, code):
    def unavailable(request, timeout):
        raise HTTPError(request.full_url, code, "upstream failed", None, None)

    monkeypatch.setattr(data, "urlopen", unavailable)
    with pytest.raises(data.DataSourceError, match="Yahoo"):
        data.yahoo_data("AAPL")


def test_yahoo_connection_failure_becomes_data_source_error(monkeypatch):
    def unavailable(request, timeout):
        raise URLError("network unavailable")

    monkeypatch.setattr(data, "urlopen", unavailable)
    with pytest.raises(data.DataSourceError, match="Yahoo"):
        data.yahoo_data("AAPL")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"chart": None},
        {"chart": []},
        {"chart": {"error": {"description": "Bad symbol"}, "result": None}},
        {"chart": {"error": None, "result": []}},
        {"chart": {"error": None, "result": [None]}},
        {"chart": {"error": None, "result": [{"meta": None}]}},
        {"chart": {"error": None, "result": [{"meta": []}]}},
    ],
)
def test_yahoo_rejects_invalid_or_empty_responses(monkeypatch, payload):
    mock_response(monkeypatch, payload)
    with pytest.raises(data.DataSourceError):
        data.yahoo_data("AAPL")


@pytest.mark.parametrize("field", ["close", "timestamp"])
def test_yahoo_rejects_object_instead_of_observation_array(monkeypatch, field):
    payload = yahoo_payload()
    result = payload["chart"]["result"][0]
    if field == "close":
        result["indicators"]["quote"][0]["close"] = {"bad": 100}
    else:
        result["timestamp"] = {"bad": 100}
    mock_response(monkeypatch, payload)
    with pytest.raises(data.DataSourceError):
        data.yahoo_data("AAPL")


def test_yahoo_rejects_misaligned_price_and_timestamp_arrays(monkeypatch):
    payload = yahoo_payload()
    payload["chart"]["result"][0]["timestamp"].pop()
    mock_response(monkeypatch, payload)
    with pytest.raises(data.DataSourceError):
        data.yahoo_data("AAPL")


def test_yahoo_rejects_non_finite_closes(monkeypatch):
    payload = yahoo_payload()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][5] = float("inf")
    mock_response(monkeypatch, payload)
    with pytest.raises(data.DataSourceError):
        data.yahoo_data("AAPL")
