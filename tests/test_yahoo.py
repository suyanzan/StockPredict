"""Verify the optional adapter's data/error handling using captured-format fixtures."""

import json
from datetime import date, datetime, time, timedelta, timezone
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

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


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (401, "us_access_denied"),
        (403, "us_access_denied"),
        (404, "us_unavailable"),
        (429, "us_rate_limited"),
        (500, "us_unavailable"),
    ],
)
def test_yahoo_http_errors_become_safe_actionable_errors(monkeypatch, code, reason):
    def unavailable(request, timeout):
        raise HTTPError(request.full_url, code, "upstream failed", None, None)

    monkeypatch.setattr(data, "urlopen", unavailable)
    with pytest.raises(data.DataSourceError, match="Yahoo") as caught:
        data.yahoo_data("AAPL")
    assert caught.value.code == reason and caught.value.http_status == code
    assert caught.value.retry_after == (300 if code == 429 else None)


def test_yahoo_connection_failure_becomes_data_source_error(monkeypatch):
    def unavailable(request, timeout):
        raise URLError("network unavailable")

    monkeypatch.setattr(data, "urlopen", unavailable)
    with pytest.raises(data.DataSourceError, match="Yahoo") as caught:
        data.yahoo_data("AAPL")
    assert caught.value.code == "us_connection_failed"
    assert caught.value.http_status is None and caught.value.retry_after is None


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
    with pytest.raises(data.DataSourceError) as caught:
        data.yahoo_data("AAPL")
    assert caught.value.code == "us_invalid_data"


