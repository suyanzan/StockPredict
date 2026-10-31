"""Small ridge autoregression with an expanding-window, one-step backtest.

Every backtest fit sees only the prefix before its target observation. Forecast
bands are volatility scenarios, not calibrated prediction intervals.
"""

from datetime import date, timedelta
from math import exp, sqrt

import numpy as np

MIN_POINTS = 60
MAX_POINTS = 5000
LAGS = 5
MIN_PRICE = 1e-8
MAX_PRICE = 1e12


def validate_points(points: list[dict]) -> None:
    if not MIN_POINTS <= len(points) <= MAX_POINTS:
        raise ValueError(f"需要 {MIN_POINTS} 至 {MAX_POINTS} 筆每日收盤價。")
    previous = None
    for point in points:
        try:
            day = date.fromisoformat(point["date"])
            price = float(point["close"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("每筆資料必須包含 YYYY-MM-DD 日期與有效收盤價。") from exc
        if point["date"] != day.isoformat():
            raise ValueError("日期格式必須是 YYYY-MM-DD。")
        if previous is not None and day <= previous:
            raise ValueError("日期必須由舊至新排序，且不能重複。")
        if not np.isfinite(price) or not MIN_PRICE <= price <= MAX_PRICE:
            raise ValueError("收盤價必須是 0.00000001 至 1,000,000,000,000 的有限正數。")
        previous = day
    try:
        date.fromisoformat(points[-1]["date"]) + timedelta(days=50)
    except OverflowError as exc:
        raise ValueError("最後日期超出可預測範圍。") from exc


def _fit(prices: np.ndarray) -> np.ndarray:
    returns = np.diff(np.log(prices))
    if len(returns) < LAGS + 2:
        raise ValueError("模型需要更多歷史資料。")
    x = np.array([[1.0, *returns[i - LAGS : i]] for i in range(LAGS, len(returns))])
    y = returns[LAGS:]
    # Penalize lag coefficients; the intercept remains unpenalized.
    penalty = np.diag([0.0] + [0.01] * LAGS)
    return np.linalg.solve(x.T @ x + penalty, x.T @ y)


def _next_price(prices: np.ndarray, coefficients: np.ndarray) -> float:
    features = np.r_[1.0, np.diff(np.log(prices))[-LAGS:]]
    predicted_return = float(np.clip(features @ coefficients, -0.2, 0.2))
    return float(prices[-1]) * exp(predicted_return)


def fit_predict(prices: np.ndarray) -> float:
    """Fit on the supplied prices only and predict one following close."""
    values = np.asarray(prices, dtype=float)
    return _next_price(values, _fit(values))


def conditional_forecast(points: list[dict], first_close: float, horizon: int = 5) -> list[dict]:
    """Recurse from one supplied first-day estimate using original-history AR(5).

    Only the initial estimate may incorporate an external market observation.
    Later steps introduce no future external prices and do not refit on invented
    observations. This conditional path has no independently calibrated bands.
    """
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 30:
        raise ValueError("預測天數必須是 1 至 30 的整數。")
    validate_points(points)
    try:
        first = float(first_close)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("第一日情境價格必須為有限正數。") from exc
    if isinstance(first_close, bool) or not np.isfinite(first) or first <= 0:
        raise ValueError("第一日情境價格必須為有限正數。")
    prices = np.array([float(point["close"]) for point in points])
    coefficients = _fit(prices)
    future_prices = prices.copy()
    last_day = date.fromisoformat(points[-1]["date"])
    forecasts = []
    for step in range(horizon):
        last_day += timedelta(days=1)
        while last_day.weekday() >= 5:
            last_day += timedelta(days=1)
        prediction = first if step == 0 else _next_price(future_prices, coefficients)
        if not np.isfinite(prediction) or prediction <= 0:
            raise ValueError("情境價格超出有效範圍。")
        forecasts.append({"date": last_day.isoformat(), "close": prediction})
        future_prices = np.append(future_prices, prediction)
    return forecasts


def _backtest(prices: np.ndarray) -> dict:
    count = min(30, len(prices) // 5)
    start = len(prices) - count
    predictions = np.array([fit_predict(prices[:i]) for i in range(start, len(prices))])
    actual = prices[start:]
    baseline = prices[start - 1 : -1]
    errors = predictions - actual
    baseline_mae = float(np.mean(np.abs(baseline - actual)))
    mae = float(np.mean(np.abs(errors)))
    direction = np.sign(actual - baseline)
    return {
        "observations": count,
        "mae": mae,
        "rmse": float(np.sqrt(np.mean(errors**2))),
        "mape_pct": float(np.mean(np.abs(errors / actual)) * 100),
        "baseline_mae": baseline_mae,
        "direction_accuracy_pct": float(
            np.mean(np.sign(predictions - baseline) == direction) * 100
        ),
        "baseline_direction_accuracy_pct": float(np.mean(direction == 0) * 100),
        "model_beats_baseline": mae < baseline_mae,
    }


def analyze(points: list[dict], horizon: int = 5) -> dict:
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 30:
        raise ValueError("預測天數必須是 1 至 30 的整數。")
    validate_points(points)
    prices = np.array([float(p["close"]) for p in points])
    coefficients = _fit(prices)
    volatility = float(np.std(np.diff(np.log(prices))[-60:], ddof=1))
    last_day = date.fromisoformat(points[-1]["date"])
    future_prices = prices.copy()
    forecasts = []
    for step in range(1, horizon + 1):
        last_day += timedelta(days=1)
        while last_day.weekday() >= 5:
            last_day += timedelta(days=1)
        prediction = _next_price(future_prices, coefficients)
        # Normal-log-return scenario with 1.645 * historical volatility.
        # This does not account for model risk, market holidays, or tail events.
        spread = 1.645 * volatility * sqrt(step)
        forecasts.append(
            {
                "date": last_day.isoformat(),
                "close": prediction,
                "lower": prediction * exp(-spread),
                "upper": prediction * exp(spread),
            }
        )
        future_prices = np.append(future_prices, prediction)
    backtest = _backtest(prices)
    warnings = [
        "預測僅供研究參考，不構成投資建議，也不保證未來表現。",
        "未來日期僅排除週末，未套用各交易所休市日；CSV 視每一列為一個觀測日。",
        "情境區間依歷史波動估計，未校準涵蓋率，亦未計入模型風險與極端行情。",
        "回測為逐日重新訓練的一日預測；多日預測表現未經此回測驗證。",
    ]
    if not backtest["model_beats_baseline"]:
        warnings.append("這段回測中，模型的平均絕對誤差未優於「維持前一日價格」基準。")
    return {
        "as_of": points[-1]["date"],
        "history": [{"date": p["date"], "close": float(p["close"])} for p in points],
        "forecast": forecasts,
        "summary": {
            "last_close": float(prices[-1]),
            "day_change_pct": float((prices[-1] / prices[-2] - 1) * 100),
            "forecast_change_pct": float((forecasts[-1]["close"] / prices[-1] - 1) * 100),
            "annualized_volatility_pct": volatility * sqrt(252) * 100,
        },
        "backtest": backtest,
        "model": {
            "name": "Ridge AR(5)",
            "description": (
                "以最近 5 個對數報酬率預測下一個報酬率，使用固定正則化 0.01 的 Ridge 迴歸。"
                "多日估計固定模型係數並遞迴預測；每日預估對數報酬限制在 ±0.2。"
            ),
            "interval_description": "歷史近 60 個報酬率的日波動 × 1.645 × √天數之對數價格情境帶。",
        },
        "warnings": warnings,
    }
