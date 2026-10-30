# 部署 StockPredict

此專案可部署為單一 Docker 網站服務，不需要資料庫或 API 金鑰。預設使用明確標示的合成示範資料，也能匯入 CSV；Yahoo 資料仍可能受代管平台網路政策或上游限流影響。

## Render 試跑

專案根目錄的 `render.yaml` 定義一個免費 Docker Web Service，健康檢查為 `/api/health`，自動部署已關閉。方案是否適用、可用額度及限制，以建立服務時 Render 顯示的資訊為準；不要在未確認的情況下改選付費方案。

1. 將本專案（含 `Dockerfile`、`render.yaml`、`uv.lock` 與 `stockpredict/`）提交並推送至 `suyanzan/StockPredict` 的部署分支。目前工作區中的未提交檔案不會自動出現在 GitHub。
2. 登入 [Render Dashboard](https://dashboard.render.com/)，連接 GitHub 帳號，授權讀取上述儲存庫。
3. 建立 Blueprint，選擇上述儲存庫及部署分支，使用根目錄的 `render.yaml`。若介面要求方案選擇，確認為 Free。
4. 啟動部署。成功後，開啟 Render 為該服務提供的實際 HTTPS 網址。此網址由平台分配，建立服務前無法確定。
5. 依下列清單驗證網站。不要只以建置成功判斷網站可用。

若不使用 Blueprint，也可以建立 Docker Web Service，選擇同一個儲存庫，設定 Dockerfile 為 `./Dockerfile`、健康檢查為 `/api/health`。應用程式會讀取 Render 提供的 `PORT`，不需另填啟動命令。

免費服務可能在閒置後休眠，第一次開啟會需要等待喚醒；可用性及限制以平台當下規則為準。此設定適合小規模示範。

## 其他 Docker 平台／本機驗證

在專案根目錄執行：

```bash
docker build -t stockpredict:local .
docker run --rm --name stockpredict -p 8000:8000 -e PORT=8000 stockpredict:local
```

可透過設定 `PORT` 更換容器內監聽埠；部署平台需將外部流量送到此埠。映像以非 root 使用者執行，且不包含開發相依套件、Git metadata 或 `.env`。

在 Codex 受管理環境中建置時，需依 cloud-environment-runtime 技能保留代理與 CA 信任設定。例如，使用公開的系統 CA bundle 作為 BuildKit secret：

```bash
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt -t stockpredict:local .
```

這是建置時的信任設定，不會將該檔案存進映像。若容器執行時要透過受管理代理存取 Yahoo，還需依該環境指引掛載 CA 並設定 `SSL_CERT_FILE`；一般網站平台則使用映像內的公開 CA 信任。

## 上線驗證

### 更新既有 Render 服務

本專案的 `render.yaml` 設定 `autoDeploy: false`，因此 GitHub 推送新版本後，既有網站仍需在 Render 服務頁右上角選 **Manual Deploy → Deploy latest commit**。待該筆部署顯示 Live，再重新整理瀏覽器。

台股新增「證交所（上市）」來源後，可點「聯電 2303」或在代碼填 `2303.TW` 並選證交所。需從實際 Render 服務驗證 `www.twse.com.tw` 可用；開發環境的網路設定不會改變 Render 的對外連線。若上游無法使用，保留明確錯誤，CSV 仍可分析。

- `/api/health` 回傳 `{"status":"ok"}`。
- 首頁載入且圖表可見；示範資料清楚標示「非真實行情」。
- 台股與美股快速切換可用，預測期間變更後筆數正確。
- CSV 匯入成功；格式錯誤時顯示可理解的訊息。
- 匯出的 CSV 保留資料來源標記。
- 若 Yahoo 不可用，顯示錯誤且不默默替換成合成資料。

目前沒有使用者帳號、持倉或下單功能；CSV 不會持久寫入伺服器。若要長期公開服務，再依實際流量及需求配置存取控制、流量限制、監控與資料授權。
