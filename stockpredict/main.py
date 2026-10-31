"""HTTP API and same-origin, dependency-free web dashboard."""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stockpredict.auto_csv import auto_csv_factors
from stockpredict.calendar import data_status, date_path
from stockpredict.community import router as community_router
from stockpredict.data import DataSourceError, demo_data, normalize_symbol, parse_csv, yahoo_data
from stockpredict.forecast import analyze
from stockpredict.localization import Language, add_localizations, localize_error
from stockpredict.market_data import overnight_factors
from stockpredict.overnight import build_context, pending_context, reference_timing
from stockpredict.reference_profiles import (
    canonical_reference_symbol,
    profile_for,
    profile_payload,
    public_catalog,
)
from stockpredict.scoreboard import router as scoreboard_router
from stockpredict.twse import normalize_twse_symbol, twse_data

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="StockPredict", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(community_router)
app.include_router(scoreboard_router)


@app.middleware("http")
async def community_cache_policy(request: Request, call_next):
    response = await call_next(request)
    if (
        request.url.path.startswith(
            ("/api/community", "/api/analysis", "/api/scoreboard", "/api/calendar")
        )
        or request.url.path == "/admin"
    ):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/admin":
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


def _analysis_error(status: int, message: str, lang: Language) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "detail": localize_error(message, lang),
            "locales": {locale: localize_error(message, locale) for locale in ("zh-TW", "en")},
        },
    )


@app.exception_handler(RequestValidationError)
async def factor_csv_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path == "/api/analysis/overnight/csv":
        lang = "en" if request.query_params.get("lang") == "en" else "zh-TW"
        return _analysis_error(
            422,
            "請檢查股票代碼、資料來源、預測期間與兩份 CSV（每份上限 2 MB）。",
            lang,
        )
    return await request_validation_exception_handler(request, exc)


class CsvAnalysis(BaseModel):
    symbol: str = Field(default="CUSTOM", min_length=1, max_length=20)
    horizon: int = Field(default=5, ge=1, le=30, strict=True)
    csv: str = Field(min_length=1, max_length=2_000_000)


class FactorCsvAnalysis(BaseModel):
    symbol: str = Field(default="2303.TW", min_length=1, max_length=20)
    source: Literal["twse", "yahoo"] = "twse"
    horizon: int = Field(default=5, ge=1, le=30, strict=True)
    umc_csv: str | None = Field(default=None, min_length=1, max_length=2_000_000)
    soxx_csv: str | None = Field(default=None, min_length=1, max_length=2_000_000)
    factor_csvs: dict[str, Annotated[str, Field(min_length=1, max_length=2_000_000)]] | None = (
        Field(default=None, min_length=2, max_length=2)
    )


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/admin", include_in_schema=False)
def feedback_admin():
    return FileResponse(STATIC / "admin.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/calendar")
def market_calendar():
    from datetime import datetime, timezone

    from stockpredict.calendar import (
        available_at,
        calendar,
        latest_published,
        next_session,
        opens_at,
    )

    now = datetime.now(timezone.utc)
    markets = []
    for market in ("XTAI", "XNYS"):
        last = latest_published(now, market)
        day = next_session(last, market)
        markets.append(
            {
                "exchange": market,
                "latest_publishable_session": last.isoformat(),
                "next_session": day.isoformat(),
                "opens_at": opens_at(day, market).isoformat(),
                "closes_at": calendar(market).session_close(day).isoformat(),
                "available_after": available_at(day, market).isoformat(),
            }
        )
    return {"checked_at": now.isoformat(), "markets": markets}


@app.get("/api/reference-profiles")
def reference_profiles():
    return public_catalog()


@app.get("/api/analysis")
def analysis(
    symbol: Annotated[str, Query(min_length=1, max_length=20)] = "2330.TW",
    source: Literal["demo", "yahoo", "twse"] = "demo",
    horizon: Annotated[int, Query(ge=1, le=30)] = 5,
    lang: Language = "zh-TW",
    market_context: Literal["none", "us_overnight"] = "none",
    factor_source: Literal["yahoo", "auto_csv"] = "yahoo",
):
    return _market_analysis(
        symbol, source, horizon, lang, market_context, factor_download_source=factor_source
    )


