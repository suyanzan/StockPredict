"""Fixed training-window candidates selected on validation, then tested out of time."""

import numpy as np

from stockpredict.comparison import metrics
from stockpredict.forecast import forecast_path

CANDIDATES = ("previous_close", "expanding_ar5", "ar5_60", "ar5_120")


def error_row(template, predicted):
    actual, base = template["actual_close"], template["base_close"]
    error = predicted - actual
    return {
        **template,
        "absolute_error": abs(error),
        "absolute_error_pct": abs(error) / actual * 100,
        "direction_hit": np.sign(predicted - base) == np.sign(actual - base),
    }


def block_interval(differences, block):
    """Circular block bootstrap; blocks of five preserve multi-day overlap."""
    values = np.asarray(differences)
    rng = np.random.default_rng(20261031)
    starts = rng.integers(0, len(values), size=(1000, (len(values) + block - 1) // block))
    indices = ((starts[..., None] + np.arange(block)) % len(values)).reshape(1000, -1)
    bounds = np.quantile(values[indices[:, : len(values)]].mean(axis=1), [0.025, 0.975])
    return [float(v) for v in bounds]


def review_models(points, rows):
    scored = [r for r in rows if r["scenario"] == "taiwan" and r["status"] == "scored"]
    paths = {}
    for origin in sorted({r["origin_date"] for r in scored}):
        prefix = [p for p in points if p["date"] < origin]
        paths[origin] = {n: forecast_path(prefix[-n:], 5) for n in (60, 120) if len(prefix) >= n}
    reviews = []
    for horizon in (1, 5):
        group = sorted(
            [r for r in scored if r["horizon"] == horizon and 120 in paths[r["origin_date"]]],
            key=lambda r: r["origin_date"],
        )
        split = max(0, len(group) - max(20, (len(group) + 2) // 3))
        test = group[split:]
        test_start = test[0]["origin_date"] if test else None
        # Purge validation outcomes not known before the first holdout decision.
        validation = [r for r in group[:split] if r["target_date"] < test_start]
        item = {
            "horizon": horizon,
            "validation_samples": len(validation),
            "validation_last_target": validation[-1]["target_date"] if validation else None,
            "holdout_samples": len(test),
            "holdout_start": test_start,
            "production_changed": False,
            "candidates": [],
            "recommendation": "insufficient_evidence",
        }
        if len(validation) < 20 or len(test) < 20:
            reviews.append(item)
            continue
        validation_scores, test_scores = {}, {}
        for candidate in CANDIDATES:

            def candidate_row(r):
                if candidate == "previous_close":
                    price = r["base_close"]
                elif candidate == "expanding_ar5":
                    price = r["predicted_close"]
                else:
                    n = 60 if candidate == "ar5_60" else 120
                    price = paths[r["origin_date"]][n][horizon - 1]["close"]
                return error_row(r, price)

            validation_scores[candidate] = [candidate_row(r) for r in validation]
            test_scores[candidate] = [candidate_row(r) for r in test]
            item["candidates"].append(
                {
                    "candidate": candidate,
                    "validation": metrics(validation_scores[candidate]),
                    "holdout": metrics(test_scores[candidate]),
                }
            )
        selected = min(CANDIDATES, key=lambda c: metrics(validation_scores[c])["mae"])
        item["selected_on_validation"] = selected
        selected_metrics = metrics(test_scores[selected])
        intervals = {}
        for reference in ("previous_close", "expanding_ar5"):
            intervals[reference] = block_interval(
                [
                    a["absolute_error"] - b["absolute_error"]
                    for a, b in zip(test_scores[selected], test_scores[reference])
                ],
                horizon,
            )
        item["holdout_mae_delta_95pct"] = intervals
        baseline = metrics(test_scores["previous_close"])["mae"]
        incumbent = metrics(test_scores["expanding_ar5"])["mae"]
        if selected == "previous_close" and intervals["expanding_ar5"][1] < 0:
            item["recommendation"] = "baseline_beats_model"
        elif (
            selected != "expanding_ar5"
            and selected_metrics["mae"] < min(baseline, incumbent) * 0.95
            and all(bounds[1] < 0 for bounds in intervals.values())
        ):
            item["recommendation"] = "candidate_for_prospective_test"
        else:
            item["recommendation"] = "retain_current_pending_evidence"
        reviews.append(item)
    return {
        "method": "fixed_candidates_temporal_validation_then_holdout",
        "minimum_split_samples": 20,
        "improvement_threshold_pct": 5,
        "confidence_method": "1000 circular-block bootstrap resamples; block=horizon",
        "production_changed": False,
        "results": reviews,
    }
