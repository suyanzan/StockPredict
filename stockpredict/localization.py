"""Presentation-only translations; model inputs and results remain unchanged."""

import re
from copy import deepcopy
from typing import Literal

Language = Literal["zh-TW", "en"]

ERRORS_EN = {
    "股票代號格式無效，例如 2330.TW、0050.TW 或 AAPL。": (
        "Invalid symbol. Examples: 2330.TW, 0050.TW, or AAPL."
    ),
    "示範資料支援 2330.TW、0050.TW、AAPL 與 MSFT；其他代號請使用 Yahoo 或 CSV。": (
        "Demo data supports 2330.TW, 0050.TW, AAPL, and MSFT. Use TWSE, "
        "Yahoo, or CSV for other symbols."
    ),
    "CSV 不可超過 2 MB。": ("CSV files must be no larger than 2 MB."),
    "CSV 必須包含 Date 與 Close 欄位。": ("CSV files must contain Date and Close columns."),
    "CSV 欄位名稱不可重複。": ("CSV column names must be unique."),
    "CSV 不可超過 5000 筆資料。": ("CSV files must contain no more than 5,000 observations."),
    "CSV 格式無法解析，請確認逗號、引號與換行。": (
        "Unable to parse the CSV. Check delimiters, quotes, and line breaks."
    ),
    "需要 60 至 5000 筆每日收盤價。": ("Provide between 60 and 5,000 daily closing prices."),
    "每筆資料必須包含 YYYY-MM-DD 日期與有效收盤價。": (
        "Each observation needs a YYYY-MM-DD date and a valid closing price."
    ),
    "日期格式必須是 YYYY-MM-DD。": ("Dates must use YYYY-MM-DD format."),
    "日期必須由舊至新排序，且不能重複。": (
        "Dates must be unique and sorted from oldest to newest."
    ),
    "收盤價必須是 0.00000001 至 1,000,000,000,000 的有限正數。": (
        "Closing prices must be finite numbers between 0.00000001 and 1,000,000,000,000."
    ),
    "最後日期超出可預測範圍。": ("The final date is outside the supported forecast range."),
    "模型需要更多歷史資料。": ("The model needs more historical observations."),
    "預測天數必須是 1 至 30 的整數。": ("The forecast horizon must be an integer from 1 to 30."),
    "Yahoo 已限流（HTTP 429）。上市台股請改用「證交所每日行情」，美股請稍後重試或匯入 CSV。": (
        "Yahoo has rate-limited this request (HTTP 429). For TWSE-listed "
        "shares, select TWSE; for US stocks, try later or import CSV "
        "data."
    ),
    "Yahoo 找不到此股票代號，請確認市場後綴。": (
        "Yahoo could not find this symbol. Check the exchange suffix."
    ),
    "無法取得 Yahoo 行情，請檢查網路設定，或改用 CSV／示範資料。": (
        "Unable to reach Yahoo. Check connectivity, or use CSV or demo data."
    ),
    "Yahoo 回傳的有效資料不足或格式不符，請改用 CSV。": (
        "Yahoo returned too few valid observations or an unexpected format. Try importing CSV data."
    ),
    "證交所資料正在讀取中，請稍候再試；也可先匯入 CSV。": (
        "A TWSE download is in progress. Please try again shortly or import CSV data."
    ),
    "證交所來源僅支援上市台股／ETF，例如 2303 或 2303.TW；上櫃 .TWO 與美股請使用 Yahoo 或 CSV。": (
        "TWSE supports numeric listed-security symbols such as 2303 or "
        "2303.TW. For OTC (.TWO) or US stocks, use Yahoo or CSV."
    ),
    "無法連線至證交所，請稍後重試或匯入 CSV。": (
        "Unable to reach TWSE. Try again later or import CSV data."
    ),
    "證交所回應格式無法解析，請稍後重試或匯入 CSV。": (
        "Unable to parse the TWSE response. Try again later or import CSV data."
    ),
    "證交所回傳資料格式不符，請稍後重試或匯入 CSV。": (
        "TWSE returned an unexpected data format. Try again later or import CSV data."
    ),
    "證交所近六個月有效收盤價不足 60 筆，或資料無效。"
    "請確認為上市代碼；新上市／長期停牌股票可改用 CSV。": (
        "TWSE has fewer than 60 valid closes in the past six months, or "
        "the data is invalid. Check the listed symbol; for recent "
        "listings or suspended stocks, try CSV data."
    ),
}

