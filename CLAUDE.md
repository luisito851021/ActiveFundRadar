# ActiveFundRadar — 專案說明

## 專案概述
自動追蹤台灣 6 檔主動型 ETF 每日持倉變化，透過 Telegram / Discord 推送異動明細與 AI 分析摘要。
本機 Windows 執行排程，Web Dashboard 在另一個專案 `C:\ezMoneySniper`（Streamlit Community Cloud）。

## 監控標的（6 檔）
| 代號 | 名稱 | 市場/單位 | 資料來源 | 通知 |
|------|------|-----------|----------|------|
| 00988A | 統一全球創新 | 全球，股 | ezmoney xlsx（code=61YTW，需 Cookie） | TG+DC |
| 00981A | 統一台股增長 | 台股，張 | ezmoney xlsx（code=49YTW，需 Cookie） | TG+DC |
| 00403A | 統一台股升級50 | 台股，張 | ezmoney xlsx（code=63YTW，需 Cookie） | TG+DC |
| 00992A | 群益台灣科技創新 | 台股，張 | Selenium 爬 capitalfund.com.tw | DC only |
| 00991A | 復華未來50 | 台股，張 | fhtrust API（HTTP，免 Cookie） | DC only |
| 00990A | 元大全球AI | 全球，股 | Selenium 爬 yuantaetfs.com | DC only |

台股 1 張 = 1000 股。DC only 名單定義於 notify.py / analyze.py 的 `DISCORD_ONLY_FUNDS`。

## 執行環境
- 本機：Windows，`C:\ActiveFundRadar`，Python + Windows Task Scheduler
- 雲端：Streamlit Community Cloud（ezMoneySniper/app.py）+ Supabase PostgreSQL
- 本機資料庫：SQLite `C:\ActiveFundRadar\etf.db`（同時作為備份）

## 排程（Windows Task Scheduler，2026-07 核實）
| Task 名稱 | 時間 | 指令 |
|-----------|------|------|
| ActiveFundRadar | 17:00 | `python run.py 00988A 00981A 00990A` |
| ActiveFundRadar_00403A | 17:00 | `python run.py 00403A` |
| ActiveFundRadar_00992A | 19:00 | `python run.py 00992A 00991A`（群益 18:00 後才公布） |
| ActiveFundRadar_CrossFund | 19:10 | `python cross_fund.py` |

## 核心架構：雙寫設計
```
run.py（排程，可傳基金代號限定範圍）
  → 假日檢查（TaiwanCalendar JSON，抓取失敗 fail-open 繼續執行）
  → download.py   # 下載持倉 xlsx / 爬蟲
  → main.py       # 解析 xlsx → 雙寫 SQLite + Supabase（db_utils.py）
  → 每檔基金：diff.py → notify.py → analyze.py（皆需傳 DATE FUND_ID）
  → classify.py --push  # 補分類新建倉標的（只處理未分類的，費用極低）
  → discord_log.send_syslog()  # 發送執行報告到 Discord 系統頻道

cross_fund.py（獨立排程）
  # 找出當日被 >1 檔基金異動的標的 → Discord 共振頻道
```

## 資料庫結構（SQLite 與 Supabase 同構）
- **holdings**（每日持倉快照）：fund_id, date, ticker, name, shares, weight（小數，0.05=5%）
- **daily_changes**（每日異動）：fund_id, date, ticker, name, action（建倉/清倉/加碼/減碼）, shares_today/yest, delta_shares, weight_today/yest, delta
- **ticker_categories**（產業分類，classify.py 維護）：ticker PK, name, category, description, color_key, updated_at

## 關鍵決策與陷阱

### 加減碼判斷邏輯
**必須用 `delta_shares`（股數變化），不能用 `delta_w`（權重變化）**
原因：ETF AUM 增長時，股數增加但權重可能下降，用權重判斷會誤判。

### 各檔 xlsx 的日期邏輯
00988A xlsx 內嵌的日期是「前一個交易日」，00981A 是「當日」。
日期應從檔案內容解析（ROC 曆轉西元），不能用 `date.today()`。

### notify.py / analyze.py 的呼叫方式
run.py 呼叫時**必須傳入 fund_id 參數**（`python notify.py DATE FUND_ID`），
避免外層迴圈 × 內層迴圈造成重複發送通知。

### 回補歷史資料時不得發送通知
手動回補（backfill）只跑 download/main/diff，**不要跑 notify/analyze、不要發 Discord/Telegram**。

### SQLite 鎖定問題
用 DB Browser for SQLite 開著 etf.db 時，Python 寫入會失敗。
執行 run.py 前必須關閉 DB Browser。

### Claude Sonnet 5 回傳 ThinkingBlock
`claude-sonnet-5` 的 `resp.content[0]` 可能是 ThinkingBlock（無 `.text`），
取文字要用 `next((b.text for b in resp.content if hasattr(b, "text")), "")`（classify.py 已處理）。

### classify.py 的 ticker 模糊比對
Claude 可能把 "AMD US" 回成 "AMD"、"5706 JP" 回成 "5706"，
`_match_to_batch()` 以首段代號做還原比對，勿移除。

### app.py 的資料庫切換邏輯
環境變數 `IS_CLOUD=true` 讀 Supabase（Streamlit Cloud 設定），否則讀本機 SQLite。

### TWSE API 勿再嘗試
`/rwd/zh/` 系列端點本機全被 block；`ETF_total` NAV 所有已知端點均失敗。收盤價已改用 FinMind。

## 環境變數（.env）
```
ANTHROPIC_API_KEY=...
TELEGRAM_TOKEN=... / TELEGRAM_CHAT_ID=...
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_00988A / _00981A / _00992A / _00403A / _00991A / _00990A=...
DISCORD_CHANNEL_CROSS_FUND=...（cross_fund.py 共振頻道）
DISCORD_SYSLOG_CHANNEL=...（discord_log.py 執行報告）
SUPABASE_URL=postgresql://postgres.xxx:[密碼]@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres
SQLITE_PATH=C:\ActiveFundRadar\etf.db
```
Streamlit Cloud Secrets 額外加：`IS_CLOUD = "true"`

## 開發原則
- 修改要**最小化**：只改必要的地方，不要順手重構不相關的程式碼
- 新功能先在本機 SQLite 驗證，再確認 Supabase 也正常
- 所有金額/權重在 DB 存小數（0.05），顯示時乘以 100 轉成百分比
- Claude API model 一律用 `claude-sonnet-5`
- 繁體中文回應

## 常用指令
```powershell
python run.py                 # 完整流程（全部 6 檔）
python run.py 00992A 00991A   # 限定基金
python notify.py 2026-07-03 00988A   # 單獨測試通知
python analyze.py 2026-07-03 00981A  # 單獨測試 AI 分析
python classify.py --push     # 分類未分類標的並同步 Supabase（--all 強制全部重分類）
python cross_fund.py          # 共振訊號偵測
python migrate.py             # 一次性資料搬移到 Supabase
```
