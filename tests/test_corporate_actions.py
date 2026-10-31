from datetime import date, datetime
from urllib.error import URLError

import pytest

import stockpredict.corporate_actions as actions
from stockpredict.calendar import calendar
from stockpredict.historical import walk_forward


def payload():
    def stamp(day):
        return int(datetime.fromisoformat(day + "T09:00:00+08:00").timestamp())

    return {
        "meta": {"exchangeTimezoneName": "Asia/Taipei", "currency": "TWD"},
        "timestamp": [stamp(d) for d in ("2026-10-01", "2026-10-15", "2026-10-30")],
        "events": {
            "dividends": {"d": {"date": stamp("2026-10-15"), "amount": 2}},
            "splits": {"s": {"date": stamp("2026-10-30"), "splitRatio": "2:1"}},
        },
    }


def test_events_keep_local_dates_and_provider_status():
    report = actions.parse_event_payload(
        payload(), now=datetime.fromisoformat("2026-10-31T12:00:00+08:00")
    )
    assert report["status"] == "ready"
    assert [(e["date"], e["type"]) for e in report["events"]] == [
        ("2026-10-15", "dividend"),
        ("2026-10-30", "split"),
    ]
    assert all(e["status"] == "provider_reported" for e in report["events"])
    assert report["events"][1]["ratio"] == 2 and report["absence_is_not_proof"]


@pytest.mark.parametrize("value", [0, -1, float("nan"), True])
def test_invalid_event_data_cannot_claim_no_events(value):
    raw = payload()
    raw["events"]["dividends"]["d"]["amount"] = value
    report = actions.parse_event_payload(raw)
    assert report["status"] == "unavailable" and report["reason"] == "invalid_event_data"


def test_upstream_event_failure_is_explicit_and_not_ready_empty(monkeypatch):
    actions._CACHE.clear()

    def fail(*a, **kw):
        raise URLError("Unavailable")

    monkeypatch.setattr(actions, "urlopen", fail)
    assert actions.actions_for("2330.TW")["status"] == "unavailable"
    actions._CACHE.clear()


def test_event_annotations_never_change_forecasts_scores_or_pairing():
    points = [
        {"date": str(d.date()), "close": 100 + i * 0.1}
        for i, d in enumerate(calendar("XTAI").sessions_in_range("2026-03-01", "2026-10-30"))
    ]
    base = walk_forward("2303.TW", points, None, date(2026, 10, 1), date(2026, 10, 30))
    result = actions.annotate_report(base, actions.parse_event_payload(payload()))
    assert result["summary"] == base["summary"] and result["comparison"] == base["comparison"]
    assert [p["predicted_close"] for p in result["predictions"]] == [
        p["predicted_close"] for p in base["predictions"]
    ]
    assert any(p["corporate_actions"] for p in result["predictions"])
    assert all("corporate_actions" not in p for p in base["predictions"])
