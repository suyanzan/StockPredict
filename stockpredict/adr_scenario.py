"""An explicit directional ADR scenario, separate from learned model forecasts.

The sensitivity, cap and decay below are disclosed scenario assumptions. They
are not estimated correlations, return forecasts or backtested model settings.
One observed ADR move shifts each original Taiwan forecast independently; it is
never compounded as if the same move occurred on subsequent US trading days.
"""

from datetime import date
from math import isfinite

from stockpredict.forecast import forecast_path

ADR_SYMBOLS = frozenset({"UMC", "TSM"})
SENSITIVITY = 0.5
DAILY_DECAY = 0.8
MAX_ADJUSTMENT_PCT = 5.0


def _session_date(value: object) -> date:
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("ADR 情境需要有效的交易日。") from exc
    if value != day.isoformat() or day.weekday() >= 5:
        raise ValueError("ADR 情境需要有效的交易日。")
    return day


def _positive_close(value: object) -> float:
    try:
        close = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("ADR 情境需要有限的正收盤價。") from exc
    if isinstance(value, bool) or not isfinite(close) or close <= 0:
        raise ValueError("ADR 情境需要有限的正收盤價。")
    return close


def directional_adr_forecast(
    points: list[dict], quote: dict, horizon: int = 5
) -> tuple[list[dict], dict]:
    """Shift the unchanged Taiwan path by a bounded, decaying ADR contribution.

    The caller confirms that the current session is the exact required US
    session and is already available. A missing preceding US session is rejected
    here rather than treating a multiple-session change as the current day's
    return. US holidays are excluded using the exchange calendar.
    """
    if not isinstance(quote, dict):
        raise ValueError("ADR 情境需要有效的美元報價。")
    symbol = quote.get("symbol")
    if not isinstance(symbol, str) or symbol not in ADR_SYMBOLS or quote.get("currency") != "USD":
        raise ValueError("ADR 情境僅支援對應 ADR 的美元報價。")
    session = _session_date(quote.get("session_date"))
    previous_session = _session_date(quote.get("previous_session_date"))
    try:
        from stockpredict.calendar import previous_session as previous_exchange_session

        expected_previous = previous_exchange_session(session, "XNYS")
    except OverflowError as exc:
        raise ValueError("ADR 交易日超出有效範圍。") from exc
    if previous_session != expected_previous:
        raise ValueError("ADR 情境缺少前一個美股平日收盤，不使用跨多日漲跌替代。")
    close = _positive_close(quote.get("close"))
    previous_close = _positive_close(quote.get("previous_close"))
    change_pct = (close - previous_close) / previous_close * 100
    if not isfinite(change_pct):
        raise ValueError("ADR 漲跌幅超出有效範圍。")
    uncapped = change_pct * SENSITIVITY
    initial = max(-MAX_ADJUSTMENT_PCT, min(MAX_ADJUSTMENT_PCT, uncapped))
    baseline = forecast_path(points, horizon)
    path = []
    for step, point in enumerate(baseline):
        adjustment = initial * DAILY_DECAY**step
        path.append(
            {
                "date": point["date"],
                "close": point["close"] * (1 + adjustment / 100),
                "adr_adjustment_pct": adjustment,
            }
        )
    method = {
        "id": "adr_directional_v1",
        "adr_symbol": symbol,
        "session_date": session.isoformat(),
        "previous_session_date": previous_session.isoformat(),
        "adr_change_pct": change_pct,
        "sensitivity": SENSITIVITY,
        "daily_decay": DAILY_DECAY,
        "max_adjustment_pct": MAX_ADJUSTMENT_PCT,
        "uncapped_adjustment_pct": uncapped,
        "initial_adjustment_pct": initial,
        "capped": abs(uncapped) > MAX_ADJUSTMENT_PCT,
    }
    return path, method
