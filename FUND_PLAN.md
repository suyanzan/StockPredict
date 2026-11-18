# 私人 0050 資金計畫（/plan）

站主專用頁面，使用與 `/admin` 相同的 `COMMUNITY_ADMIN_TOKEN`；`noindex` 且不快取。

- 登入：以金鑰呼叫 `POST /api/plan/session` 後，伺服器設定 7 天的 `sp_plan_owner` Cookie（HttpOnly、SameSite=Strict、Render 上為 Secure、Path=/api/plan）。Cookie 只含到期時間與以金鑰計算的 HMAC 簽章，不含金鑰本身；資料庫不需保存 session。
- 到期、按「登出這台裝置」（`DELETE /api/plan/session`）或在 Render 更換金鑰後，所有登入立即失效，需重新輸入金鑰。此登入只適用 `/plan`，不影響 `/admin`。

- 金額、資金分配、原有持股與買入紀錄只存在使用者瀏覽器的 localStorage（`stockpredict.plan.v1`），不送往伺服器、不寫入資料庫或 GitHub。
- `GET /api/plan/0050`（需 Bearer 金鑰）只回傳以「1 單位資金」計算的百分比：0050 歷史最大跌幅與回本時間、一次投入 vs 分批買入、衛星比例 0／10／20% 的套利規則回測。
- 價格來源為 Yahoo `0050.TW` 最長歷史（保留最近 5000 個交易日），已反映分割、不含配息；每個程序快取 6 小時。手續費 0.1425%、賣出加計 0.1% ETF 證交稅，不計最低手續費。
- 衛星規則：起始全數買進；價格達參考價 +X% 時賣出設定比例換回現金；之後從賣價下跌 Y% 時以全部現金買回；每次交易更新參考價。
- 歷史模擬不代表未來，也不是投資建議。
