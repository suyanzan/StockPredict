"""Provider-reported corporate actions. Markers never rewrite raw prices or scores."""

import json
import math
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime, timezone
from threading import Lock
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from stockpredict.calendar import previous_session

router = APIRouter()
_CACHE = OrderedDict()
_LOCK = Lock()


def unavailable(reason="event_source_unavailable", *, now=None):
    return {
        "status": "unavailable",
        "reason": reason,
        "source": "Yahoo Finance",
        "checked_at": (now or datetime.now(timezone.utc)).isoformat(),
        "events": [],
        "coverage_start": None,
        "coverage_end": None,
        "absence_is_not_proof": True,
    }


def parse_event_payload(result, *, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        zone = ZoneInfo(result["meta"]["exchangeTimezoneName"])
        currency = result["meta"].get("currency", "")
        if not isinstance(currency, str) or len(currency) > 10:
            raise ValueError("Invalid currency")
        stamps = result["timestamp"]
        if not stamps or not all(type(v) is int for v in stamps):
            raise ValueError("Invalid coverage")
        coverage = [datetime.fromtimestamp(t, zone).date() for t in stamps]
        if min(coverage) > now.astimezone(zone).date():
            raise ValueError("Coverage is entirely in the future")
        raw = result.get("events", {})
        if not isinstance(raw, dict):
            raise ValueError("Invalid events")
        events = []
        for name, kind in (("dividends", "dividend"), ("splits", "split")):
            group = raw.get(name, {})
            if not isinstance(group, dict):
                raise ValueError("Invalid event group")
            for item in group.values():
                stamp = item["date"]
                if type(stamp) is not int:
                    raise ValueError("Invalid event date")
                day = datetime.fromtimestamp(stamp, zone).date()
                if not min(coverage) <= day <= min(max(coverage), now.astimezone(zone).date()):
                    raise ValueError("Event outside observed coverage")
                event = {
                    "date": str(day),
                    "type": kind,
                    "source": "Yahoo Finance",
                    "status": "provider_reported",
                }
                if kind == "dividend":
                    amount = item["amount"]
                    if (
                        isinstance(amount, bool)
                        or not math.isfinite(float(amount))
                        or float(amount) <= 0
                    ):
                        raise ValueError("Invalid dividend")
                    event.update(amount=float(amount), currency=currency)
                else:
                    numerator, denominator = item.get("numerator"), item.get("denominator")
                    if numerator is None or denominator is None:
                        numerator, denominator = item["splitRatio"].split(":")
                    values = (numerator, denominator)
                    if any(
                        isinstance(v, bool) or not math.isfinite(float(v)) or float(v) <= 0
                        for v in values
                    ):
                        raise ValueError("Invalid split")
                    ratio = float(numerator) / float(denominator)
                    if not math.isfinite(ratio) or ratio <= 0:
                        raise ValueError("Invalid split ratio")
                    event.update(
                        numerator=float(numerator),
                        denominator=float(denominator),
                        ratio=ratio,
                    )
                events.append(event)
        return {
            "status": "ready",
            "reason": None,
            "source": "Yahoo Finance",
            "checked_at": now.isoformat(),
            "coverage_start": str(min(coverage)),
            "coverage_end": str(min(max(coverage), now.astimezone(zone).date())),
            "events": sorted(events, key=lambda e: (e["date"], e["type"])),
            "absence_is_not_proof": True,
        }
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return unavailable("invalid_event_data", now=now)


def actions_for(symbol):
    from stockpredict.data import normalize_symbol

    symbol = normalize_symbol(symbol)
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(symbol)
        if cached and cached[0] > now:
            return deepcopy(cached[1])
    try:
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
            "?range=2y&interval=1d&events=div%2Csplits"
        )
        with urlopen(
            Request(url, headers={"User-Agent": "StockPredict/0.1"}), timeout=10
        ) as response:
            payload = json.loads(response.read(5_000_001))
        result = parse_event_payload(payload["chart"]["result"][0])
    except Exception:
        result = unavailable()
    with _LOCK:
        _CACHE[symbol] = (time.monotonic() + (3600 if result["status"] == "ready" else 300), result)
        while len(_CACHE) > 16:
            _CACHE.popitem(last=False)
    return deepcopy(result)


def annotate_report(report, actions):
    report = deepcopy(report)
    report["corporate_actions"] = deepcopy(actions)
    for row in report["predictions"]:
        base = str(previous_session(date.fromisoformat(row["origin_date"])))
        row["corporate_actions"] = [
            e for e in actions["events"] if base < e["date"] <= row["target_date"]
        ]
        row["corporate_action_status"] = (
            "unavailable"
            if actions["status"] != "ready"
            else "source_reported"
            if actions["coverage_start"] <= base and row["target_date"] <= actions["coverage_end"]
            else "outside_source_coverage"
        )
    return report


@router.get("/api/corporate-actions")
def corporate_actions(symbol: str = "2330.TW"):
    try:
        result = actions_for(symbol)
        return {"symbol": symbol, **result}
    except ValueError:
        return JSONResponse(status_code=422, content={"reason": "invalid_symbol"})
