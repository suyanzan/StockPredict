from stockpredict.comparison import paired_comparison


def row(origin, scenario, error, *, status="scored", actual=100, horizon=1):
    return dict(
        symbol="2303.TW",
        origin_date=origin,
        target_date=origin,
        scenario=scenario,
        horizon=horizon,
        status=status,
        base_close=90,
        actual_close=actual,
        absolute_error=abs(error),
        absolute_error_pct=abs(error),
        direction_hit=error >= 0,
    )


def test_unmatched_dates_and_pending_cannot_improve_paired_scores():
    rows = [
        row("2026-10-01", "taiwan", 10),
        row("2026-10-01", "adr", 5),
        row("2026-10-02", "taiwan", 100),
        row("2026-10-03", "adr", 0),
        row("2026-10-04", "taiwan", 0, status="pending"),
        row("2026-10-04", "adr", 0, status="pending"),
    ]
    first, fifth = paired_comparison(rows)
    assert first["paired_samples"] == 1 and first["adr_coverage"] == 0.5
    assert first["taiwan"]["mae"] == 10 and first["adr"]["mae"] == 5
    assert first["mae_improvement_pct"] == 50
    assert fifth["paired_samples"] == 0 and fifth["taiwan"]["mae"] is None


def test_different_origins_or_actuals_do_not_pair():
    a, b = row("2026-10-01", "taiwan", 5), row("2026-10-02", "adr", 5)
    b["target_date"] = a["target_date"]
    assert paired_comparison([a, b])[0]["paired_samples"] == 0
    b["origin_date"] = a["origin_date"]
    b["actual_close"] = 200
    assert paired_comparison([a, b])[0]["paired_samples"] == 0
