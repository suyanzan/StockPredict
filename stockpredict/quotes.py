"""Read-only daily quotes using the existing bounded TWSE source."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from stockpredict.calendar import is_session, latest_published, previous_session
from stockpredict.data import DataSourceError
from stockpredict.twse import normalize_twse_symbol, twse_data

router = APIRouter()


def taiwan_quote(symbol, now=None):
    now = now or datetime.now(timezone.utc)
    expected = latest_published(now, "XTAI")
    points, metadata = twse_data(symbol)
    closes = {
        date.fromisoformat(p["date"]): p["close"]
        for p in points
        if date.fromisoformat(p["date"]) <= expected and is_session(date.fromisoformat(p["date"]))
    }
    if not closes:
        raise DataSourceError("No publishable daily close")
    day = max(closes)
    close = closes[day]
    prior_day = previous_session(day)
    prior = closes.get(prior_day)
    change = None if prior is None else close - prior
    return {
        "status": "ready",
        "symbol": symbol,
        "name": metadata.get("name", symbol),
        "source": "twse",
        "currency": "TWD",
        "session_date": day.isoformat(),
        "close": close,
        "previous_session_date": prior_day.isoformat() if prior is not None else None,
        "previous_close": prior,
        "day_change": change,
        "day_change_pct": None if prior is None else change / prior * 100,
        "expected_session_date": expected.isoformat(),
        "fresh": day == expected,
        "checked_at": now.isoformat(),
    }


@router.get("/api/quotes/taiwan")
def quote(symbol: str = Query(min_length=1, max_length=20)):
    try:
        symbol = normalize_twse_symbol(symbol)
    except ValueError:
        return JSONResponse(status_code=422, content={"reason": "invalid_twse_symbol"})
    try:
        return taiwan_quote(symbol)
    except DataSourceError:
        return JSONResponse(status_code=503, content={"reason": "quote_unavailable"})
