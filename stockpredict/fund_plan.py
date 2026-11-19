"""Owner-only 0050 funding plan: historical drawdowns, lump sum vs. monthly
buying, and a rule-based "satellite" that sells into strength.

Every result is a percentage of one unit of capital. The owner's real amounts
and holdings never reach the server; the private page scales results locally.
These are historical simulations, not forecasts or advice.
"""

import hashlib
import hmac
import os
import threading
import time
from datetime import date, datetime, timezone
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse

from stockpredict import plan_data
from stockpredict.community import _origin_check, require_admin
from stockpredict.data import DataSourceError

SYMBOL = "0050.TW"
BUY_FEE = 0.001425
SELL_COST = 0.001425 + 0.001  # Commission plus ETF securities transaction tax.
MONTH = 21  # Trading days per month, for spacing scheduled buys.
START_STEP = 5  # Sample a start date every five trading days.
SATELLITE_SHARES = (0.0, 0.1, 0.2)
CACHE_SECONDS = 1800  # The published snapshot changes at most a few times a day.
FAILURE_SECONDS = 60  # Do not re-download right after a failed read.
SESSION_COOKIE = "sp_plan_owner"
SESSION_SECONDS = 7 * 24 * 3600
SESSION_PATH = "/api/plan"

router = APIRouter()
_cache: dict = {}
_lock = threading.Lock()
_fetch_lock = threading.Lock()  # One snapshot read at a time; others reuse its result.


def _signature(expires: int) -> str:
    key = os.getenv("COMMUNITY_ADMIN_TOKEN", "").encode()
    return hmac.new(key, f"plan-owner:{expires}".encode(), hashlib.sha256).hexdigest()


def _session_expiry(request: Request) -> int | None:
    """Expiry of a valid owner cookie. Rotating the owner key revokes every session."""
    if len(os.getenv("COMMUNITY_ADMIN_TOKEN", "").encode()) < 32:
        return None
    expires_text, _, signature = request.cookies.get(SESSION_COOKIE, "").partition(".")
    if not expires_text.isdigit() or len(expires_text) > 12:
        return None
    expires = int(expires_text)
    if expires <= time.time() or expires > time.time() + SESSION_SECONDS + 60:
        return None
    if not hmac.compare_digest(signature, _signature(expires)):
        return None
    return expires


def require_plan_owner(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> None:
    if _session_expiry(request) is None:
        require_admin(authorization)


def _iso(expires: int) -> str:
    return datetime.fromtimestamp(expires, timezone.utc).isoformat()


@router.post("/api/plan/session", dependencies=[Depends(require_admin)])
def start_session(request: Request, response: Response):
    _origin_check(request)
    expires = int(time.time()) + SESSION_SECONDS
    response.set_cookie(
        SESSION_COOKIE,
        f"{expires}.{_signature(expires)}",
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="strict",
        secure=os.getenv("RENDER", "").lower() == "true" or request.url.scheme == "https",
        path=SESSION_PATH,
    )
    return {"expires_at": _iso(expires)}


@router.get("/api/plan/session")
def session_status(request: Request):
    expires = _session_expiry(request)
    if expires is None:
        return JSONResponse(
            status_code=401,
            content={"detail": {"code": "unauthorized", "message": "需要輸入管理金鑰。"}},
        )
    return {"expires_at": _iso(expires)}


@router.delete("/api/plan/session", status_code=204)
def end_session(request: Request):
    _origin_check(request)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path=SESSION_PATH)
    return response


def _cached_history():
    with _lock:
        cached = _cache.get("history")
        if cached and time.monotonic() < cached[0]:
            return cached[1], cached[2]
        failed = _cache.get("failure")
        if failed and time.monotonic() < failed[0]:
            raise failed[1]
    return None


def _history() -> tuple[list[str], np.ndarray]:
    """Daily 0050 closes from the published plan-data snapshot (never Yahoo directly)."""
    if (hit := _cached_history()) is not None:
        return hit
    with _fetch_lock:
        if (hit := _cached_history()) is not None:
            return hit
        try:
            dates, closes, _ = plan_data.load_history()
        except DataSourceError as exc:
            with _lock:
                _cache["failure"] = (time.monotonic() + FAILURE_SECONDS, exc)
            raise
        values = np.array(closes, dtype=float)
        with _lock:
            _cache.pop("failure", None)
            _cache["history"] = (time.monotonic() + CACHE_SECONDS, dates, values)
        return dates, values


def max_drawdown(dates: list[str], closes: np.ndarray) -> dict:
    peaks = np.maximum.accumulate(closes)
    drawdowns = closes / peaks - 1
    trough = int(np.argmin(drawdowns))
    peak = int(np.argmax(closes[: trough + 1]))
    recovered = np.nonzero(closes[trough:] >= closes[peak])[0]
    recovery = trough + int(recovered[0]) if len(recovered) else None
    return {
        "pct": round(float(drawdowns[trough]) * 100, 2),
        "peak_date": dates[peak],
        "trough_date": dates[trough],
        "recovery_date": dates[recovery] if recovery is not None else None,
        "recovery_trading_days": recovery - peak if recovery is not None else None,
    }


