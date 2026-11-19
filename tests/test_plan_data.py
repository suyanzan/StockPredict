"""Published 0050 history: generator windows, file format and strict reader."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

import stockpredict.plan_data as plan_data
from stockpredict.data import DataSourceError

NOW = datetime(2026, 11, 19, 7, 0, tzinfo=timezone.utc)


def days(count, start=date(2010, 1, 4)):
    day, result = start, []
    while len(result) < count:
        if day.weekday() < 5:
            result.append(day.isoformat())
        day += timedelta(days=1)
    return result


def points(count=300):
    return [{"date": d, "close": 50 + i * 0.1} for i, d in enumerate(days(count))]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(plan_data, "_sleep", lambda _: None)


def test_fetch_uses_one_year_windows_newest_first(monkeypatch):
    calls = []

    def fake(symbol, **kwargs):
        calls.append(kwargs["period"])
        return points(), {"currency": "TWD"}

    monkeypatch.setattr(plan_data, "yahoo_data", fake)
    result = plan_data.fetch_history(int(NOW.timestamp()))
    assert len(calls) == plan_data.HISTORY_YEARS
    assert calls[0][1] == int(NOW.timestamp())
    assert all(newer[0] == older[1] for newer, older in zip(calls, calls[1:]))
    assert all(0 < end - begin <= plan_data.CHUNK_SECONDS for begin, end in calls)
    assert [p["date"] for p in result] == days(300)


def test_fetch_retries_rate_limits_then_fails_without_partial_history(monkeypatch):
    calls = []

    def fake(symbol, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise DataSourceError("hidden", code="us_rate_limited")
        if len(calls) > 3:
            raise DataSourceError("hidden", code="us_access_denied")
        return points(), {}

    monkeypatch.setattr(plan_data, "yahoo_data", fake)
    with pytest.raises(DataSourceError) as error:
        plan_data.fetch_history(int(NOW.timestamp()))
    # Window 2 recovers after one retry; window 3's access error is not retried.
    assert error.value.code == "us_access_denied" and len(calls) == 4


def test_fetch_stops_where_yahoo_history_starts(monkeypatch):
    calls = []
    # Eleven one-year windows of data, then Yahoo has nothing older.
    history = days(11 * 250)

    def fake(symbol, **kwargs):
        calls.append(1)
        index = len(calls) - 1
        if index >= 11:
            raise DataSourceError("hidden", code="us_unavailable")
        chunk = history[len(history) - (index + 1) * 250 : len(history) - index * 250]
        return [{"date": d, "close": 100.0} for d in chunk], {}

    monkeypatch.setattr(plan_data, "yahoo_data", fake)
    result = plan_data.fetch_history(int(NOW.timestamp()))
    assert [p["date"] for p in result] == history
    assert len(calls) == 11 + len(plan_data.RETRY_DELAYS) + 1  # Retried, then stopped.


def test_fetch_rejects_a_history_that_ends_too_soon(monkeypatch):
    calls = []

    def fake(symbol, **kwargs):
        calls.append(1)
        if len(calls) > 2:
            raise DataSourceError("hidden", code="us_unavailable")
        return points(), {}

    monkeypatch.setattr(plan_data, "yahoo_data", fake)
    with pytest.raises(DataSourceError):
        plan_data.fetch_history(int(NOW.timestamp()))


def test_refresh_writes_a_valid_file_and_skips_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_data, "yahoo_data", lambda symbol, **_: (points(), {}))
    assert plan_data.refresh(tmp_path, now=NOW)["status"] == "updated"
    raw = (tmp_path / plan_data.FILE_NAME).read_bytes()
    dates, closes, meta = plan_data.parse(raw, now=NOW)
    assert dates == days(300) and closes[0] == 50.0 and meta["provider"] == "Yahoo Finance"
    later = NOW + timedelta(hours=2)
    assert plan_data.refresh(tmp_path, now=later)["status"] == "unchanged"
    assert (tmp_path / plan_data.FILE_NAME).read_bytes() == raw


def snapshot(**changes):
    payload = json.loads(plan_data.render(points(), NOW))
    payload.update(changes)
    return json.dumps(payload).encode()


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "2330.TW"},
        {"schema_version": 2},
        {"rows": 299},
        {"last_date": "2099-01-01"},
        {"generated_at": "2099-01-01T00:00:00+00:00"},
        {"generated_at": "2026-11-19T07:00:00"},
        {"closes": [["2010-01-05", 1.0], ["2010-01-04", 2.0]]},
        {"source": {"provider": "Elsewhere"}},
    ],
)
def test_parse_rejects_inconsistent_snapshots(changes):
    with pytest.raises(ValueError):
        plan_data.parse(snapshot(**changes), now=NOW)


def test_load_history_maps_failures_to_bounded_codes(monkeypatch):
    monkeypatch.setattr(plan_data, "_download", lambda: b"not json")
    with pytest.raises(DataSourceError) as error:
        plan_data.load_history()
    assert error.value.code == "auto_csv_invalid_data"
    monkeypatch.setattr(plan_data, "_download", lambda: snapshot())
    dates, closes, _ = plan_data.load_history()
    assert len(dates) == len(closes) == 300
