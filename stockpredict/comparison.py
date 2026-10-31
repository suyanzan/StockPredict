"""Compare scenarios only on identical forecast origins, targets and horizons."""


def metrics(rows):
    n = len(rows)
    return {
        "samples": n,
        "mae": sum(r["absolute_error"] for r in rows) / n if n else None,
        "mape": sum(r["absolute_error_pct"] for r in rows) / n if n else None,
        "direction_accuracy": sum(r["direction_hit"] for r in rows) / n if n else None,
        "baseline_mae": sum(abs(r["base_close"] - r["actual_close"]) for r in rows) / n
        if n
        else None,
    }


def paired_comparison(rows):
    result = []
    for symbol in sorted({r["symbol"] for r in rows}):
        for horizon in (1, 5):
            groups = {}
            for scenario in ("taiwan", "adr"):
                groups[scenario] = {
                    (r["origin_date"], r["target_date"]): r
                    for r in rows
                    if r["symbol"] == symbol
                    and r["horizon"] == horizon
                    and r["scenario"] == scenario
                    and r["status"] == "scored"
                }
            common = sorted(groups["taiwan"].keys() & groups["adr"].keys())
            # Different baselines/actuals cannot be treated as a matched experiment.
            common = [
                key
                for key in common
                if all(
                    groups["taiwan"][key][field] == groups["adr"][key][field]
                    for field in ("base_close", "actual_close")
                )
            ]
            matched = {s: metrics([groups[s][key] for key in common]) for s in groups}
            base, adr = matched["taiwan"]["mae"], matched["adr"]["mae"]
            result.append(
                {
                    "symbol": symbol,
                    "horizon": horizon,
                    "paired_samples": len(common),
                    "taiwan_scored": len(groups["taiwan"]),
                    "adr_scored": len(groups["adr"]),
                    "adr_coverage": len(common) / len(groups["taiwan"])
                    if groups["taiwan"]
                    else None,
                    "unpaired_taiwan": len(groups["taiwan"]) - len(common),
                    "dates": [{"origin_date": k[0], "target_date": k[1]} for k in common],
                    "taiwan": matched["taiwan"],
                    "adr": matched["adr"],
                    "mae_improvement_pct": (base - adr) / base * 100 if base else None,
                }
            )
    return result