def _summary(returns: list[float]) -> dict:
    values = np.array(returns) * 100
    return {
        "median": round(float(np.median(values)), 2),
        "p5": round(float(np.percentile(values, 5)), 2),
        "worst": round(float(values.min()), 2),
        "best": round(float(values.max()), 2),
        "loss_rate": round(float((values < 0).mean()) * 100, 1),
    }


def _schedule(start: int, months: int) -> list[int]:
    return [start + MONTH * k for k in range(months)]


def _dca_shares(closes: np.ndarray, start: int, months: int, capital: float) -> float:
    each = capital / months
    return sum(each / (closes[i] * (1 + BUY_FEE)) for i in _schedule(start, months))


def _satellite(
    closes: np.ndarray, start: int, end: int, up: float, down: float, fraction: float
) -> tuple[float, int]:
    """Value (per 1 unit) and trade count of a sell-high / buy-back rule."""
    shares = 1 / (closes[start] * (1 + BUY_FEE))
    cash, reference, trades = 0.0, closes[start], 0
    for price in closes[start + 1 : end + 1]:
        if shares > 0 and price >= reference * (1 + up):
            sold = shares * fraction
            shares -= sold
            cash += sold * price * (1 - SELL_COST)
            reference, trades = price, trades + 1
        elif cash > 0 and price <= reference * (1 - down):
            shares += cash / (price * (1 + BUY_FEE))
            cash, reference, trades = 0.0, price, trades + 1
    return shares * closes[end] + cash, trades


def simulate(
    closes: np.ndarray,
    *,
    months: int,
    horizon_months: int,
    up: float,
    down: float,
    fraction: float,
) -> dict:
    horizon = horizon_months * MONTH
    starts = range(0, len(closes) - horizon, START_STEP)
    if not starts:
        raise ValueError("Not enough history for this horizon.")
    lump, dca, lump_lows, dca_better = [], [], [], 0
    plans = {share: {"returns": [], "trades": [], "beats_dca": 0} for share in SATELLITE_SHARES}
    for start in starts:
        end = start + horizon
        lump_shares = 1 / (closes[start] * (1 + BUY_FEE))
        lump_value = lump_shares * closes[end]
        lump.append(lump_value - 1)
        lump_lows.append(lump_shares * closes[start : end + 1].min() - 1)
        dca_value = _dca_shares(closes, start, months, 1.0) * closes[end]
        dca.append(dca_value - 1)
        dca_better += dca_value > lump_value
        for share in SATELLITE_SHARES:
            core = _dca_shares(closes, start, months, 1 - share) * closes[end]
            satellite, trades = (
                _satellite(closes, start, end, up, down, fraction) if share else (0.0, 0)
            )
            value = core + satellite * share
            plan = plans[share]
            plan["returns"].append(value - 1)
            plan["trades"].append(trades)
            plan["beats_dca"] += value > dca_value + 1e-12
    count = len(lump)
    return {
        "samples": count,
        "lump_sum": {**_summary(lump), "worst_paper_loss": _summary(lump_lows)["worst"]},
        "monthly": _summary(dca),
        "monthly_beats_lump_pct": round(dca_better / count * 100, 1),
        "satellite": [
            {
                "share_pct": round(share * 100),
                **_summary(plan["returns"]),
                "median_trades": int(np.median(plan["trades"])),
                "beats_monthly_pct": (
                    None if share == 0 else round(plan["beats_dca"] / count * 100, 1)
                ),
            }
            for share, plan in plans.items()
        ],
    }


@router.get("/api/plan/0050", dependencies=[Depends(require_plan_owner)])
def plan_0050(
    months: Annotated[int, Query(ge=1, le=24)] = 12,
    horizon_months: Annotated[int, Query(ge=6, le=120)] = 36,
    up_pct: Annotated[float, Query(ge=1, le=50)] = 8,
    down_pct: Annotated[float, Query(ge=1, le=50)] = 10,
    sell_fraction_pct: Annotated[float, Query(ge=5, le=100)] = 33,
):
    if horizon_months < months:
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "invalid_horizon", "message": "觀察期不能短於投入月數。"}},
        )
    try:
        dates, closes = _history()
        result = simulate(
            closes,
            months=months,
            horizon_months=horizon_months,
            up=up_pct / 100,
            down=down_pct / 100,
            fraction=sell_fraction_pct / 100,
        )
    except DataSourceError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "history_unavailable",
                    "source_code": exc.code,
                    "message": "暫時無法取得 0050 歷史價格。",
                }
            },
        )
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "insufficient_history",
                    "message": "歷史資料不足以計算此觀察期。",
                }
            },
        )
    return {
        "symbol": SYMBOL,
        "latest": {"date": dates[-1], "close": float(closes[-1])},
        "history": {"start": dates[0], "end": dates[-1], "days": len(dates)},
        "max_drawdown": max_drawdown(dates, closes),
        "simulation": result,
        "assumptions": {
            "buy_fee_pct": BUY_FEE * 100,
            "sell_cost_pct": round(SELL_COST * 100, 4),
            "trading_days_per_month": MONTH,
            "start_every_trading_days": START_STEP,
            "dividends": "excluded",
            "today": date.today().isoformat(),
        },
    }
