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
  # TEST_POSTGRES_URL 必須指向獨立測試資料庫，禁止使用正式 Neon。
   uv run pytest -q
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


## V1.1 reliability 修補與正式驗收

本節描述待部署的程式變更，不代表正式環境已更新。

- 真實台股及紐約行情缺少應有交易日時，分析 API 回傳 503、來源日期及空預測。
  前端刷新失敗會隱藏先前結果；CSV／示範模式不套用即時行情門檻。
- `--strict` 納入 ADR 來源錯誤。交易日開盤後若當日純台股預測尚未封存，
  即使實際值收集成功仍回傳失敗；已封存的盤後工作不因逾時而誤報。
  休市日不要求新預測，仍保留遲到不回填的規則。
- 看板、歷史回測與配對比較的摘要補上 RMSE；空樣本為 null。
- 獨立健康查詢只讀必要日期與實際值是否存在，不傳輸完整歷史快照或重新計算模型指標。

排程啟用前應核對 Web／收集器的部署 SHA 與資料庫目標。選定主要盤前排程：
若使用 Render Cron，先確認服務已啟用且成功執行，再停用重複的盤前 Actions 時段；
必須保留盤後收集與獨立監控。Repository 中存在 Blueprint 不代表 Render 已建立服務。
本次沒有更改任何正式排程、部署或 Neon 設定。

測試必須使用獨立 PostgreSQL。整合測試會建立並刪除隨機 schema，禁止對正式資料庫執行。
Web 看板讀取可用 SELECT；回測保存另需對 sp_backtest_runs 的 SELECT、INSERT 權限，
初始化由管理角色執行，不應為了保存回測而授予 Web 建表權限。

正式驗收需連續五個交易日確認：09:00 前保存必要預測、重跑無重複、盤後取得精確日期收盤、
故障通知送達並可追蹤；目前本機測試不替代這段正式觀察。
修改模型／評分來源雜湊會使舊回測封存的 replay 相容性檢查拒絕使用新引擎重播，
舊封存與匯出內容維持不變。


### 排程切換與版本比對

CLI 現支援 `--phase preopen`（盤前）、`--phase close`（只收實際值，不產生預測），
預設 `all` 保留既有手動使用方式。兩種工作在開盤後皆會揭露當日純台股預測是否漏收。
排程延誤超過截止時間不會補存；任務退出失敗表示需處理，不可直接重跑補造盤前成績。

GitHub workflow 按排程來源選擇 phase；手動執行可明確選擇 phase。
Render Blueprint 僅準備盤前工作，沒有在本次建立或啟用任何付費服務。
確認 Render 正確執行後，才將 Repository variable `SCOREBOARD_PREOPEN_PROVIDER` 設為 `render`：
此設定只略過 GitHub 的盤前自動工作，保留盤後與手動工作。
變數未設定時維持 GitHub 原有行為；切換回 GitHub 時先停用 Render 盤前工作，再清除變數。
跨平台唯一鍵保護仍在，但切換期間應檢查是否有重複執行。

`GET /api/health` 新增 `release.commit` 與 `release.source_hash`。
commit 僅接受 Render／GitHub 提供的 40 位十六進位 SHA，未知時為 null；source_hash
涵蓋目前套件 Python、JS、CSS、HTML 檔案，不輸出環境變數或檔案內容。
收集檢查紀錄同樣保存 phase、release，供比對 Web 與收集器版本。
已啟動程序應透過部署／重新啟動載入新程式，不能直接覆寫執行中的檔案。

正式驗收應先核對兩端 SHA 與 source_hash，再觀察五交易日，不應僅以工作顯示 success
或網站 liveness 200 判定盤前收集完成。

### 本地修補驗證結果

- 最終完整 Pytest：688 passed，9 項既有棄用警告；無跳過。
- PostgreSQL 使用獨立、臨時的本機 Docker 容器，未連線正式 Neon。
- Ruff lint、63 個 Python 檔案格式檢查與 git diff whitespace 檢查通過。
- Workflow YAML、盤前／盤後／手動 phase 路由與 Render Blueprint phase 檢查通過。
- Docker 映像建置通過；以非 root 啟動驗證健康 API、no-store、示範分析，
  以及儲存未設定時的健康 API 503；映像與工作目錄 source_hash 一致。
- 前一輪 Chromium 驗證刷新失敗後隱藏舊預測，無 JavaScript 執行錯誤。
- 尚未 Push、正式部署或切換排程；正式五交易日觀察尚未開始。
