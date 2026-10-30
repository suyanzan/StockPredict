"""TWSE monthly parsing, source separation, request pacing, and bounded caches."""

import calendar
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from io import BytesIO
from threading import Barrier
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import stockpredict.main as main
import stockpredict.twse as twse
from stockpredict.data import DataSourceError

TODAY = date(2026, 10, 30)
TAIPEI = ZoneInfo("Asia/Taipei")


def taipei_time(day=TODAY, hour=14, minute=59, second=59):
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=TAIPEI)


def month_payload(month, symbol="2303"):
    year, number = int(month[:4]), int(month[4:6])
    return {
        "stat": "OK",
        "date": month,
        "title": f"{year - 1911}年{number:02}月 {symbol} 聯電 各日成交資訊",
        "fields": ["日期", "收盤價"],
        "data": [
            [f"{year - 1911}/{number:02}/{day:02}", "1,234.50"]
            for day in range(1, calendar.monthrange(year, number)[1] + 1)
            if date(year, number, day).weekday() < 5
        ],
    }


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    twse.clear_cache()
    monkeypatch.setattr(twse, "_now", taipei_time)
    monkeypatch.setattr(twse, "_sleep", lambda seconds: None)
    clock = {"now": 10_000.0}
    monkeypatch.setattr(twse, "_clock", lambda: clock["now"])
    yield clock
    twse.clear_cache()


def mock_months(monkeypatch, transform=None):
    requests = []

    def response(request, timeout):
        parsed = urlparse(request.full_url)
        query = parse_qs(parsed.query)
        assert parsed.scheme == "https" and parsed.netloc == "www.twse.com.tw"
        assert query["response"] == ["json"] and timeout > 0
        month, symbol = query["date"][0], query["stockNo"][0]
        requests.append((month, symbol))
        payload = month_payload(month, symbol)
        return BytesIO(json.dumps(transform(payload) if transform else payload).encode())

    monkeypatch.setattr(twse, "urlopen", response)
    return requests


def test_completed_closes_are_sorted_and_current_date_excluded(monkeypatch):
    requests = mock_months(monkeypatch)
    points, meta = twse.twse_data("2303.TW")
    assert len(points) >= 100 and len(requests) <= 6
    assert requests[0] == ("20261001", "2303")
    assert requests == sorted(requests, reverse=True)
    assert points == sorted(points, key=lambda p: p["date"])
    assert all(date.fromisoformat(p["date"]) < TODAY and p["close"] == 1234.5 for p in points)
    assert meta["source"] == "twse" and meta["currency"] == "TWD" and meta["name"] == "聯電"


@pytest.mark.parametrize(
    "hour,minute,second,expected_last",
    [(14, 59, 59, "2026-10-29"), (15, 0, 0, "2026-10-30"), (23, 59, 59, "2026-10-30")],
)
def test_today_is_eligible_only_at_the_taipei_cutoff(
    monkeypatch, hour, minute, second, expected_last
):
    monkeypatch.setattr(twse, "_now", lambda: taipei_time(hour=hour, minute=minute, second=second))
    mock_months(monkeypatch)
    points, _ = twse.twse_data("2303")
    assert points[-1] == {"date": expected_last, "close": 1234.5}


def test_post_cutoff_does_not_invent_today_when_official_row_is_missing(monkeypatch):
    monkeypatch.setattr(twse, "_now", lambda: taipei_time(hour=15))

    def unpublished(payload):
        payload["data"] = [row for row in payload["data"] if row[0] != "115/10/30"]
        return payload

    mock_months(monkeypatch, unpublished)
    points, _ = twse.twse_data("2303")
    assert points[-1]["date"] == "2026-10-29"


def test_future_rows_still_excluded_after_cutoff(monkeypatch):
    monkeypatch.setattr(twse, "_now", lambda: taipei_time(date(2026, 10, 29), hour=15))
    mock_months(monkeypatch)
    points, _ = twse.twse_data("2303")
    assert points[-1]["date"] == "2026-10-29"
    assert all(point["date"] <= "2026-10-29" for point in points)


