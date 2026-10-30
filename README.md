# StockPredict

台股與美股的股價研究工具。提供繁體中文網頁、歷史價格圖、1–30 個工作日的走勢估計、波動情境帶，以及逐日重新訓練的歷史回測。第一版使用 FastAPI、NumPy 與原生 JavaScript，無需資料庫、API 金鑰或前端建置工具。

## 啟動

需要 **Python 3.12 或 3.13** 和 [uv](https://docs.astral.sh/uv/)。在專案目錄執行：

```bash
uv sync --locked --dev
uv run --no-sync uvicorn stockpredict.main:app --host 0.0.0.0 --port 8000
```

服務在 8000 埠提供網頁；`/docs` 是 API 文件。開發時可在啟動指令最後加上 `--reload`。健康檢查：

```bash
curl --fail http://127.0.0.1:8000/api/health
```

雲端工作階段使用既有 `/workspace/StockPredict` checkout，不需建立額外 worktree。工作階段重啟後，重新執行上述啟動指令；不要假設服務程序會隨環境快照保留。

## 資料來源

- **示範資料（預設）**：2330.TW、0050.TW、AAPL、MSFT 的可重現合成資料，約一年的工作日。所有價格、回測與預測均非真實市場表現。無需外部網路。
- **CSV**：上傳自己的歷史收盤價，伺服器不將檔案寫入磁碟。使用 UTF-8 編碼（接受 BOM），欄位為 `Date,Close`（大小寫不限，可有額外欄位），日期嚴格使用 `YYYY-MM-DD`。至少 60、最多 5,000 筆，上限 2 MB。可由新至舊排列，系統會排序；重複日期、空值、非有限數值或非正價格會拒絕。價格支援 0.00000001 至 1,000,000,000,000。
- **Yahoo 每日行情（選用）**：讀取 `query1.finance.yahoo.com`，需環境允許此 HTTPS 網域。不需 API 金鑰。來源可能限流或拒絕存取；失敗時顯示錯誤，不會偷偷換成示範價格。為避免尚未收盤的日線，一律排除交易所當地的今天。這是未還原權息的每日資料，**不是即時報價**；公司行動可能造成價格跳空、扭曲回測。

CSV 範例格式（實際分析需至少 60 筆）：

```csv
Date,Close
2025-01-02,100.5
2025-01-03,101.2
2025-01-06,100.9
```

台股上市代號可用 `2330.TW`，上櫃代號如 `6488.TWO`；美股如 `AAPL`、`MSFT`。示範模式僅提供上述四檔，其餘使用 CSV 或 Yahoo。CSV 的幣別、交易日完整性與權息調整方式由使用者確認；每一列視為一個觀測日。

## 預測與回測

模型 **Ridge AR(5)** 使用最近五個對數報酬率作為輸入，以固定正則化 0.01 的線性迴歸估計下一日報酬率；不使用新聞或基本面。多日預測固定模型係數，將估計值遞迴輸入，且每日估計對數報酬限制在 ±0.2。這個簡單模型方便重現、檢查與替換，不保證優於基準。

- **回測**：取最後 `min(30, 資料筆數 // 5)` 筆，逐筆僅用該日以前的資料重新訓練，計算一日預測 MAE、RMSE、MAPE 與方向命中率。以「下一日價格等於前一日價格」比較 MAE；模型未勝過基準時會明確提示。這不是持續追蹤的實盤績效，也未驗證多日預測表現。
- **方向命中率**：比較預估價格與前日價格的正負方向是否符合實際變動；不變也是獨立方向，因此不變基準僅在實際價格不變時命中。
- **情境帶**：近 60 個對數報酬率的標準差 × `1.645 × √預測步數`，套用於對數價格。使用 252 日年化波動率。此區間沒有校準未來涵蓋率，不應解讀為已驗證的信賴區間。
- **日期**：未來日期僅排除週末，未整合台灣或美國的交易所休市日。

本工具僅供研究與教學，不構成投資建議。

## 驗證

```bash
uv run --no-sync pytest -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
node --check stockpredict/static/app.js
```

測試涵蓋 CSV 驗證、數值與日期邊界、回測的時間順序、API、靜態資源與模擬的上游回應，不依賴 Yahoo 連線。相依套件版本由 `uv.lock` 固定。

## API

```text
GET  /api/health
GET  /api/analysis?symbol=2330.TW&source=demo&horizon=5
POST /api/analysis/csv
```

CSV 請求 JSON：`{"symbol":"CUSTOM","horizon":5,"csv":"Date,Close\n..."}`。`horizon` 為 1–30；網頁提供 5、10、20 日快捷選項。回應包含 `history`、`forecast`、`summary`、`backtest`、`model`、`warnings`；百分比欄位單位為百分點（例如 2.5 表示 2.5%）。CSV 不推測幣別。

## 專案結構

網站部署方式見 [DEPLOY.md](DEPLOY.md)，附有 Dockerfile 與 Render Blueprint 設定。發布 Codex 開發環境與部署公開網站是分開的步驟。

```text
stockpredict/
  main.py       # HTTP API 與靜態網頁
  data.py       # 示範、CSV 與 Yahoo 資料來源
  forecast.py   # 預測、回測與數值驗證
  static/       # HTML、CSS、JavaScript 介面
tests/          # 自動化測試
```

本版為單人研究與開發用途，沒有登入、持倉、交易下單或持久儲存。正式對外部署前需另行配置反向代理、存取控制、請求大小與速率限制、資料授權及營運監控。
