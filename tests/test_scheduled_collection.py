from datetime import datetime

import pytest

from stockpredict.scheduled_collection import scheduled_phase


@pytest.mark.parametrize("minute", [10, 30, 50])
def test_preopen_ticks(minute):
    now = datetime.fromisoformat(f"2026-11-11T00:{minute}:00+00:00")
    assert scheduled_phase(now) == "preopen"


@pytest.mark.parametrize("hour", [7, 9, 13])
def test_afternoon_intersections(hour):
    for minute in (10, 30, 50):
        now = datetime.fromisoformat(f"2026-11-11T{hour:02}:{minute}:00+00:00")
        assert scheduled_phase(now) == ("close" if minute == 30 else None)


def test_weekend_holiday_and_late_tick_do_not_capture():
    for value in (
        "2026-11-14T00:10:00+00:00",
        "2026-01-01T00:30:00+00:00",
        "2026-11-11T01:10:00+00:00",
    ):
        assert scheduled_phase(datetime.fromisoformat(value)) is None


def test_delayed_startup_keeps_collection_in_its_window():
    assert scheduled_phase(datetime.fromisoformat("2026-11-11T00:13:00+00:00")) == "preopen"
    assert scheduled_phase(datetime.fromisoformat("2026-11-11T07:34:00+00:00")) == "close"


def test_idle_tick_does_not_connect_or_download(monkeypatch):
    from stockpredict import scheduled_collection, scoreboard

    monkeypatch.setattr(scheduled_collection, "scheduled_phase", lambda now: None)

    def forbidden(**kwargs):
        pytest.fail("An idle tick must not run collection")

    monkeypatch.setattr(scoreboard, "run_job", forbidden)
    assert scheduled_collection.main() == 0


@pytest.mark.parametrize("failed", [False, True])
def test_collection_failure_propagates_to_exit_status(monkeypatch, failed):
    from stockpredict import scheduled_collection, scoreboard

    monkeypatch.setattr(scheduled_collection, "scheduled_phase", lambda now: "close")

    def run_job(*, phase):
        assert phase == "close"
        return [{"symbol": "2303.TW", "status": "unavailable" if failed else "current"}]

    monkeypatch.setattr(scoreboard, "run_job", run_job)
    assert scheduled_collection.main() == int(failed)
