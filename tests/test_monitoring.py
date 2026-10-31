from datetime import datetime

from stockpredict.monitoring import collection_failures, due_schedule, health_alerts


def at(value):
    return datetime.fromisoformat(value + "+08:00")


def test_schedule_grace_and_weekend_calendar():
    assert due_schedule(at("2026-11-02T09:34:59")).isoformat() == "2026-11-02T08:30:00+08:00"
    assert due_schedule(at("2026-11-02T09:35:00")).isoformat() == "2026-11-02T08:50:00+08:00"
    assert due_schedule(at("2026-11-01T12:00:00")).date().isoformat() == "2026-10-30"


def test_no_retroactive_missing_forecasts_before_service_started():
    check = {"checked_at": at("2026-10-31T10:00:00"), "details": []}
    assert not health_alerts([], check, check["checked_at"], now=at("2026-10-31T11:00:00"))


def test_missing_writer_and_preopen_capture_surface_independently():
    check = {"checked_at": at("2026-11-02T08:30:00"), "details": []}
    alerts = health_alerts([], check, at("2026-10-31T10:00:00"), now=at("2026-11-02T09:45:00"))
    assert any(a["code"] == "schedule_stale" for a in alerts)
    assert len([a for a in alerts if a["code"] == "preopen_missing"]) == 4
    assert len([a for a in alerts if a["severity"] == "critical"]) == 3


def test_close_gate_and_schedule_grace_do_not_alert_early():
    row = dict(
        symbol="2303.TW",
        scenario="taiwan",
        origin_date="2026-11-02",
        target_date="2026-11-02",
        status="pending",
    )
    check = {"checked_at": at("2026-11-02T15:30:00"), "details": []}
    before = health_alerts([row], check, at("2026-11-02T10:00:00"), now=at("2026-11-02T16:14:59"))
    after = health_alerts([row], check, at("2026-11-02T10:00:00"), now=at("2026-11-02T16:15:00"))
    assert not any(a["code"] == "actual_close_missing" for a in before)
    assert any(a["code"] == "actual_close_missing" for a in after)


def test_upstream_failures_fail_strict_writer_but_adr_holidays_do_not():
    assert collection_failures([{"symbol": "2303.TW", "status": "unavailable"}]) == ["2303.TW"]
    assert not collection_failures(
        [
            {
                "symbol": "2303.TW",
                "status": "current",
                "taiwan": "saved",
                "adr": "missing_us_sessions",
            }
        ]
    )


def test_independent_monitor_reads_public_health_and_rejects_old_backend(monkeypatch):
    import io
    import urllib.request

    import pytest

    from stockpredict.monitoring import poll

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **kw: io.BytesIO(
            b'{"status":"ready","alerts":[{"code":"schedule_stale","severity":"critical"}]}'
        ),
    )
    assert poll("https://example.test/api/scoreboard")[0]["code"] == "schedule_stale"
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(b'{"status":"ready"}')
    )
    with pytest.raises(ValueError, match="deployment"):
        poll("https://example.test/api/scoreboard")
