# 自動更新美股收盤 CSV

網站預設的「自動收盤資料」由共用 CSV 提供，訪客不需要下載或上傳檔案。資料仍來自 Yahoo，但由獨立排程取得一次，網站讀取已驗證的快照；不再讓每位訪客直接向 Yahoo 請求美股行情。

## 更新時程

GitHub Actions 的 **Update completed US market CSVs** 於週一至週五 UTC 20:30、21:30 執行，對應台北次日 04:30、05:30。程式先確認紐約時間已過 16:15；夏令時間通常第一個時段可更新，冬令時間第一個時段不下載、第二個時段才更新。排程可能延遲，不能保證準時公布。

每次只處理 UMC、TSM、SOXX、SPY、QQQ，依序請求且間隔至少 3 秒；五檔都必須包含當天完整收盤價，才會發布。已驗證的當日快照存在時，後續執行不再請求 Yahoo。遇到限流、資料未公布或美國休市，不發布假更新、不切換出口、不密集重試，既有快照的交易日期不會被改成今天。

## 資料與網站如何連接

- 程式與工作流程位於 `main`；CSV 與 `manifest.json` 位於獨立的 `market-data` 分支。
- 每份快照有不可變路徑，manifest 記錄來源、交易日、產生時間、筆數及檔案雜湊；提交一次發布整份快照，保留最多五份之前的快照。
- Render 固定讀取此專案的公開資料分支，驗證檔案內容與日期。快取可減少下載，但不允許將前一個交易日當成本次所需交易日。
- 未收盤時不讀取美股 CSV。當天資料缺失時，網站顯示尚不可用，保留原 AR(5) 分析。
- 新程式第一次仍需部署 Render；之後排程更新 CSV **不需要重新部署網站**。

資料分支只包含公開行情，不包含網站環境變數、資料庫連線或管理金鑰。更新工作使用 GitHub 自動提供的 `GITHUB_TOKEN`，只有該工作要求 repository contents 寫入權限；腳本只推送資料分支，不改動主分支。使用標準 `ubuntu-latest` runner，沒有新增付費服務或外部行情帳號。

## 查看或手動執行

在 GitHub 專案的 **Actions → Update completed US market CSVs** 查看最近結果；需要時可選 **Run workflow**。若 GitHub 停用了排程或不允許工作寫入 repository，需在專案設定恢復對應權限。

網站仍保留「Yahoo 直接取得」及「手動匯入 CSV」兩種明確選項。自動快照缺資料時不會偷偷改用其他來源。即使排程也收到 Yahoo 429，網站會如實顯示未更新；自動化無法保證供應商永遠提供資料。

## 本機驗證

```bash
uv run --no-sync python -m stockpredict.refresh_market_data --output-dir /tmp/stockpredict-closes
uv run --no-sync pytest -q tests/test_refresh_market_data.py tests/test_auto_csv.py tests/test_auto_csv_api.py
```

讀取 API 時使用 `market_context=us_overnight&factor_source=auto_csv`。回應的 `market_context.data_source` 為 `auto_csv`；資料可用時另含 `snapshot_metadata` 的實際交易日與產生時間。舊 API 未指定 `factor_source` 時仍維持直接 Yahoo 行為，網頁則預設自動 CSV。
