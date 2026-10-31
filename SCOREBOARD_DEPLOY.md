# 預測成績看板：部署與驗證

本次工作從 `main` 的 `7796b00ac57d017cc6420bfd840340635ddab095`
重新 clone 至 `/workspace/StockPredict-fresh`，分支為
`feat/prediction-scoreboard`，未使用原工作區的程式或虛擬環境。

## 行為與資料

- 追蹤 `2303.TW`（聯電）及 `2330.TW`（台積電）。`taiwan` 與 `adr`
  分開保存、分開評分，每個預測保存完整五個交易日的原始路徑、輸入台股歷史、
  來源資訊、ADR 報價／方法、模型版本與實際保存時間。
- 僅在第一個目標交易日的台北 00:00 至 09:00 前保存，且必須取得前一交易日收盤。
  同股票、情境、起日的第一次成功保存為準，重跑不覆寫；09:00 起拒收，
  排程錯過不事後回填。缺少美股資料時只保留可用的純台股預測。
- PostgreSQL 的 unique constraint、`ON CONFLICT DO NOTHING` 與觸發器
  防止重複寫入及 UPDATE／DELETE／TRUNCATE。資料庫管理者仍有管理權限；
  部署時應維持備份及角色隔離。
- TWSE 收盤在台北 15:00 門檻後且來源確實返回該日期時才保存實際值；
  每個交易日的首次收盤紀錄不可覆寫。供應商日後修訂不會靜默改寫既有成績。
  第 1、5 個交易日分別比對精確日期，沒有該日實際值就顯示待公布，完全排除於分母。
- 誤差為預測減實際，MAE 為平均絕對誤差，MAPE 為平均絕對百分比誤差。
  方向以保存時的台股前收盤為共同基準，上漲／持平／下跌三分類；無樣本為 `null`／`—`。
- 使用鎖定版本 `exchange_calendars` 的 XTAI／XNYS 日曆，排除休市日、處理 DST 與
  提早收盤。真實台股／紐約市場分析與跨市場情境均使用交易日期；
  合成示範及無交易所資訊的 CSV 保留既有平日規則，畫面會說明。
  日曆涵蓋 2000–2035；臨時停市及交易所新公告須維護日曆依賴，不應自行猜測。
- 畫面顯示取得的行情日期、應有日期、檢查時間與缺資料原因。
  TWSE 的 15:00、美股交易所收盤後 15 分鐘、Yahoo 收盤後 15 分鐘均只是可用門檻，
  不能代替「已實際取得該日資料」的檢查。不會把舊價格改標為今天。

## 部署

1. 將此分支的變更經審查合併至部署分支。建立／選用 PostgreSQL，
   在 Web 服務設定 `SCOREBOARD_DATABASE_URL`（須使用 PostgreSQL DSN，遠端建議
   `sslmode=require`）。未設定時可使用既有 PostgreSQL `DATABASE_URL`；
   不會將 SQLite 當成成績庫，也不會自動建立外部付費資源。
2. 安裝鎖定依賴並初始化新資料表：

   ```sh
   uv sync --locked
   uv run python -m stockpredict.scoreboard init
   ```

   此命令新增 `sp_predictions`、`sp_actual_closes`、`sp_scoreboard_checks`、`sp_backtest_runs`
   與相關觸發器，不更動既有留言資料。可安全重跑。

3. 建置並啟動既有 Web 服務（Render 使用既有 Docker 設定）：

   ```sh
   docker build -t stockpredict:scoreboard .
   docker run --env-file /secure/path/stockpredict.env -p 8000:8000 stockpredict:scoreboard
   ```

   受代理管理的建置環境另加
   `--secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt`。
   執行環境也需要正確 CA 信任設定；不關閉 TLS 驗證。
   使用新的映像啟動服務後，確認 `/api/health`、`/api/calendar`、`/api/scoreboard`。
   成績庫尚未設定或未初始化時，看板會明示無法使用，既有分析可繼續使用。

4. 排程執行：

   ```sh
   uv run python -m stockpredict.scoreboard run
   ```

   已提供 `.github/workflows/scoreboard.yml`；在 GitHub repository secrets 設定
   `SCOREBOARD_DATABASE_URL`。排程於台北平日 08:10、08:30、08:50 保存／重試，
   15:30、17:30、21:30 收集公布後收盤。程式會再次查日曆及盤前門檻。
   GitHub 排程可能延遲，若要求準時執行，改由部署平台 cron 使用同一命令。
   延誤超過 09:00 的工作會拒絕保存，不以盤後預測補成績。
   保留既有 `update-market-data.yml`，讓 ADR 自動收盤快照先行更新。
   Web 與排程須連到同一資料庫；資料庫必須允許排程執行環境連線。
   正式環境可給 Web 專用唯讀角色，只授予這三張表 SELECT；初始化及排程使用寫入角色。

5. 首次部署看板沒有歷史預測屬正常現象。第一個成功盤前保存日收盤公布後
   才有第 1 日成績，第 5 個交易日公布後才有第 5 日成績。
   觀察看板最近檢查狀態及排程輸出，缺來源資料會留下原因。

## 本次驗證

- 變更前：依賴安裝完成，既有 559 項 pytest 通過。
- 最終 591 項 pytest 全部通過，含真實 PostgreSQL 17 的整合測試；Ruff 檢查及格式檢查通過。
  執行方式：

  ```sh
  TEST_POSTGRES_URL="$SCOREBOARD_DATABASE_URL" uv run pytest -q
  uv run ruff check .
  uv run ruff format --check .
  ```

  整合測試建立獨立隨機 schema 並於結束移除；未提供 `TEST_POSTGRES_URL`
  時這些測試會明示跳過。CI 已新增 PostgreSQL service，避免漏跑。
  涵蓋重跑與併發唯一性、不可修改／刪除／清空、盤前門檻、來源失敗、
  一／五日分開計分、待公布排除、持平方向、台灣連假、US DST 與提早收盤。
- Docker 映像建置，並以非 root 使用者啟動檢查 API。
- Chromium／Playwright 驗證繁中及英文、八組成績、待公布、更新按鈕、
  既有合成分析／CSV 匯出、實際 TWSE 查詢、390px 手機版與資料庫失敗顯示。
  `artifacts/browser-verification.json` 為檢查紀錄；中英文及手機截圖也在該目錄。
  瀏覽器的成績資料為獨立本機 `browser_verification` schema 的合成測試資料，
  不代表真實預測成效，也未寫入線上資料庫。
- 實際執行收集程式，聯電及台積電皆取得 2026-10-30 的 TWSE 行情。
  執行日台北 2026-10-31 為休市日，正確顯示 `outside_capture_day`，不補存預測。

程式已推送至 main；Render 需手動部署對應版本。本機驗證使用隔離 schema，未寫入正式網站紀錄。

## English deployment notes

Configure a PostgreSQL `SCOREBOARD_DATABASE_URL` for both the web service and the
scheduled writer. Run `uv sync --locked`, then
`uv run python -m stockpredict.scoreboard init`. Build and deploy the existing
Docker service. Enable the supplied scoreboard workflow with the matching
repository secret, or schedule `python -m stockpredict.scoreboard run` on your
hosting platform. The first successful pre-open snapshot is immutable; late
jobs never backfill forecasts. Pending actual closes do not affect scores.
Keep the existing US close-data workflow enabled. Browser screenshots use an
isolated local test schema and do not show real prediction performance.
