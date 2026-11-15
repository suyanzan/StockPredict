"""Read-only recent-session results, separate from model backtests and reliability acceptance."""

from collections import Counter
from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

from stockpredict.calendar import available_at, latest_published, opens_at, previous_session

SYMBOLS = ("2303.TW", "2330.TW", "2308.TW")
PAIRS = [(symbol, "taiwan") for symbol in SYMBOLS] + [(symbol, "adr") for symbol in SYMBOLS[:2]]


def metrics(rows):
    n = len(rows)
    if not n:
        return {"samples": 0, "mape": None, "baseline_mape": None, "hits": 0}
    return {
        "samples": n,
        "mape": sum(abs(r["predicted_close"] - r["actual_close"]) / r["actual_close"] for r in rows)
        / n
        * 100,
        "baseline_mape": sum(
            abs(r["base_close"] - r["actual_close"]) / r["actual_close"] for r in rows
        )
        / n
        * 100,
        "hits": sum(
            ((r["predicted_close"] > r["base_close"]) - (r["predicted_close"] < r["base_close"]))
            == ((r["actual_close"] > r["base_close"]) - (r["actual_close"] < r["base_close"]))
            for r in rows
        ),
    }


def summarize_week(rows, predictions, actuals, now=None):
    now = now or datetime.now(timezone.utc)
    day = latest_published(now)
    sessions = [day]
    for _ in range(4):
        sessions.append(previous_session(sessions[-1]))
    sessions = sorted(sessions)
    days = {d.isoformat(): d for d in sessions}
    selected = [
        r
        for r in rows
        if r["horizon"] == 1 and r["target_date"] in days and (r["symbol"], r["scenario"]) in PAIRS
    ]
    counts = Counter((r["symbol"], r["scenario"], r["target_date"]) for r in selected)
    archives = {p["id"]: p for p in predictions}
    actual_map = {(a["symbol"], str(a["session_date"])): a for a in actuals}
    valid, pending, invalid = [], [], []
    for row in selected:
        try:
            d = days[row["target_date"]]
            created = datetime.fromisoformat(row["created_at"])
            archive = archives[row["id"]]
            if (
                counts[(row["symbol"], row["scenario"], row["target_date"])] != 1
                or row["origin_date"] != row["target_date"]
                or created.utcoffset() is None
                or created >= opens_at(d)
                or created.astimezone(ZoneInfo("Asia/Taipei")).date() != d
                or str(archive["base_date"]) != previous_session(d).isoformat()
                or archive["snapshot"]["history"][-1]["date"] != str(archive["base_date"])
                or any(
                    isinstance(row[k], bool) or not isfinite(row[k]) or row[k] <= 0
                    for k in ("predicted_close", "base_close")
                )
            ):
                raise ValueError("Invalid capture")
            actual = actual_map.get((row["symbol"], row["target_date"]))
            if row["status"] == "pending" and actual is None and row["actual_close"] is None:
                pending.append(row)
                continue
            if (
                row["status"] != "scored"
                or not actual
                or isinstance(row["actual_close"], bool)
                or not isfinite(row["actual_close"])
                or row["actual_close"] <= 0
                or row["actual_close"] != actual["close"]
                or actual["source"] != "TWSE"
                or not available_at(d) <= actual["observed_at"] <= now
            ):
                raise ValueError("Invalid actual")
            valid.append(row)
        except (KeyError, TypeError, ValueError, IndexError):
            invalid.append(row)

    def group(pairs):
        included = [r for r in valid if (r["symbol"], r["scenario"]) in pairs]
        occupied = sum((s, c, d) in counts for s, c in pairs for d in days)
        return {
            **metrics(included),
            "expected": len(days) * len(pairs),
            "missing": len(days) * len(pairs) - occupied,
            "pending": sum((r["symbol"], r["scenario"]) in pairs for r in pending),
            "excluded": sum(
                (s, c) in pairs
                for s, c, d in {(r["symbol"], r["scenario"], r["target_date"]) for r in invalid}
            ),
            "dates": sorted({r["target_date"] for r in included}),
        }

    return {
        "checked_at": now.isoformat(),
        "sessions": [d.isoformat() for d in sessions],
        "scope": "preopen_day1_target_sessions",
        "taiwan": group(PAIRS[:3]),
        "adr": group(PAIRS[3:]),
        "stocks": [
            {"symbol": symbol, "scenario": scenario, **group([(symbol, scenario)])}
            for symbol, scenario in PAIRS
        ],
    }