def test_data_source_error_preserves_strings_and_bounds_diagnostic_fields():
    original = data.DataSourceError("Application-owned safe error")
    assert str(original) == "Application-owned safe error"
    assert original.code == "data_unavailable"
    assert original.http_status is None and original.retry_after is None
    invalid = data.DataSourceError("Safe message", code=["untrusted"], http_status=True)
    assert invalid.code == "data_unavailable" and invalid.http_status is None
    assert data.DataSourceError("", retry_after=-10).retry_after == 1
    assert data.DataSourceError("", retry_after=10**100).retry_after == 86400
    assert data.DataSourceError("", retry_after="123").retry_after is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, 300),
        ("garbage", 300),
        ("0", 60),
        ("1", 60),
        ("60", 60),
        ("000180", 180),
        ("900", 900),
        ("999999", 86400),
        ("9" * 5000, 86400),
        ("Sat, 31 Oct 2026 02:05:01 GMT", 301),
        ("Sat, 31 Oct 2026 01:00:00 GMT", 60),
        ("Sat, 31 Oct 2026 02:05:00", 300),
    ],
)
def test_yahoo_rate_limit_uses_bounded_retry_hint_without_retrying(monkeypatch, header, expected):
    now = datetime(2026, 10, 31, 2, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(data, "_now", lambda tz: now.astimezone(tz))
    calls = []

    def limited(request, timeout):
        calls.append(request.full_url)
        headers = Message()
        if header is not None:
            headers["Retry-After"] = header
        raise HTTPError(request.full_url, 429, "Do not serialize upstream text", headers, None)

    monkeypatch.setattr(data, "urlopen", limited)
    with pytest.raises(data.DataSourceError) as caught:
        data.yahoo_data("UMC")
    assert caught.value.code == "us_rate_limited"
    assert caught.value.retry_after == expected and len(calls) == 1
    assert "Do not serialize" not in str(caught.value)


def test_yahoo_malformed_json_is_invalid_data_not_a_connection_failure(monkeypatch):
    monkeypatch.setattr(data, "urlopen", lambda *args, **kwargs: BytesIO(b"not json"))
    with pytest.raises(data.DataSourceError) as caught:
        data.yahoo_data("UMC")
    assert caught.value.code == "us_invalid_data"


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


def session_payload(monkeypatch, now_text, close_time="16:00"):
    """A daily candle supplied during and after the exchange's regular session."""
    zone = ZoneInfo("America/New_York")
    now = datetime.fromisoformat(now_text)
    local_day = now.astimezone(zone).date()
    monkeypatch.setattr(data, "_now", lambda tz: now.astimezone(tz))
    payload = yahoo_payload()
    result = payload["chart"]["result"][0]
    opens = datetime.combine(local_day, time(9, 30), zone)
    closes = datetime.combine(local_day, time.fromisoformat(close_time), zone)
    result["timestamp"][-1] = int(opens.timestamp())
    result["meta"].update(
        exchangeTimezoneName=zone.key,
        currentTradingPeriod={
            "regular": {"start": int(opens.timestamp()), "end": int(closes.timestamp())}
        },
    )
    return payload


@pytest.mark.parametrize(
    ("now_text", "close_time", "included"),
    [
        ("2026-10-30T15:00:00-04:00", "16:00", False),  # Still trading.
        ("2026-10-30T16:14:59-04:00", "16:00", False),
        ("2026-10-30T16:15:00-04:00", "16:00", True),
        ("2026-11-27T13:14:59-05:00", "13:00", False),  # Half-day session.
        ("2026-11-27T13:15:00-05:00", "13:00", True),
        ("2026-03-06T21:15:00+00:00", "16:00", True),  # Before DST.
        ("2026-03-09T20:15:00+00:00", "16:00", True),  # After DST.
        ("2026-10-31T04:15:00+08:00", "16:00", True),  # Taipei's next day.
    ],
)
def test_yahoo_only_includes_today_after_reported_session_and_buffer(
    monkeypatch, now_text, close_time, included
):
    payload = session_payload(monkeypatch, now_text, close_time)
    mock_response(monkeypatch, payload)
    points, _ = data.yahoo_data("AAPL")
    assert (points[-1]["close"] == 999.0) is included
    assert len(points) == 69 + included


@pytest.mark.parametrize(
    "schedule",
    [
        None,
        [],
        {},
        {"regular": None},
        {"regular": {"start": 1, "end": True}},
        {"regular": {"start": 1, "end": "1793390400"}},
        {"regular": {"start": 2, "end": 1}},
        {"regular": {"start": 1, "end": 2}},  # Another day.
        {"regular": {"start": 1, "end": 10**30}},
    ],
)
def test_yahoo_unconfirmed_session_keeps_previous_closes(monkeypatch, schedule):
    payload = session_payload(monkeypatch, "2026-10-30T17:00:00-04:00")
    payload["chart"]["result"][0]["meta"]["currentTradingPeriod"] = schedule
    mock_response(monkeypatch, payload)
    points, _ = data.yahoo_data("AAPL")
    assert len(points) == 69 and points[-1]["close"] == 169.0


def test_yahoo_missing_timezone_does_not_confirm_today(monkeypatch):
    payload = session_payload(monkeypatch, "2026-10-30T17:00:00-04:00")
    del payload["chart"]["result"][0]["meta"]["exchangeTimezoneName"]
    mock_response(monkeypatch, payload)
    points, _ = data.yahoo_data("AAPL")
    assert points[-1]["close"] == 169.0


def test_yahoo_published_close_never_includes_future_candle(monkeypatch):
    payload = session_payload(monkeypatch, "2026-10-30T17:00:00-04:00")
    result = payload["chart"]["result"][0]
    result["timestamp"].append(result["timestamp"][-1] + 86400)
    result["indicators"]["quote"][0]["close"].append(555.0)
    mock_response(monkeypatch, payload)
    points, _ = data.yahoo_data("AAPL")
    assert points[-1] == {"date": "2026-10-30", "close": 999.0}


@pytest.mark.parametrize("missing", ["null", "absent"])
def test_yahoo_does_not_invent_close_if_not_published(monkeypatch, missing):
    payload = session_payload(monkeypatch, "2026-10-30T17:00:00-04:00")
    result = payload["chart"]["result"][0]
    if missing == "null":
        result["indicators"]["quote"][0]["close"][-1] = None
    else:
        result["timestamp"].pop()
        result["indicators"]["quote"][0]["close"].pop()
    mock_response(monkeypatch, payload)
    points, _ = data.yahoo_data("AAPL")
    assert len(points) == 69 and points[-1]["close"] == 169.0
