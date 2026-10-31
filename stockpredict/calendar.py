"""Exchange sessions and conservative publication gates (never weekday fallback)."""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

import exchange_calendars as xc


@lru_cache(maxsize=2)
def calendar(market: str):
    if market not in ("XTAI", "XNYS"):
        raise ValueError("Unsupported exchange")
    return xc.get_calendar(market, start="2000-01-01", end="2035-12-31")


def is_session(day: date, market: str = "XTAI") -> bool:
    return bool(calendar(market).is_session(day.isoformat()))


def next_session(day: date, market: str = "XTAI") -> date:
    return (
        calendar(market)
        .date_to_session((day + timedelta(days=1)).isoformat(), direction="next")
        .date()
    )


def previous_session(day: date, market: str = "XTAI") -> date:
    return (
        calendar(market)
        .date_to_session((day - timedelta(days=1)).isoformat(), direction="previous")
        .date()
    )


def opens_at(day: date, market: str = "XTAI") -> datetime:
    return calendar(market).session_open(day.isoformat()).to_pydatetime()


def available_at(day: date, market: str = "XTAI") -> datetime:
    delay = timedelta(minutes=90 if market == "XTAI" else 15)
    return calendar(market).session_close(day.isoformat()).to_pydatetime() + delay


def latest_published(
    now: datetime, market: str = "XTAI", publication_delay: int | None = None
) -> date:
    c = calendar(market)
    local = now.astimezone(c.tz).date()
    day = c.date_to_session(local.isoformat(), direction="previous").date()
    threshold = available_at(day, market)
    if publication_delay is not None:
        threshold += timedelta(minutes=publication_delay - (90 if market == "XTAI" else 15))
    return previous_session(day, market) if now < threshold else day


def date_path(path: list[dict], after: str, market: str) -> list[dict]:
    day = date.fromisoformat(after)
    result = []
    for point in path:
        day = next_session(day, market)
        result.append({**point, "date": day.isoformat()})
    return result


def data_status(
    points: list[dict],
    market: str,
    now: datetime | None = None,
    publication_delay: int | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    expected = latest_published(now, market, publication_delay).isoformat()
    actual = points[-1]["date"] if points else None
    return {
        "exchange": market,
        "checked_at": now.isoformat(),
        "session_date": actual,
        "expected_session_date": expected,
        "status": "current" if actual == expected else "missing",
        "reason": None if actual == expected else "missing_expected_session",
        "calendar": "exchange_calendars",
        "calendar_through": "2035-12-31",
    }
