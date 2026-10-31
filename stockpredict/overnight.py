"""Optional, one-day Taiwan forecast using already-completed US sessions.

The daily feeds do not contain historical publication timestamps. A US bar is
therefore assumed available fifteen minutes after the calendar's exchange close,
including DST and early closes. This is not a point-in-time price archive or a
guarantee of publication. Missing expected sessions are excluded rather than
treated as zero returns. The ordinary multi-day forecast remains separate.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import exp
from zoneinfo import ZoneInfo

import numpy as np

from stockpredict.adr_scenario import ADR_SYMBOLS, directional_adr_forecast
from stockpredict.calendar import available_at, date_path, is_session, next_session
from stockpredict.forecast import LAGS, conditional_forecast, fit_predict, validate_points
from stockpredict.reference_profiles import FACTOR_PAIRS

FACTORS = ("UMC", "SOXX")
MIN_ALIGNED_ROWS = 60
RIDGE_PENALTY = 1.0
TAIPEI = ZoneInfo("Asia/Taipei")
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class _Row:
    index: int
    day: str
    features: np.ndarray
    target: float


def _available_at(day: date) -> datetime:
    return available_at(day, "XNYS")


def _taiwan_time(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), TAIPEI).astimezone(timezone.utc)


def _session_window(previous: date, target: date) -> tuple[date, list[date]]:
    """Expected baseline and US sessions strictly after the preceding TW close."""
    prior_close = _taiwan_time(previous, 13, 30)
    cutoff = _taiwan_time(target, 9)
    baseline = prior_close.astimezone(NEW_YORK).date()
    while not is_session(baseline, "XNYS") or _available_at(baseline) > prior_close:
        baseline -= timedelta(days=1)
    sessions = []
    day = baseline + timedelta(days=1)
    last = cutoff.astimezone(NEW_YORK).date()
    while day <= last:
        if is_session(day, "XNYS") and prior_close < _available_at(day) <= cutoff:
            sessions.append(day)
        day += timedelta(days=1)
    return baseline, sessions


def _window_returns(
    baseline: date,
    sessions: list[date],
    factors: dict[str, dict[date, float]],
    factor_symbols: tuple[str, str] = FACTORS,
) -> np.ndarray | None:
    if not sessions:
        return None
    # Intermediate weekday prices are required even though the cumulative
    # return telescopes. This avoids silently treating missing sessions as known.
    required = [baseline, *sessions]
    if any(day not in factors[symbol] for symbol in factor_symbols for day in required):
        return None
    return np.array(
        [
            np.log(factors[symbol][sessions[-1]] / factors[symbol][baseline])
            for symbol in factor_symbols
        ]
    )


def _fit_predict(features: np.ndarray, targets: np.ndarray, next_features: np.ndarray) -> float:
    """Standardization and fitting see this training prefix only."""
    mean = features.mean(axis=0)
    scale = features.std(axis=0)
    scale = np.where(scale < 1e-12, 1.0, scale)
    design = np.column_stack([np.ones(len(features)), (features - mean) / scale])
    penalty = np.diag([0.0] + [RIDGE_PENALTY] * features.shape[1])
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ targets)
    next_design = np.r_[1.0, (next_features - mean) / scale]
    return float(np.clip(next_design @ coefficients, -0.2, 0.2))


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 2 or np.std(left) < 1e-12 or np.std(right) < 1e-12:
        return None
    return float(np.clip(np.corrcoef(left, right)[0, 1], -1, 1))


def _historical_rows(
    points: list[dict],
    prices: np.ndarray,
    factors: dict[str, dict[date, float]],
    factor_symbols: tuple[str, str] = FACTORS,
) -> list[_Row]:
    returns = np.diff(np.log(prices))
    rows = []
    for index in range(LAGS + 1, len(points)):
        previous = date.fromisoformat(points[index - 1]["date"])
        target = date.fromisoformat(points[index]["date"])
        baseline, sessions = _session_window(previous, target)
        overnight = _window_returns(baseline, sessions, factors, factor_symbols)
        if overnight is not None:
            rows.append(
                _Row(
                    index,
                    points[index]["date"],
                    np.r_[returns[index - 1 - LAGS : index - 1], overnight],
                    float(returns[index - 1]),
                )
            )
    return rows


def _backtest(rows: list[_Row], prices: np.ndarray) -> dict:
    count = min(20, len(rows) // 5)
    start = len(rows) - count
    factor_predictions, ar_predictions, actual, baseline = [], [], [], []
    for position in range(start, len(rows)):
        row = rows[position]
        training = rows[:position]
        predicted_return = _fit_predict(
            np.array([item.features for item in training]),
            np.array([item.target for item in training]),
            row.features,
        )
        previous_close = float(prices[row.index - 1])
        factor_predictions.append(previous_close * exp(predicted_return))
        ar_predictions.append(fit_predict(prices[: row.index]))
        actual.append(float(prices[row.index]))
        baseline.append(previous_close)
    actual, baseline = np.array(actual), np.array(baseline)
    factor_predictions, ar_predictions = np.array(factor_predictions), np.array(ar_predictions)
    factor_mae = float(np.mean(np.abs(factor_predictions - actual)))
    ar_mae = float(np.mean(np.abs(ar_predictions - actual)))
    direction = np.sign(actual - baseline)
    return {
        "observations": count,
        "start": rows[start].day,
        "end": rows[-1].day,
        "dates": [row.day for row in rows[start:]],
        "factor_mae": factor_mae,
        "ar_mae": ar_mae,
        "baseline_mae": float(np.mean(np.abs(baseline - actual))),
        "factor_direction_accuracy_pct": float(
            np.mean(np.sign(factor_predictions - baseline) == direction) * 100
        ),
        "ar_direction_accuracy_pct": float(
            np.mean(np.sign(ar_predictions - baseline) == direction) * 100
        ),
        "baseline_direction_accuracy_pct": float(np.mean(direction == 0) * 100),
        # Positive means an improvement over the original AR(5), not a claim
        # that either model beats the unchanged-price baseline.
        "improvement_pct": (ar_mae - factor_mae) / ar_mae * 100 if ar_mae > 1e-12 else None,
    }


def _timing_context(points: list[dict], now: datetime | None) -> tuple[datetime, date, date, dict]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    validate_points(points)
    last_day = date.fromisoformat(points[-1]["date"])
    target = next_session(last_day)
    cutoff = min(now, _taiwan_time(target, 9))
    _, sessions = _session_window(last_day, target)
    result = {
        "status": "unavailable",
        "reason": None,
        "target_date": target.isoformat(),
        "decision_cutoff": cutoff.isoformat(),
        "assumed_availability": True,
        "forecast": None,
        "scenario_forecast": [],
        "scenario_method": None,
        "quotes": [],
        "factors": [],
        "backtest": None,
        "correlations_window": None,
        "required_us_session_date": sessions[-1].isoformat() if sessions else None,
        "available_after": _available_at(sessions[-1]).isoformat() if sessions else None,
    }
    if now >= _taiwan_time(target, 13, 30):
        result["reason"] = "stale_history"
    elif now < _taiwan_time(last_day, 13, 30):
        result["reason"] = "incomplete_history"
    elif not sessions:
        result["reason"] = "missing_us_sessions"
    elif any(_available_at(day) > cutoff for day in sessions):
        result.update(status="waiting", reason="us_session_not_closed")
    return now, last_day, target, result


def pending_context(points: list[dict], *, now: datetime | None = None) -> dict | None:
    """Check required US sessions before any factor download or CSV analysis."""
    _, _, _, result = _timing_context(points, now)
    return result if result["reason"] is not None else None


def reference_timing(points: list[dict], *, now: datetime | None = None) -> dict:
    """Describe the exact required session, including when data is eligible."""
    return _timing_context(points, now)[3]


def build_context(
    points: list[dict],
    factors: dict[str, list[dict]],
    *,
    now: datetime | None = None,
    factor_symbols: tuple[str, str] = FACTORS,
    horizon: int = 5,
) -> dict:
    """Use the required completed US sessions; never substitute an earlier date."""
    if not isinstance(factor_symbols, tuple) or factor_symbols not in FACTOR_PAIRS:
        raise ValueError("Unsupported reference-factor pair.")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 30:
        raise ValueError("預測天數必須是 1 至 30 的整數。")
    _, last_day, target, result = _timing_context(points, now)
    if result["reason"] is not None:
        return result
    if not isinstance(factors, dict):
        return {**result, "reason": "invalid_factor_data"}
    mapped = {}
    data_reason = None
    session = date.fromisoformat(result["required_us_session_date"])
    for symbol in factor_symbols:
        try:
            observations = factors[symbol]
            validate_points(observations)
            mapped[symbol] = {
                date.fromisoformat(item["date"]): float(item["close"]) for item in observations
            }
        except KeyError:
            data_reason = data_reason or "missing_factors"
            continue
        except (ValueError, TypeError):
            data_reason = "invalid_factor_data"
            continue
        if session in mapped[symbol]:
            close = mapped[symbol][session]
            previous_days = [day for day in mapped[symbol] if day < session]
            previous_day = max(previous_days) if previous_days else None
            previous_close = mapped[symbol][previous_day] if previous_day else None
            result["quotes"].append(
                {
                    "symbol": symbol,
                    "currency": "USD",
                    "session_date": session.isoformat(),
                    "close": close,
                    "previous_session_date": previous_day.isoformat() if previous_day else None,
                    "previous_close": previous_close,
                    "day_change": close - previous_close if previous_close is not None else None,
                    "day_change_pct": (close / previous_close - 1) * 100
                    if previous_close is not None
                    else None,
                }
            )
    if data_reason is not None:
        return {**result, "reason": data_reason}
    baseline, sessions = _session_window(last_day, target)
    overnight = _window_returns(baseline, sessions, mapped, factor_symbols)
    if overnight is None:
        return {**result, "reason": "missing_us_sessions"}
    prices = np.array([float(point["close"]) for point in points])
    rows = _historical_rows(points, prices, mapped, factor_symbols)
    if len(rows) < MIN_ALIGNED_ROWS:
        return {**result, "reason": "insufficient_aligned_history"}

    if factor_symbols[0] in ADR_SYMBOLS:
        adr_quote = next(
            (quote for quote in result["quotes"] if quote["symbol"] == factor_symbols[0]), None
        )
        try:
            scenario, scenario_method = directional_adr_forecast(points, adr_quote, horizon)
        except ValueError:
            # Never substitute an older/multiple-session ADR move or silently
            # revert to a path whose direction could oppose the requested rule.
            return {**result, "reason": "missing_us_sessions"}
        result["scenario_forecast"] = scenario
        result["scenario_method"] = scenario_method

    window = rows[-60:]
    targets = np.array([row.target for row in window])
    result["correlations_window"] = {
        "start": window[0].day,
        "end": window[-1].day,
        "samples": len(window),
    }
    result["factors"] = [
        {
            "symbol": symbol,
            "first_session": None,
            "last_session": None,
            "return_pct": None,
            "available_at": None,
            "correlation": _correlation(
                np.array([row.features[LAGS + index] for row in window]), targets
            ),
            "samples": len(window),
        }
        for index, symbol in enumerate(factor_symbols)
    ]
    result["backtest"] = _backtest(rows, prices)

    features = np.r_[np.diff(np.log(prices))[-LAGS:], overnight]
    predicted_return = _fit_predict(
        np.array([row.features for row in rows]), np.array([row.target for row in rows]), features
    )
    previous_close = float(prices[-1])
    result["forecast"] = {
        "date": target.isoformat(),
        "close": previous_close * exp(predicted_return),
        "base_close": previous_close,
        "change_pct": (exp(predicted_return) - 1) * 100,
    }
    if factor_symbols[0] not in ADR_SYMBOLS:
        result["scenario_forecast"] = conditional_forecast(
            points, result["forecast"]["close"], horizon=horizon
        )
    result["scenario_forecast"] = date_path(result["scenario_forecast"], points[-1]["date"], "XTAI")
    for index, item in enumerate(result["factors"]):
        item.update(
            first_session=sessions[0].isoformat(),
            last_session=sessions[-1].isoformat(),
            return_pct=(exp(float(overnight[index])) - 1) * 100,
            available_at=_available_at(sessions[-1]).isoformat(),
        )
    return {**result, "status": "ready"}
