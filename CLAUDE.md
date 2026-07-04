# ActiveFundRadar — 專案說明

## 專案概述
自動追蹤台灣兩檔主動型 ETF 每日持倉變化，透過 Telegram 推送異動明細與 AI 分析摘要。
本機 Windows 執行排程，Streamlit Community Cloud 提供手機可瀏覽的 Web Dashboard。

## 監控標的
- **00988A** 統一全球創新：全球股票（美、日、韓、德），持股單位為「股」
- **00981A** 統一台股增長：台灣上市公司，持股單位為「張」（1張=1000股）

## 執行環境
- 本機：Windows，路徑 `C:\ActiveFundRadar`，Python + Windows Task Scheduler
- 雲端：Streamlit Community Cloud（app.py）+ Supabase PostgreSQL（資料庫）
- 本機資料庫：SQLite `C:\ActiveFundRadar\etf.db`（同時作為備份）

## 核心架構：雙寫設計
```
run.py（排程）
  → download.py   # 下載 ETF xlsx
  → main.py       # 解析 xlsx → 雙寫 SQLite + Supabase（透過 db_utils.py）
  → diff.py       # 比對持倉差異 → 雙寫 SQLite + Supabase
  → notify.py     # 格式化 Telegram 通知（單檔執行：傳入 date + fund_id）
  → analyze.py    # 呼叫 Claude API 分析 → 發送 Telegram（單檔執行）
```

## 資料庫結構
### holdings（每日完整持倉快照）
| 欄位 | 型別 | 說明 |
|------|------|------|
| fund_id | TEXT | 00988A / 00981A |
| date | TEXT | YYYY-MM-DD |
| ticker | TEXT | 股票代號 |
| name | TEXT | 股票名稱 |
| shares | INTEGER | 持股股數 |
| weight | REAL | 持股權重（小數，如 0.05 = 5%） |

### daily_changes（每日持倉異動）
| 欄位 | 說明 |
|------|------|
| fund_id, date, ticker, name | 基本資訊 |
| action | 建倉 / 清倉 / 加碼 / 減碼 |
| shares_today, shares_yest, delta_shares | 股數 |
| weight_today, weight_yest, delta | 權重（小數） |

## 關鍵決策與陷阱

### 加減碼判斷邏輯
**必須用 `delta_shares`（股數變化），不能用 `delta_w`（權重變化）**
原因：ETF AUM 增長時，股數增加但權重可能下降，用權重判斷會誤判。

### 00988A 的日期邏輯
00988A xlsx 內嵌的日期是「前一個交易日」，00981A 是「當日」。
日期應從 xlsx 檔案內容解析（ROC 曆轉西元），不能用 `date.today()`。

### notify.py / analyze.py 的呼叫方式
run.py 呼叫時**必須傳入 fund_id 參數**（`python notify.py DATE FUND_ID`），
避免外層迴圈 × 內層迴圈造成重複發送通知。

### SQLite 鎖定問題
用 DB Browser for SQLite 開著 etf.db 時，Python 寫入會失敗。
執行 run.py 前必須關閉 DB Browser。

### app.py 的資料庫切換邏輯
透過環境變數 `IS_CLOUD` 控制：
- `IS_CLOUD=true`：讀 Supabase（Streamlit Cloud 設定）
- 未設定或 false：讀本機 SQLite

## 環境變數（.env）
```
ANTHROPIC_API_KEY=...
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
SUPABASE_URL=postgresql://postgres.xxx:[密碼]@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres
SQLITE_PATH=C:\ActiveFundRadar\etf.db
```
Streamlit Cloud Secrets 額外加：`IS_CLOUD = "true"`

## 開發原則
- 修改要**最小化**：只改必要的地方，不要順手重構不相關的程式碼
- 新功能先在本機 SQLite 驗證，再確認 Supabase 也正常
- 所有金額/權重在 DB 存小數（0.05），顯示時乘以 100 轉成百分比
- 繁體中文回應

## 常用指令
```powershell
# 啟動 Streamlit（本機）
python -m streamlit run app.py

# 手動執行完整流程
python run.py

# 一次性資料搬移到 Supabase
python migrate.py

# 單獨測試某檔 ETF 通知
python notify.py 2026-04-14 00988A
python analyze.py 2026-04-14 00981A
```
