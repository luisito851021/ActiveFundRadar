# ActiveFundRadar 🔍

自動追蹤台灣主動型 ETF 每日持倉變化，透過 Telegram 與 Discord 推送異動明細與 AI 選股分析。

網頁查詢介面請見 [ezMoneySniper](https://github.com/luisito851021/ezMoneySniper)。

## 監控標的

| ETF 代號 | 名稱 | 通知管道 |
|---|---|---|
| 00988A | 統一全球創新 | Telegram + Discord |
| 00981A | 統一台股增長 | Telegram + Discord |
| 00403A | 統一台股升級50 | Telegram + Discord |
| 00992A | 群益台灣科技創新 | Discord 限定 |
| 00991A | 復華未來50 | Discord 限定 |
| 00990A | 元大全球AI | Discord 限定 |
| 00411A | 統一前沿科技 | Telegram + Discord |
| 00987D | 統一美債量化 | Telegram + Discord |

## 功能

- 每日自動下載持倉 xlsx 並寫入 SQLite 資料庫（同步備份至 Supabase）
- 比對前後兩日持倉，偵測建倉／清倉／加碼／減碼
- 透過 Telegram / Discord Bot 推送異動明細（各基金對應獨立頻道）
- 呼叫 Claude API 分析經理人選股邏輯，同步發送至 Telegram 與 Discord
- 持倉標的產業分類（Claude API，`ticker_categories` 表），每日自動補分類新建倉標的
- 跨基金共振訊號偵測（當日被多檔基金同時異動的標的）
- 每次執行後發送執行報告到 Discord 系統頻道

## 專案結構

```
ActiveFundRadar/
├── run.py            # 主排程，依序執行所有步驟
├── download.py       # 下載 ETF 持倉 xlsx
├── main.py           # 解析 xlsx 並寫入資料庫
├── diff.py           # 比對持倉差異
├── notify.py         # 格式化並發送 Telegram / Discord 通知
├── analyze.py        # 呼叫 Claude API 進行選股分析並推送
├── classify.py       # 持倉標的產業分類（Claude API）
├── cross_fund.py     # 跨基金共振訊號偵測（獨立排程）
├── discord_log.py    # 執行報告發送到 Discord 系統頻道
├── db_utils.py       # SQLite + Supabase 雙寫工具
├── init_db.py        # 初始化 SQLite 資料庫
├── requirements.txt
├── .env              # 敏感設定（不進 Git）
└── .gitignore
```

## 安裝與設定

### 1. 安裝套件

```bash
pip install -r requirements.txt
```

### 2. 建立 .env 檔案

在專案根目錄建立 `.env`，填入以下內容：

```
ANTHROPIC_API_KEY=你的_Anthropic_API_Key

TELEGRAM_TOKEN=你的_Telegram_Bot_Token
TELEGRAM_CHAT_ID=你的_Chat_ID

DISCORD_BOT_TOKEN=你的_Discord_Bot_Token
DISCORD_CHANNEL_00988A=各基金對應的頻道_ID（00981A/00992A/00403A/00991A/00990A/00411A/00987D 同理）
DISCORD_CHANNEL_CROSS_FUND=共振訊號頻道_ID
DISCORD_SYSLOG_CHANNEL=執行報告頻道_ID

SUPABASE_URL=postgresql://...
SQLITE_PATH=C:\ActiveFundRadar\etf.db
```

### 3. 初始化資料庫

```bash
python init_db.py
```

### 4. 更新 Cookie

`download.py` 需要有效的 ezmoney.com.tw Cookie，從 Chrome DevTools 複製後更新 `COOKIES` 區塊。

### 5. Discord Bot 設定

1. 至 [Discord Developer Portal](https://discord.com/developers/applications) 建立 Bot
2. 開啟 `MESSAGE CONTENT INTENT`
3. 使用以下連結邀請 Bot 加入伺服器（需 `Send Messages` 權限）：
   ```
   https://discord.com/oauth2/authorize?client_id=你的_CLIENT_ID&permissions=2048&scope=bot
   ```
4. 右鍵各頻道 → 複製頻道 ID，填入 `.env`（需先開啟 Discord 開發者模式）

## 執行方式

### 手動執行完整流程

```bash
python run.py
```

### 單獨執行各步驟

```bash
python download.py                        # 下載 xlsx
python main.py                            # 寫入資料庫
python diff.py                            # 比對異動
python notify.py 2026-04-01 00988A        # 發送通知
python analyze.py 2026-04-01 00988A       # AI 分析
```

## 自動排程

使用 Windows 工作排程器，設定每個交易日執行 `run.py`。

## 注意事項

- `.env`、`etf.db`、`Files/` 資料夾均不進版本控制
- 00988A、00990A、00411A 為全球股票（持股單位：股）；00981A、00403A、00992A、00991A 為台灣股票（持股單位：張，1張=1000股）
- 00987D 為債券型（美債量化），持倉分成債券（記面額）與美債期貨（記口數），兩者都寫進 `holdings`，期貨 ticker 帶契約年月（如 `UB 2026/12`）
- 00992A、00990A 使用 Selenium + ChromeDriver 下載，chromedriver.exe 需手動放置於專案根目錄
- Claude API Token 消耗量會於每次分析後印出至 console
- 網頁查詢介面請使用 [ezMoneySniper](https://github.com/luisito851021/ezMoneySniper)
