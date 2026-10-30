"""HTTP API and same-origin, dependency-free web dashboard."""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stockpredict.community import router as community_router
from stockpredict.data import DataSourceError, demo_data, normalize_symbol, parse_csv, yahoo_data
from stockpredict.forecast import analyze
from stockpredict.localization import Language, add_localizations, localize_error
from stockpredict.market_data import overnight_factors
from stockpredict.overnight import build_context, pending_context
from stockpredict.twse import normalize_twse_symbol, twse_data

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="StockPredict", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(community_router)


@app.middleware("http")
async def community_cache_policy(request: Request, call_next):
    response = await call_next(request)
    if (
        request.url.path.startswith(("/api/community", "/api/analysis"))
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
    umc_csv: str = Field(min_length=1, max_length=2_000_000)
    soxx_csv: str = Field(min_length=1, max_length=2_000_000)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/admin", include_in_schema=False)
def feedback_admin():
    return FileResponse(STATIC / "admin.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/analysis")
def analysis(
    symbol: Annotated[str, Query(min_length=1, max_length=20)] = "2330.TW",
    source: Literal["demo", "yahoo", "twse"] = "demo",
    horizon: Annotated[int, Query(ge=1, le=30)] = 5,
    lang: Language = "zh-TW",
    market_context: Literal["none", "us_overnight"] = "none",
):
    return _market_analysis(symbol, source, horizon, lang, market_context)


def _market_analysis(
    symbol: str,
    source: Literal["demo", "yahoo", "twse"],
    horizon: int,
    lang: Language,
    market_context: Literal["none", "us_overnight"],
    factor_data: dict[str, list[dict]] | None = None,
):
    try:
        symbol = normalize_twse_symbol(symbol) if source == "twse" else normalize_symbol(symbol)
        if market_context == "us_overnight" and symbol == "2303":
            symbol = "2303.TW"
        if market_context == "us_overnight" and (symbol != "2303.TW" or source == "demo"):
            raise ValueError("美股參考目前僅支援聯電 2303.TW 的證交所或 Yahoo 真實行情。")
        providers = {"demo": demo_data, "yahoo": yahoo_data, "twse": twse_data}
        points, metadata = providers[source](symbol)
        result = analyze(points, horizon)
        if market_context == "us_overnight":
            factor_source = "csv" if factor_data is not None else "yahoo"
            try:
                pending = pending_context(points)
                if pending is not None:
                    result["market_context"] = pending
                else:
                    factors = factor_data if factor_data is not None else overnight_factors()
                    result["market_context"] = build_context(points, factors)
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
                }
            result["market_context"]["data_source"] = factor_source
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
        normalized = normalize_twse_symbol(body.symbol)
        if normalized != "2303.TW":
            raise ValueError("美股參考目前僅支援聯電 2303.TW 的證交所或 Yahoo 真實行情。")
        factors = {}
        for factor, csv_text in (("UMC", body.umc_csv), ("SOXX", body.soxx_csv)):
            try:
                factors[factor] = parse_csv(csv_text)
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
