"""Read-only schedule/deadline monitoring with no credentials in public diagnostics."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from stockpredict.calendar import available_at, is_session, opens_at, previous_session

TAIPEI = ZoneInfo("Asia/Taipei")
SLOTS = ((8, 10), (8, 30), (8, 50), (15, 30), (17, 30), (21, 30))


def _instant(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def due_schedule(now):
    """Latest planned run whose 45-minute grace period has elapsed."""
    day = now.astimezone(TAIPEI).date()
    for offset in range(10):
        candidate = day - timedelta(days=offset)
        if not is_session(candidate):
            continue
        for hour, minute in reversed(SLOTS):
            slot = datetime.combine(candidate, time(hour, minute), TAIPEI)
            if slot + timedelta(minutes=45) <= now:
                return slot
    return None


def health_alerts(rows, last_check, started_at, *, now=None):
    now = now or datetime.now(timezone.utc)
    if not last_check:
        return [{"code": "no_checks", "severity": "warning"}]
    alerts = []
    due = due_schedule(now)
    if due and _instant(last_check["checked_at"]) < due:
        alerts.append(
            {"code": "schedule_stale", "severity": "critical", "expected_run": due.isoformat()}
        )
    day = now.astimezone(TAIPEI).date()
    while not is_session(day) or now < opens_at(day):
        day = previous_session(day)
    # Do not demand forecasts from before the collection service first existed.
    if (
        started_at
        and _instant(started_at) <= opens_at(day)
        and now >= opens_at(day) + timedelta(minutes=15)
    ):
        from stockpredict.scoreboard import SYMBOLS, scenarios_for

        for symbol in SYMBOLS:
            if symbol == "2308.TW" and not any(
                c.get("symbol") == symbol for c in last_check.get("details", [])
            ):
                continue
            for scenario in scenarios_for(symbol):
                if not any(
                    r["symbol"] == symbol
                    and r["scenario"] == scenario
                    and r["origin_date"] == str(day)
                    for r in rows
                ):
                    alerts.append(
                        {
                            "code": "preopen_missing",
                            "symbol": symbol,
                            "scenario": scenario,
                            "session_date": str(day),
                            "severity": "critical" if scenario == "taiwan" else "warning",
                        }
                    )
    overdue = [
        r
        for r in rows
        if r["status"] == "pending"
        and available_at(datetime.fromisoformat(r["target_date"]).date()) + timedelta(minutes=75)
        <= now
    ]
    if overdue:
        alerts.append(
            {
                "code": "actual_close_missing",
                "severity": "warning",
                "count": len(overdue),
                "oldest_target": min(r["target_date"] for r in overdue),
            }
        )
    for check in last_check.get("details", []):
        errors = scenario_failures(check)
        if check.get("status") in ("unavailable", "missing") or errors:
            alerts.append(
                {
                    "code": "source_unavailable",
                    "severity": "critical",
                    "symbol": check["symbol"],
                    "reason": check.get("reason")
                    or next(iter(errors.values()), "source_unavailable"),
                    "scenario_errors": errors,
                }
            )
    return alerts


def scenario_failures(check):
    # Expected calendar/availability waits are not provider faults.
    failures = {
        "source_unavailable",
        "source_changed_during_capture",
        "invalid_factor_data",
        "incomplete_history",
        "stale_history",
        "missing_factors",
    }
    return {
        scenario: value
        for scenario in ("taiwan", "adr")
        if isinstance(value := check.get(scenario), str)
        and (
            value in failures
            or value.startswith(("us_", "auto_csv_"))
            and value != "us_session_not_closed"
        )
    }


def scenario_failure(check):
    return bool(scenario_failures(check))


def collection_failures(checks):
    return [
        c["symbol"]
        for c in checks
        if c.get("status") in ("unavailable", "missing")
        or scenario_failure(c)
        or c.get("preopen_missing", False)
    ]


def poll(url):
    """Used by an independent Actions job, so a missing writer can still be detected."""
    import json
    from urllib.request import Request, urlopen

    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=90) as response:
        report = json.loads(response.read(5_000_001))
    if report.get("status") != "ready" or "alerts" not in report:
        raise ValueError("Scoreboard monitoring is not available; check deployment and storage")
    return report["alerts"]


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    try:
        alerts = poll(args.url)
        print(json.dumps(alerts, ensure_ascii=False))
        failed = any(
            a["severity"] == "critical" or a["code"] in ("no_checks", "actual_close_missing")
            for a in alerts
        )
        if failed:
            print(
                "::error::Scoreboard collection or closing-price deadline missed; inspect dashboard"
            )
        sys.exit(1 if failed else 0)
    except Exception:
        print(
            "::error::Cannot read scoreboard health; "
            "check site deployment and database configuration"
        )
        sys.exit(1)
