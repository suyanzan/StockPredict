from copy import deepcopy
from datetime import date

from stockpredict.calendar import calendar
from stockpredict.historical import walk_forward
from stockpredict.model_review import block_interval


def test_model_selection_uses_only_validation_and_purges_overlapping_outcomes():
    dates = calendar("XTAI").sessions_in_range("2025-01-01", "2026-10-30")
    points = [{"date": str(d.date()), "close": 100 + i * 0.1} for i, d in enumerate(dates)]
    report = walk_forward("2303.TW", points, None, date(2026, 7, 1), date(2026, 10, 30))
    reviews = report["model_review"]["results"]
    assert all(r["validation_samples"] >= 20 and r["holdout_samples"] >= 20 for r in reviews)
    assert all(r["validation_last_target"] < r["holdout_start"] for r in reviews)
    first = reviews[0]
    changed = deepcopy(points)
    for p in changed:
        if p["date"] >= first["holdout_start"]:
            p["close"] *= 1.3
    altered = walk_forward("2303.TW", changed, None, date(2026, 7, 1), date(2026, 10, 30))
    other = altered["model_review"]["results"][0]
    assert first["selected_on_validation"] == other["selected_on_validation"]
    assert [c["validation"] for c in first["candidates"]] == [
        c["validation"] for c in other["candidates"]
    ]
    assert not report["model_review"]["production_changed"]


def test_block_interval_has_expected_direction():
    assert block_interval([-5] * 40, 5) == [-5, -5]
    assert block_interval([0] * 40, 1) == [0, 0]
