# 免費資料庫與私人留言設定

行情分析及中英文切換不需要資料庫。**瀏覽統計與留言**需要外部資料庫，才能在 Render 免費網站休眠、重啟或重新部署後保留資料。這裡使用 Neon 的 PostgreSQL Free 方案；可用方案與額度以建立時 Neon 顯示的資訊為準，本次沒有建立任何付費資源。

## 1. 建立 Neon 專案

1. 前往 [Neon Console](https://console.neon.tech/) 註冊或登入。
2. 建立專案，名稱可用 `stockpredict`，選擇 **Free** 方案及接近 Render 的地區。
3. 開啟專案的 **Connect／Connection Details**，選擇 PostgreSQL 連線資訊。可使用 Pooled connection。
4. 複製完整的 PostgreSQL connection string，保留平台提供的 SSL 參數（例如 `sslmode=require`）。

連線字串包含資料庫密碼。**只貼到下一步 Render 的環境變數欄位，不要放進 GitHub、留言、截圖或聊天。** 不需手動建表；網站在首次存取時自動建立本功能的兩張資料表。

## 2. 在 Render 設定

開啟 Render 的 `stockpredict` 服務 → **Environment**，新增：

| Key | Value |
| --- | --- |
| `COMMUNITY_DATABASE_URL` | Neon 提供的完整 PostgreSQL 連線字串 |
| `COMMUNITY_ADMIN_TOKEN` | 使用密碼管理器產生的至少 32 字元隨機英文、數字或符號字串，保留給自己 |
| `COMMUNITY_MODERATION` | `private` |

管理金鑰用來查看、標記處理及刪除私人建議。它與資料庫密碼不同，不會寫入程式碼，管理頁也不會存到瀏覽器儲存空間。請在密碼管理器中保留一份。

**不要在 Render 免費方案設定 `COMMUNITY_SQLITE_PATH`**。該服務的本機檔案不保證在重新部署後保留；PostgreSQL 連線已提供持久儲存，不需要 SQLite。

儲存環境變數後，部署 GitHub 最新版本。此專案關閉自動部署，因此在 **Deploys → Manual Deploy → Deploy latest commit** 執行，等待新版本顯示 **Live**。

## 3. 驗證網站

1. 開啟 [StockPredict](https://stockpredict-xwar.onrender.com/)，必要時按 Ctrl＋F5。
2. 下方應顯示實際「瀏覽次數」與「不重複瀏覽器」。重新載入會增加瀏覽次數；同一瀏覽器不會增加不重複瀏覽器數。
3. 切換語言、重做行情分析不應增加瀏覽次數。語言偏好會保存在該瀏覽器。
4. 送出一則測試建議，確認顯示「只有網站擁有者能查看」，且首頁不會公開留言內容。
5. 開啟 [私人建議管理頁](https://stockpredict-xwar.onrender.com/admin)，輸入 `COMMUNITY_ADMIN_TOKEN` 的值，即可查看、標記已處理或刪除。登出／重新整理後需再次輸入金鑰。
6. 再部署或重新啟動 Render，確認統計與建議仍在。Neon 資料庫本身須持續存在。

統計從啟用功能時開始累計，無法回推之前沒有記錄的訪客。使用匿名 Cookie 估算不重複瀏覽器，不代表實際人數；刪除 Cookie、使用不同瀏覽器或裝置會被視為另一個瀏覽器。服務只儲存 Cookie 的雜湊識別，不將 IP 或 User-Agent 寫進本功能的資料表。

## 如果顯示尚未啟用或暫時無法使用

- **尚未啟用**：檢查 Render 是否設定 `COMMUNITY_DATABASE_URL`，並確定網站已部署新版本。
- **暫時無法使用**：檢查 Neon 專案仍可連線、完整連線字串及 SSL 參數未缺漏。免費服務喚醒時可稍後重新讀取。
- **管理功能尚未設定**：檢查 `COMMUNITY_ADMIN_TOKEN` 是否至少 32 個字元，並重新部署。
- **金鑰無效**：使用管理金鑰，不是 Neon 資料庫密碼；不要將金鑰放在網址。

資料庫尚未設定或失敗時，網站顯示 `—` 與狀態訊息，行情分析仍可使用。管理 API 的錯誤會隱藏連線字串與密碼。

## 本機開發

可使用明確指定的 SQLite 檔案，不需要建立外部帳號：

```bash
COMMUNITY_SQLITE_PATH=/workspace/.stockpredict/community.sqlite3 \
COMMUNITY_MODERATION=private \
uv run --no-sync uvicorn stockpredict.main:app --host 0.0.0.0 --port 8000
```

這個檔案會在應用程式重啟後保留，但實際保存期限仍取決於所在磁碟。管理頁仍需透過環境變數提供 `COMMUNITY_ADMIN_TOKEN`。不要將真實金鑰或 SQLite 資料檔提交到 Git。