WARNINGS_EN = [
    "Forecasts are for research only, are not investment advice, "
    "and do not guarantee future results.",
    "Future dates exclude weekends only, not exchange holidays. Each CSV row is one observation.",
    "Scenario bands use historical volatility. Their coverage is not calibrated, "
    "and they do not account for model risk or extreme market events.",
    "The backtest refits a one-step forecast each day. It does not validate multi-day forecasts.",
]

SOURCE_LABELS_EN = {
    "demo": "Synthetic demo data (not actual market prices)",
    "csv": "Imported CSV data",
    "twse": "TWSE daily closing prices (unadjusted)",
    "yahoo": "Yahoo Finance daily closing prices (delayed, unadjusted)",
}


def localize_error(message: str, lang: Language) -> str:
    if lang == "zh-TW":
        return message
    if message in ERRORS_EN:
        return ERRORS_EN[message]
    match = re.fullmatch(r"第 (\d+) 列欄位數與標題不符。", message)
    if match:
        return f"Row {match[1]} has a different number of columns from the header."
    match = re.fullmatch(r"第 (\d+) 列需要 YYYY-MM-DD 日期與有效收盤價。", message)
    if match:
        return f"Row {match[1]} needs a YYYY-MM-DD date and a valid closing price."
    match = re.search(r"HTTP (\d+)", message)
    if match and "Yahoo" in message:
        return f"Yahoo is temporarily unavailable (HTTP {match[1]}). Try CSV or demo data."
    if match and "證交所" in message:
        return f"TWSE is temporarily unavailable (HTTP {match[1]}). Try later or import CSV data."
    if not re.search(r"[\u3400-\u9fff]", message):
        return message
    return "Unable to complete the analysis. Check the symbol, selected source, and data format."


def add_localizations(result: dict, lang: Language = "zh-TW") -> dict:
    """Supply both languages so changing the UI language never downloads quotes."""
    zh = {key: deepcopy(result[key]) for key in ("name", "source_label", "model", "warnings")}
    source = result["source"]
    name = result["name"]
    if source == "csv":
        name = "Imported price history"
    else:
        name = {
            "2330.TW": "TSMC",
            "0050.TW": "Yuanta Taiwan 50 ETF",
            "2303.TW": "United Microelectronics",
        }.get(result["symbol"], name)
    warnings = list(WARNINGS_EN)
    if source == "demo":
        warnings.insert(
            0,
            "All prices, forecasts, and backtests use synthetic data, "
            "not actual market performance.",
        )
    elif source == "csv":
        warnings.insert(
            0,
            "CSV data is supplied by the user. Verify its origin, currency, "
            "and treatment of corporate actions.",
        )
    else:
        warnings.insert(
            0,
            "Daily closes are unadjusted. Dividends, splits, and other corporate "
            "actions can distort returns and backtests.",
        )
    if not result["backtest"]["model_beats_baseline"]:
        warnings.append(
            "In this backtest, the model's mean absolute error did not beat "
            "the previous-close baseline."
        )
    en = {
        "name": name,
        "source_label": SOURCE_LABELS_EN[source],
        "warnings": warnings,
        "model": {
            "name": "Ridge AR(5)",
            "description": "Predicts the next log return from the previous five log returns "
            "using Ridge regression with a fixed penalty of 0.01. Multi-day "
            "forecasts recurse with fixed coefficients; predicted daily log "
            "returns are clipped to ±0.2.",
            "interval_description": "Log-price scenario band based on volatility of the last "
            "60 log returns × 1.645 × √forecast step.",
        },
    }
    return {**result, **(en if lang == "en" else zh), "locales": {"zh-TW": zh, "en": en}}