def test_suspended_today_is_not_treated_as_a_close_after_cutoff(monkeypatch):
    monkeypatch.setattr(twse, "_now", lambda: taipei_time(hour=15))

    def suspended(payload):
        for row in payload["data"]:
            if row[0] == "115/10/30":
                row[1] = "--"
        return payload

    mock_months(monkeypatch, suspended)
    points, _ = twse.twse_data("2303")
    assert points[-1]["date"] == "2026-10-29"


@pytest.mark.parametrize("symbol", ["2303", "2303.TW", "0050", "0050.tw", "006208"])
def test_numeric_listed_symbols(monkeypatch, symbol):
    requests = mock_months(monkeypatch)
    twse.twse_data(symbol)
    assert requests[0][1] == symbol.upper().removesuffix(".TW")


@pytest.mark.parametrize("symbol", ["AAPL", "2303.TWO", "123", "1234567", "../2303", "２３０３"])
def test_other_markets_rejected_without_network(monkeypatch, symbol):
    monkeypatch.setattr(twse, "urlopen", lambda *a, **kw: pytest.fail("Unexpected network"))
    with pytest.raises(ValueError):
        twse.twse_data(symbol)


def test_column_order_and_suspended_days(monkeypatch):
    def reorder(payload):
        payload["fields"] = ["成交股數", "收盤價", "日期"]
        payload["data"] = [["1000", row[1], row[0]] for row in payload["data"]]
        payload["data"][0][1] = "--"
        return payload

    mock_months(monkeypatch, reorder)
    points, _ = twse.twse_data("2303")
    assert len(points) >= 100
    assert all(p["close"] == 1234.5 for p in points)


@pytest.mark.parametrize("per_month,success", [(10, True), (9, False)])
def test_six_month_minimum_history(monkeypatch, per_month, success):
    calls = mock_months(monkeypatch, lambda p: {**p, "data": p["data"][:per_month]})
    if success:
        assert len(twse.twse_data("2303")[0]) == 60
    else:
        with pytest.raises(DataSourceError):
            twse.twse_data("2303")
    assert len(calls) == 6


def test_official_empty_month_does_not_stop_history_collection(monkeypatch):
    def current_empty(payload):
        return {"stat": "很抱歉，沒有符合條件的資料!"} if payload["date"] == "20261001" else payload

    calls = mock_months(monkeypatch, current_empty)
    points, _ = twse.twse_data("2303")
    assert len(calls) == 6 and len(points) >= 100
    assert all(p["date"] < "2026-10-01" for p in points)


@pytest.mark.parametrize("close", ["0", "-1", "nan", "inf", "bad", "", "1e13", "12,34.5"])
def test_bad_prices_are_not_silently_dropped(monkeypatch, close):
    def corrupt(payload):
        payload["data"][0][1] = close
        return payload

    mock_months(monkeypatch, corrupt)
    with pytest.raises(DataSourceError):
        twse.twse_data("2303")


@pytest.mark.parametrize("day", ["115/02/30", "2026-10-01", "114/10/01", "not-a-date"])
def test_invalid_or_wrong_month_dates(monkeypatch, day):
    def corrupt(payload):
        payload["data"][0][0] = day
        return payload

    mock_months(monkeypatch, corrupt)
    with pytest.raises(DataSourceError):
        twse.twse_data("2303")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"stat": "OK", "fields": None, "data": []},
        {"stat": "OK", "fields": ["日期", "成交股數"], "data": []},
        {"stat": "OK", "fields": ["日期", "收盤價"], "data": {}},
        {"stat": "unexpected service error"},
    ],
)
def test_malformed_response(monkeypatch, payload):
    mock_months(monkeypatch, lambda _: payload)
    with pytest.raises(DataSourceError):
        twse.twse_data("2303")


@pytest.mark.parametrize("code", [403, 404, 429, 500])
def test_http_error_not_retried(monkeypatch, code):
    calls = []

    def unavailable(request, timeout):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, code, "unavailable", None, None)

    monkeypatch.setattr(twse, "urlopen", unavailable)
    with pytest.raises(DataSourceError):
        twse.twse_data("2303")
    assert len(calls) == 1


