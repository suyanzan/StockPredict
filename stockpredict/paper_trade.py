"""Reference-only paper trading of the 0050 plan, forward from a fixed start.

Two virtual NT$1,000,000 accounts are replayed from PAPER_START on each
completed 0050 daily close (decide and fill at that close):

* plan: the core is bought in equal monthly installments and a satellite
  share is bought on the first day, then sold into strength and bought back.
* baseline: the whole amount is bought in the same monthly installments.

The replay is deterministic, so every request recomputes it from the start;
there is no stored state to drift. Whole shares (odd lots), a 0.1425%
commission with a NT$1 minimum and a 0.1% ETF transaction tax on sales.
This is a simulation for reference, not advice or a record of real trades.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from stockpredict import fund_plan
from stockpredict.data import DataSourceError

PAPER_START = date(2026, 11, 19)
CAPITAL = 1_000_000
FEE_RATE = 0.001425
TAX_RATE = 0.001

router = APIRouter()


def _fee(amount: float) -> int:
    return max(1, round(amount * FEE_RATE))


def _buy(cash: float, price: float) -> tuple[int, float]:
    """Whole shares affordable with cash, and their total cost incl. commission."""
    shares = int(cash // (price * (1 + FEE_RATE)))
    while shares > 0 and shares * price + _fee(shares * price) > cash:
        shares -= 1
    return (shares, shares * price + _fee(shares * price)) if shares else (0, 0.0)


def _sell(shares: int, price: float) -> float:
    gross = shares * price
    return gross - _fee(gross) - round(gross * TAX_RATE)


def _buy_days(dates: list[str], first: int, months: int) -> list[int]:
    """First trading day on/after the start, then the first trading day of each month."""
    days, month = [first], dates[first][:7]
    for index in range(first + 1, len(dates)):
        if len(days) == months:
            break
        if dates[index][:7] != month:
            days.append(index)
            month = dates[index][:7]
    return days


def replay(
    dates: list[str],
    closes: list[float],
    *,
    start: date = PAPER_START,
    months: int = 12,
    satellite: float = 0.1,
    up: float = 0.08,
    down: float = 0.10,
    fraction: float = 0.33,
) -> dict:
    first = next((i for i, d in enumerate(dates) if d >= start.isoformat()), None)
    if first is None:
        return {"status": "waiting", "start": start.isoformat()}
    buy_days = set(_buy_days(dates, first, months))
    accounts = {
        "plan": {
            "cash": float(CAPITAL),
            "shares": 0,
            "sat_shares": 0,
            "sat_cash": 0.0,
            "core_left": CAPITAL * (1 - satellite),
            "reference": None,
            "done": 0,
        },
        "baseline": {
            "cash": float(CAPITAL),
            "shares": 0,
            "sat_shares": 0,
            "sat_cash": 0.0,
            "core_left": float(CAPITAL),
            "reference": None,
            "done": 0,
        },
    }
    installments = {"plan": CAPITAL * (1 - satellite) / months, "baseline": CAPITAL / months}
    trades, series = [], []
    for index in range(first, len(dates)):
        day, price = dates[index], float(closes[index])
        for name, account in accounts.items():
            if index in buy_days:
                budget = min(installments[name], account["core_left"])
                if account["done"] == months - 1:
                    budget = account["core_left"]  # Final installment uses the remainder.
                account["done"] += 1
                shares, cost = _buy(budget, price)
                if shares:
                    account["shares"] += shares
                    account["cash"] -= cost
                    account["core_left"] -= cost
                    trades.append(_trade(day, name, "buy", shares, price, cost, "monthly"))
            if name != "plan" or satellite == 0:
                continue
            if index == first:
                shares, cost = _buy(CAPITAL * satellite, price)
                account["sat_shares"], account["cash"] = shares, account["cash"] - cost
                account["reference"] = price
                trades.append(_trade(day, name, "buy", shares, price, cost, "satellite_start"))
            elif account["sat_shares"] and price >= account["reference"] * (1 + up):
                sold = int(account["sat_shares"] * fraction)
                if sold:
                    proceeds = _sell(sold, price)
                    account["sat_shares"] -= sold
                    account["sat_cash"] += proceeds
                    account["cash"] += proceeds
                    account["reference"] = price
                    trades.append(_trade(day, name, "sell", sold, price, proceeds, "take_profit"))
            elif account["sat_cash"] > 0 and price <= account["reference"] * (1 - down):
                shares, cost = _buy(account["sat_cash"], price)
                if shares:
                    account["sat_shares"] += shares
                    account["sat_cash"] -= cost
                    account["cash"] -= cost
                    account["reference"] = price
                    trades.append(_trade(day, name, "buy", shares, price, cost, "buy_back"))
        series.append(
            {"date": day, **{name: round(_value(a, price), 2) for name, a in accounts.items()}}
        )
    price = float(closes[-1])
    return {
        "status": "running",
        "start": start.isoformat(),
        "first_trading_day": dates[first],
        "latest": {"date": dates[-1], "close": price},
        "capital": CAPITAL,
        "accounts": {
            name: {
                "value": round(_value(a, price), 2),
                "return_pct": round((_value(a, price) / CAPITAL - 1) * 100, 2),
                "cash": round(a["cash"], 2),
                "shares": a["shares"] + a["sat_shares"],
                "installments_done": a["done"],
                "installments_total": months,
            }
            for name, a in accounts.items()
        },
        "trades": trades,
        "series": series,
    }


def _value(account: dict, price: float) -> float:
    return account["cash"] + (account["shares"] + account["sat_shares"]) * price


def _trade(day, account, side, shares, price, amount, reason) -> dict:
    return {
        "date": day,
        "account": account,
        "side": side,
        "shares": shares,
        "price": price,
        "amount": round(amount, 2),
        "reason": reason,
    }


@router.get("/api/plan/paper", dependencies=[Depends(fund_plan.require_plan_owner)])
def paper(
    months: Annotated[int, Query(ge=1, le=24)] = 12,
    satellite_pct: Annotated[float, Query(ge=0, le=50)] = 10,
    up_pct: Annotated[float, Query(ge=1, le=50)] = 8,
    down_pct: Annotated[float, Query(ge=1, le=50)] = 10,
    sell_fraction_pct: Annotated[float, Query(ge=5, le=100)] = 33,
):
    try:
        dates, closes = fund_plan._history()
    except DataSourceError:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {"code": "history_unavailable", "message": "暫時無法取得 0050 價格。"}
            },
        )
    return replay(
        dates,
        list(closes),
        months=months,
        satellite=satellite_pct / 100,
        up=up_pct / 100,
        down=down_pct / 100,
        fraction=sell_fraction_pct / 100,
    )
