"""HTTP API and same-origin, dependency-free web dashboard."""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stockpredict.data import DataSourceError, demo_data, normalize_symbol, parse_csv, yahoo_data
from stockpredict.forecast import analyze

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="StockPredict", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class CsvAnalysis(BaseModel):
    symbol: str = Field(default="CUSTOM", min_length=1, max_length=20)
    horizon: int = Field(default=5, ge=1, le=30, strict=True)
    csv: str = Field(min_length=1, max_length=2_000_000)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/analysis")
def analysis(
    symbol: Annotated[str, Query(min_length=1, max_length=20)] = "2330.TW",
    source: Literal["demo", "yahoo"] = "demo",
    horizon: Annotated[int, Query(ge=1, le=30)] = 5,
):
    try:
        symbol = normalize_symbol(symbol)
        points, metadata = demo_data(symbol) if source == "demo" else yahoo_data(symbol)
        result = analyze(points, horizon)
        if source == "demo":
            result["warnings"].insert(0, "所有價格、預測與回測均來自合成資料，不代表真實市場表現。")
        else:
            result["warnings"].insert(
                0, "Yahoo 每日收盤價未還原權息，除權息與股票分割可能扭曲報酬與回測。"
            )
        return {"symbol": symbol, **metadata, **result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DataSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/analysis/csv")
def analyze_csv(body: CsvAnalysis):
    try:
        symbol = normalize_symbol(body.symbol)
        result = analyze(parse_csv(body.csv), body.horizon)
        result["warnings"].insert(0, "CSV 由使用者提供；請自行確認資料來源、幣別與還原權息方式。")
        return {
            "symbol": symbol,
            "name": "自訂歷史資料",
            "currency": "",
            "source": "csv",
            "source_label": "使用者匯入 CSV",
            **result,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
