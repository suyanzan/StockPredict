from copy import deepcopy
from datetime import date, datetime

import pytest

from stockpredict.calendar import date_path, previous_session
from stockpredict.scoreboard import evaluate
from stockpredict.weekly_accuracy import summarize_week

NOW = datetime.fromisoformat("2026-11-15T10:00:00+00:00")


def records(day="2026-11-13", predicted=101, actual=102):
    base = previous_session(date.fromisoformat(day))
    prediction = {
        "id": 1,
        "symbol": "2303.TW",
        "scenario": "taiwan",
        "base_date": base,
        "base_close": 100,
        "created_at": datetime.fromisoformat(day + "T08:00:00+08:00"),
        "snapshot": {
            "history": [{"date": base.isoformat(), "close": 100}],
            "forecast": date_path([{"close": predicted}] * 5, base.isoformat(), "XTAI"),
        },
    }
    actuals = (
        [
            {
                "symbol": "2303.TW",
                "session_date": date.fromisoformat(day),
                "close": actual,
                "observed_at": datetime.fromisoformat(day + "T16:00:00+08:00"),
                "source": "TWSE",
            }
        ]
        if actual is not None
        else []
    )
    return [prediction], actuals


def summary(predictions, actuals, now=NOW):
    return summarize_week(evaluate(predictions, actuals)["predictions"], predictions, actuals, now)


def test_exact_mape_direction_and_same_sample_baseline_not_one_minus_error():
    predictions, actuals = records()
    r = summary(predictions, actuals)
    assert r["sessions"] == ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    group = r["taiwan"]
    assert group["mape"] == pytest.approx(1 / 102 * 100)
    assert group["baseline_mape"] == pytest.approx(2 / 102 * 100)
    assert group["hits"] == group["samples"] == 1
    assert group["expected"] == 15 and group["missing"] == 14
    assert r["adr"]["expected"] == r["adr"]["missing"] == 10
    assert len(r["stocks"]) == 5


def test_zero_samples_and_missing_actual_are_not_zero_error_or_misses():
    predictions, actuals = records(actual=None)
    r = summary(predictions, actuals)["taiwan"]
    assert r["pending"] == 1 and r["missing"] == 14
    assert r["samples"] == r["hits"] == 0
    assert r["mape"] is r["baseline_mape"] is None


def test_flat_is_a_separate_direction():
    p, a = records(predicted=100, actual=100)
    assert summary(p, a)["taiwan"]["hits"] == 1
    p, a = records(predicted=101, actual=100)
    assert summary(p, a)["taiwan"]["hits"] == 0


@pytest.mark.parametrize(
    "fault",
    [
        "late",
        "old_day",
        "wrong_base",
        "future_actual",
        "early_actual",
        "source",
        "duplicate",
        "nan",
        "training",
    ],
)
def test_invalid_records_excluded_instead_of_improving_results(fault):
    predictions, actuals = records()
    p, a = predictions[0], actuals[0]
    if fault == "late":
        p["created_at"] = datetime.fromisoformat("2026-11-13T09:00:00+08:00")
    elif fault == "old_day":
        p["created_at"] = datetime.fromisoformat("2026-11-12T08:00:00+08:00")
    elif fault == "wrong_base":
        p["base_date"] = date(2026, 11, 11)
    elif fault == "future_actual":
        a["observed_at"] = datetime.fromisoformat("2026-11-16T16:00:00+08:00")
    elif fault == "early_actual":
        a["observed_at"] = datetime.fromisoformat("2026-11-13T12:00:00+08:00")
    elif fault == "source":
        a["source"] = "demo"
    elif fault == "duplicate":
        predictions.append(deepcopy(p))
    elif fault == "nan":
        p["base_close"] = float("nan")
    else:
        p["snapshot"]["history"][-1]["date"] = "2026-11-13"
    result = summary(predictions, actuals)["taiwan"]
    assert result["samples"] == 0 and result["excluded"] == 1
    assert result["missing"] == 14


def test_week_rolls_only_after_publication_gate_and_skips_exchange_holidays():
    p, a = records()
    before = summary(p, a, datetime.fromisoformat("2026-11-16T14:00:00+08:00"))
    after = summary(p, a, datetime.fromisoformat("2026-11-16T16:00:00+08:00"))
    assert before["sessions"][-1] == "2026-11-13"
    assert after["sessions"] == [
        "2026-11-10",
        "2026-11-11",
        "2026-11-12",
        "2026-11-13",
        "2026-11-16",
    ]
    holiday = summary([], [], datetime.fromisoformat("2026-10-12T16:00:00+08:00"))
    assert "2026-10-09" not in holiday["sessions"]


def test_adr_research_and_five_day_results_do_not_enter_primary_summary():
    p, a = records()
    p[0]["scenario"] = "adr"
    r = summary(p, a)
    assert r["taiwan"]["samples"] == 0 and r["adr"]["samples"] == 1
    p, a = records("2026-11-03")
    a[0]["session_date"] = date(2026, 11, 9)
    a[0]["observed_at"] = datetime.fromisoformat("2026-11-09T16:00:00+08:00")
    r = summary(p, a)
    assert r["taiwan"]["samples"] == 0