def _market_analysis(
    symbol: str,
    source: Literal["demo", "yahoo", "twse"],
    horizon: int,
    lang: Language,
    market_context: Literal["none", "us_overnight"],
    factor_data: dict[str, list[dict]] | None = None,
    factor_download_source: Literal["yahoo", "auto_csv"] = "yahoo",
):
    try:
        symbol = normalize_twse_symbol(symbol) if source == "twse" else normalize_symbol(symbol)
        profile = None
        if market_context == "us_overnight":
            symbol = canonical_reference_symbol(symbol)
            profile = profile_for(symbol)
            if profile is None or source == "demo":
                raise ValueError("美股參考僅支援台股的證交所或 Yahoo 真實行情。")
        providers = {"demo": demo_data, "yahoo": yahoo_data, "twse": twse_data}
        points, metadata = providers[source](symbol)
        result = analyze(points, horizon)
        if source != "demo" and (
            symbol.endswith(".TW") or metadata.get("exchange_timezone") == "America/New_York"
        ):
            market = "XTAI" if symbol.endswith(".TW") else "XNYS"
            result["forecast"] = date_path(result["forecast"], points[-1]["date"], market)
            result["data_status"] = data_status(
                points, market, publication_delay=15 if source == "yahoo" else None
            )
        if market_context == "us_overnight":
            factor_source = "csv" if factor_data is not None else factor_download_source
            snapshot_metadata = None
            timing = None
            try:
                pending = pending_context(points)
                if pending is not None:
                    result["market_context"] = pending
                else:
                    factors = factor_data
                    if factors is None:
                        if factor_source == "auto_csv":
                            timing = reference_timing(points)
                            factors, snapshot_metadata = auto_csv_factors(
                                profile.symbols, timing["required_us_session_date"]
                            )
                        else:
                            factors = (
                                overnight_factors()
                                if profile.id == "umc"
                                else overnight_factors(profile.symbols)
                            )
                    result["market_context"] = (
                        build_context(
                            points, factors, **({"horizon": horizon} if horizon != 5 else {})
                        )
                        if profile.id == "umc"
                        else build_context(
                            points,
                            factors,
                            factor_symbols=profile.symbols,
                            **({"horizon": horizon} if horizon != 5 else {}),
                        )
                    )
            except DataSourceError as exc:
                result["market_context"] = {
                    "status": "unavailable",
                    "reason": exc.code,
                    "http_status": exc.http_status,
                    "retry_after_seconds": exc.retry_after,
                    "target_date": result["forecast"][0]["date"],
                    "decision_cutoff": None,
                    "assumed_availability": True,
                    "forecast": None,
                    "factors": [],
                    "backtest": None,
                    "correlations_window": None,
                    "quotes": [],
                    "scenario_forecast": [],
                }
                if timing is not None:
                    result["market_context"].update(
                        required_us_session_date=timing["required_us_session_date"],
                        available_after=timing["available_after"],
                    )
            result["market_context"]["data_source"] = factor_source
            result["market_context"]["reference_profile"] = profile_payload(profile)
            for quote in result["market_context"].get("quotes", []):
                quote["data_source"] = factor_source
            if snapshot_metadata is not None:
                result["market_context"]["snapshot_metadata"] = snapshot_metadata
        if source == "demo":
            result["warnings"].insert(0, "所有價格、預測與回測均來自合成資料，不代表真實市場表現。")
        else:
            result["warnings"].insert(
                0, "每日收盤價未還原權息，除權息與股票分割可能扭曲報酬與回測。"
            )
        return add_localizations({"symbol": symbol, **metadata, **result}, lang)
    except ValueError as exc:
        return _analysis_error(400, str(exc), lang)
    except DataSourceError as exc:
        return _analysis_error(502, str(exc), lang)


@app.post("/api/analysis/overnight/csv")
def analyze_factor_csv(body: FactorCsvAnalysis, lang: Language = "zh-TW"):
    try:
        normalized = canonical_reference_symbol(body.symbol)
        profile = profile_for(normalized)
        if profile is None:
            raise ValueError("美股參考僅支援台股的證交所或 Yahoo 真實行情。")
        if body.factor_csvs is not None:
            if body.umc_csv is not None or body.soxx_csv is not None:
                raise ValueError("請勿混用新版與舊版美股 CSV 欄位。")
            csvs = body.factor_csvs
        else:
            if profile.id != "umc" or body.umc_csv is None or body.soxx_csv is None:
                raise ValueError("請提供本股票對應的兩份美股 CSV。")
            csvs = {"UMC": body.umc_csv, "SOXX": body.soxx_csv}
        if set(csvs) != set(profile.symbols):
            raise ValueError("美股 CSV 標的不符本股票的參考設定。")
        factors = {}
        for factor in profile.symbols:
            try:
                factors[factor] = parse_csv(csvs[factor])
            except ValueError as exc:
                raise ValueError(f"{factor} CSV：{exc}") from exc
        return _market_analysis(
            normalized, body.source, body.horizon, lang, "us_overnight", factors
        )
    except ValueError as exc:
        return _analysis_error(400, str(exc), lang)


@app.post("/api/analysis/csv")
def analyze_csv(body: CsvAnalysis, lang: Language = "zh-TW"):
    try:
        symbol = normalize_symbol(body.symbol)
        result = analyze(parse_csv(body.csv), body.horizon)
        result["warnings"].insert(0, "CSV 由使用者提供；請自行確認資料來源、幣別與還原權息方式。")
        return add_localizations(
            {
                "symbol": symbol,
                "name": "自訂歷史資料",
                "currency": "",
                "source": "csv",
                "source_label": "使用者匯入 CSV",
                **result,
            },
            lang,
        )
    except ValueError as exc:
        return _analysis_error(400, str(exc), lang)