def test_alias_cache_expires_in_one_hour(monkeypatch, isolated_cache):
    calls = mock_months(monkeypatch)
    original = twse.twse_data("2303")
    count = len(calls)
    isolated_cache["now"] += 3599
    assert twse.twse_data("2303.TW") == original and len(calls) == count
    isolated_cache["now"] += 2
    assert twse.twse_data("2303") == original and len(calls) == count * 2


def test_pre_cutoff_cache_cannot_hide_newly_eligible_close(monkeypatch):
    calls = mock_months(monkeypatch)
    before, _ = twse.twse_data("2303")
    count = len(calls)
    assert before[-1]["date"] == "2026-10-29"
    monkeypatch.setattr(twse, "_now", lambda: taipei_time(hour=15, minute=0, second=0))
    after, _ = twse.twse_data("2303")
    assert after[-1]["date"] == "2026-10-30" and len(calls) > count


def test_missing_weekday_close_rechecks_after_five_minutes_then_caches_hour(
    monkeypatch, isolated_cache
):
    monkeypatch.setattr(twse, "_now", lambda: taipei_time(hour=15))
    published = {"today": False}

    def official_rows(payload):
        if not published["today"]:
            payload["data"] = [row for row in payload["data"] if row[0] != "115/10/30"]
        return payload

    calls = mock_months(monkeypatch, official_rows)
    old, _ = twse.twse_data("2303")
    count = len(calls)
    assert old[-1]["date"] == "2026-10-29"
    published["today"] = True
    isolated_cache["now"] += 299
    assert twse.twse_data("2303")[0] == old and len(calls) == count
    isolated_cache["now"] += 1
    fresh = twse.twse_data("2303")[0]
    assert fresh[-1]["date"] == "2026-10-30" and len(calls) == count * 2
    isolated_cache["now"] += 3599
    assert twse.twse_data("2303")[0] == fresh and len(calls) == count * 2
    isolated_cache["now"] += 1
    twse.twse_data("2303")
    assert len(calls) == count * 3


def test_weekend_missing_today_keeps_hour_cache(monkeypatch, isolated_cache):
    monkeypatch.setattr(twse, "_now", lambda: taipei_time(date(2026, 10, 31), hour=15))
    calls = mock_months(monkeypatch)
    points, _ = twse.twse_data("2303")
    assert points[-1]["date"] == "2026-10-30"
    count = len(calls)
    isolated_cache["now"] += 301
    assert twse.twse_data("2303")[0] == points and len(calls) == count


def test_cache_does_not_survive_taipei_midnight(monkeypatch):
    calls = mock_months(monkeypatch)
    twse.twse_data("2303")
    count = len(calls)
    monkeypatch.setattr(twse, "_now", lambda: taipei_time(date(2026, 10, 31), hour=0))
    twse.twse_data("2303")
    assert len(calls) > count


def test_errors_are_cached_for_sixty_seconds(monkeypatch, isolated_cache):
    calls = []

    def unavailable(request, timeout):
        calls.append(request.full_url)
        raise URLError("unavailable")

    monkeypatch.setattr(twse, "urlopen", unavailable)
    for increment in [0, 59, 2]:
        isolated_cache["now"] += increment
        with pytest.raises(DataSourceError):
            twse.twse_data("2303.TW")
    assert len(calls) == 2


def test_return_values_are_detached_from_cache(monkeypatch):
    mock_months(monkeypatch)
    points, meta = twse.twse_data("2303")
    points[0]["close"] = 0
    meta["name"] = "changed"
    fresh, metadata = twse.twse_data("2303")
    assert fresh[0]["close"] == 1234.5 and metadata["name"] == "聯電"


def test_expired_prices_not_returned_when_refresh_fails(monkeypatch, isolated_cache):
    mock_months(monkeypatch)
    twse.twse_data("2303")
    isolated_cache["now"] += 3601

    def unavailable(request, timeout):
        raise URLError("unavailable")

    monkeypatch.setattr(twse, "urlopen", unavailable)
    with pytest.raises(DataSourceError):
        twse.twse_data("2303")


