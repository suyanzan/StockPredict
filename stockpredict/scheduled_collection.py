"""Route shared Render cron ticks without collecting at extra cron intersections."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from stockpredict.calendar import is_session


def scheduled_phase(now):
    local = now.astimezone(ZoneInfo("Asia/Taipei"))
    if not is_session(local.date()):
        return None
    # Allow delayed container startup while retaining the 09:00 capture gate.
    if local.hour == 8 and local.minute >= 10:
        return "preopen"
    if local.hour in (15, 17, 21) and 30 <= local.minute < 50:
        return "close"
    return None


def main():
    import json

    from stockpredict.monitoring import collection_failures
    from stockpredict.scoreboard import run_job

    phase = scheduled_phase(datetime.now(timezone.utc))
    if phase is None:
        print("No collection scheduled for this tick; exiting without upstream requests.")
        return 0
    print(f"Starting scheduled {phase} collection", flush=True)
    checks = run_job(phase=phase)
    print(json.dumps(checks, ensure_ascii=False))
    return 1 if collection_failures(checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
