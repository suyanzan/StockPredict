from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from stockpredict.acceptance import REQUIRED, audit_window
from stockpredict.calendar import available_at, date_path, previous_session

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)


def evidence():
    rows, details = [], []
    for id, (symbol, scenario) in enumerate(REQUIRED, 1):
        base = previous_session(date(2026, 11, 13)).isoformat()
        path = date_path([{}] * 5, base, "XTAI")
        for h in (1, 5):
            rows.append(
                {
                    "id": id,
                    "symbol": symbol,
                    "scenario": scenario,
                    "origin_date": "2026-11-13",
                    "created_at": "2026-11-13T00:11:00+00:00",
                    "horizon": h,
                    "target_date": path[h - 1]["date"],
                    "status": "scored" if h == 1 else "pending",
                }
            )
        details.append(
            {
                "id": id,
                "symbol": symbol,
                "scenario": scenario,
                "origin_date": "2026-11-13",
                "base_date": base,
                "training": {"end": base},
                "forecast": [
                    {
                        "target_date": p["date"],
                        "actual_close": 100 if i == 0 else None,
                        "observed_at": (
                            available_at(date(2026, 11, 13)) + timedelta(minutes=31)
                        ).isoformat()
                        if i == 0
                        else None,
                    }
                    for i, p in enumerate(path)
                ],
            }
        )
    return {"status": "ready", "predictions": rows}, details


def test_future_origin_and_unmatured_day5_never_pass():
    scores, details = evidence()
    report = audit_window(scores, details, NOW)
    day = report["days"][3]
    assert day["capture_status"] == "verified"
    assert day["day1_close_timely"] is True
    assert day["day5_status"] == "pending"
    assert day["day5_target"] == "2026-11-19"
    assert report["days"][4]["capture_status"] == "pending"
    assert report["status"] == "pending"
    assert report["same_version_five_day_pass"] is False


@pytest.mark.parametrize(
    "fault", ["duplicate", "late", "wrong_date", "premature", "conflicting_actual"]
)
def test_archive_and_actual_evidence_faults_are_detected(fault):
    scores, details = evidence()
    if fault == "duplicate":
        scores["predictions"].append(deepcopy(scores["predictions"][0]))
    elif fault == "late":
        scores["predictions"][0]["created_at"] = "2026-11-13T01:01:00+00:00"
    elif fault == "wrong_date":
        details[0]["forecast"][0]["target_date"] = "2026-11-12"
    elif fault == "premature":
        details[0]["forecast"][0]["observed_at"] = "2026-11-13T05:00:00+00:00"
    else:
        details[1]["forecast"][0]["actual_close"] = 101
    assert audit_window(scores, details, NOW)["days"][3]["capture_status"] == "issues"


def test_collection_grace_and_missing_details_do_not_pass():
    scores, details = evidence()
    now = available_at(date(2026, 11, 19)) + timedelta(minutes=5)
    assert audit_window(scores, details, now)["days"][3]["day5_status"] == "pending_collection"
    now += timedelta(minutes=80)
    assert audit_window(scores, details, now)["days"][3]["day5_status"] == "issues"
    assert audit_window(scores, [], NOW)["days"][3]["capture_status"] == "issues"


def test_unavailable_storage_and_naive_clock_cannot_pass():
    assert audit_window({"status": "unavailable"}, [], NOW)["status"] == "unavailable"
    with pytest.raises(ValueError):
        audit_window({"status": "ready"}, [], datetime(2026, 11, 15))