def test_concurrent_requests_share_download(monkeypatch):
    calls = mock_months(monkeypatch)
    start = Barrier(4)

    def fetch():
        start.wait(timeout=5)
        return twse.twse_data("2303")

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch) for _ in range(4)]
        results = [f.result(timeout=10) for f in futures]
    assert all(result == results[0] for result in results) and len(calls) <= 6


def test_request_spacing(monkeypatch, isolated_cache):
    calls = mock_months(monkeypatch)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        isolated_cache["now"] += seconds

    monkeypatch.setattr(twse, "_sleep", sleep)
    twse.twse_data("2303")
    assert len(sleeps) == len(calls) - 1
    assert all(seconds >= 3 for seconds in sleeps)


def test_busy_fetch_fails_promptly_without_network(monkeypatch):
    class BusyLock:
        def acquire(self, timeout):
            assert timeout == 2
            return False

    # Restore before the autouse fixture's clear_cache teardown.
    with monkeypatch.context() as patch:
        patch.setattr(twse, "_LOCK", BusyLock())
        patch.setattr(twse, "urlopen", lambda *a, **kw: pytest.fail("Unexpected network"))
        with pytest.raises(DataSourceError, match="讀取中"):
            twse.twse_data("2303")


def test_lru_limits_successful_cache_to_sixty_four_symbols(monkeypatch):
    calls = mock_months(monkeypatch)
    for number in range(2100, 2164):
        twse.twse_data(str(number))
    count = sum(symbol == "2100" for _, symbol in calls)
    twse.twse_data("2100")
    twse.twse_data("2164")
    twse.twse_data("2100")
    assert sum(symbol == "2100" for _, symbol in calls) == count
    twse.twse_data("2101")
    assert sum(symbol == "2101" for _, symbol in calls) == count * 2


def test_api_canonical_symbol_and_cache_reused_for_new_horizon(monkeypatch):
    calls = mock_months(monkeypatch)
    with TestClient(main.app) as client:
        short = client.get(
            "/api/analysis", params={"source": "twse", "symbol": "2303", "horizon": 5}
        )
        assert short.status_code == 200, short.text
        count = len(calls)
        long = client.get(
            "/api/analysis", params={"source": "twse", "symbol": "2303.TW", "horizon": 20}
        )
    assert long.status_code == 200, long.text
    assert short.json()["symbol"] == long.json()["symbol"] == "2303.TW"
    assert short.json()["source"] == long.json()["source"] == "twse"
    assert len(short.json()["forecast"]) == 5 and len(long.json()["forecast"]) == 20
    assert len(calls) == count


def test_api_uses_published_today_close_as_forecast_origin_after_cutoff(monkeypatch):
    monkeypatch.setattr(twse, "_now", lambda: taipei_time(hour=15))
    mock_months(monkeypatch)
    with TestClient(main.app) as client:
        response = client.get(
            "/api/analysis", params={"source": "twse", "symbol": "2303", "horizon": 5}
        )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["source"] == "twse" and result["as_of"] == "2026-10-30"
    assert result["history"][-1] == {"date": "2026-10-30", "close": 1234.5}
    assert result["forecast"][0]["date"] == "2026-11-02"


def test_api_does_not_silently_switch_to_yahoo_or_demo(monkeypatch):
    def unavailable(symbol):
        raise DataSourceError("TWSE unavailable")

    def forbidden(symbol):
        pytest.fail("Unexpected data source fallback")

    monkeypatch.setattr(main, "twse_data", unavailable)
    monkeypatch.setattr(main, "yahoo_data", forbidden)
    monkeypatch.setattr(main, "demo_data", forbidden)
    with TestClient(main.app) as client:
        response = client.get("/api/analysis", params={"source": "twse", "symbol": "2303"})
    assert response.status_code == 502 and "TWSE" in response.json()["detail"]
