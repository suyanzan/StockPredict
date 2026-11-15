"""Audit the fixed V1.1 observation window from public read-only API snapshots."""

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from stockpredict.calendar import available_at, date_path, is_session, opens_at, previous_session

ORIGINS = ("2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16")
REQUIRED = (
    ("2303.TW", "taiwan"),
    ("2303.TW", "adr"),
    ("2330.TW", "taiwan"),
    ("2330.TW", "adr"),
    ("2308.TW", "taiwan"),
)


def instant(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Evidence timestamps must include a timezone")
    return result


def audit_window(scoreboard, details, now=None):
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("Audit clock must include a timezone")
    if scoreboard.get("status") != "ready":
        return {"status": "unavailable", "observed_at": now.isoformat(), "days": []}
    rows = scoreboard.get("predictions", [])
    detail_map = {d["id"]: d for d in details}
    days = []
    actual_values = {}
    for origin in ORIGINS:
        day = date.fromisoformat(origin)
        path = [p["date"] for p in date_path([{}] * 5, previous_session(day).isoformat(), "XTAI")]
        selected = [r for r in rows if r["origin_date"] == origin]
        counts = Counter((r["symbol"], r["scenario"], r["horizon"]) for r in selected)
        duplicates = [list(key) for key, count in counts.items() if count > 1]
        missing, issues, captures, commits, observations = [], [], [], set(), []
        for symbol, scenario in REQUIRED:
            pair = [r for r in selected if (r["symbol"], r["scenario"]) == (symbol, scenario)]
            if not pair:
                missing.append({"symbol": symbol, "scenario": scenario})
                continue
            if {r["horizon"] for r in pair} != {1, 5} or len({r["id"] for r in pair}) != 1:
                issues.append(f"{symbol}:{scenario}:horizon_identity")
                continue
            record = pair[0]
            created = instant(record["created_at"])
            if (
                created >= opens_at(day)
                or created.astimezone(ZoneInfo("Asia/Taipei")).date() != day
            ):
                issues.append(f"{symbol}:{scenario}:capture_time")
            captures.append(
                {"symbol": symbol, "scenario": scenario, "created_at": created.isoformat()}
            )
            detail = detail_map.get(record["id"])
            if not detail:
                issues.append(f"{symbol}:{scenario}:detail_not_verified")
                continue
            commits.add((detail.get("engine_manifest") or {}).get("build_commit", "unknown"))
            if (
                detail["origin_date"] != origin
                or detail["symbol"] != symbol
                or detail["scenario"] != scenario
                or detail["base_date"] != previous_session(day).isoformat()
                or detail.get("training", {}).get("end") != detail["base_date"]
                or [p["target_date"] for p in detail["forecast"]] != path
            ):
                issues.append(f"{symbol}:{scenario}:date_alignment")
            for point in detail["forecast"]:
                if point["actual_close"] is not None:
                    observed = instant(point["observed_at"])
                    gate = available_at(date.fromisoformat(point["target_date"]))
                    if point["actual_close"] <= 0 or observed < gate or observed > now:
                        issues.append(f"{symbol}:{scenario}:actual_publication")
                    key = (symbol, point["target_date"])
                    if key in actual_values and actual_values[key] != point["actual_close"]:
                        issues.append(f"{symbol}:{scenario}:actual_conflict")
                    actual_values[key] = point["actual_close"]
                    if point["target_date"] == origin:
                        observations.append(observed)
            for row in pair:
                if row["target_date"] != path[row["horizon"] - 1]:
                    issues.append(f"{symbol}:{scenario}:score_date")
        capture_due = now >= opens_at(day)
        fifth_due = now >= available_at(date.fromisoformat(path[-1]))
        day1 = sum(r["horizon"] == 1 and r["status"] == "scored" for r in selected)
        day5 = sum(r["horizon"] == 5 and r["status"] == "scored" for r in selected)
        days.append(
            {
                "origin_date": origin,
                "is_session": is_session(day),
                "capture_status": "pending"
                if not capture_due
                else "issues"
                if missing or issues or duplicates
                else "verified",
                "expected_scenarios": len(REQUIRED),
                "captured_scenarios": len(captures),
                "missing_scenarios": missing if capture_due else [],
                "duplicates": duplicates,
                "issues": issues,
                "captures": captures,
                "build_commits": sorted(commits),
                "day1_scored": day1,
                "day1_close_timely": (
                    len(observations) == len(REQUIRED)
                    and max(observations) <= available_at(day) + timedelta(minutes=75)
                    if observations
                    else None
                ),
                "day5_target": path[-1],
                "day5_available_after": available_at(date.fromisoformat(path[-1])).isoformat(),
                "day5_status": "pending"
                if not fifth_due
                else "verified"
                if day5 == len(REQUIRED) and not issues and not duplicates
                else "pending_collection"
                if now < available_at(date.fromisoformat(path[-1])) + timedelta(minutes=75)
                else "issues",
                "day5_scored": day5,
            }
        )
    return {
        "status": "pending"
        if any(d["day5_status"].startswith("pending") for d in days)
        else "review_required",
        "observed_at": now.isoformat(),
        "days": days,
        "same_version_five_day_pass": False,
        "notification_delivery": "not_verified",
        "scope": (
            "Public API records; database constraints and external notification delivery "
            "need independent evidence. Version acceptance is never inferred from commit IDs."
        ),
    }


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scoreboard", required=True)
    parser.add_argument("--details", required=True)
    parser.add_argument("--now")
    args = parser.parse_args()
    report = audit_window(
        json.loads(Path(args.scoreboard).read_text()),
        json.loads(Path(args.details).read_text()),
        instant(args.now) if args.now else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
