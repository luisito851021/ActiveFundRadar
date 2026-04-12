# ActiveFundRadar 🔍

自動追蹤台灣主動型 ETF 每日持倉變化，透過 Telegram 推送異動明細與 AI 選股分析。

## 監控標的

| ETF 代號 | 名稱 |
|---|---|
| 00988A | 統一全球創新 |
| 00981A | 統一台股增長 |

## 功能

- 每日自動下載持倉 xlsx 並寫入 SQLite 資料庫
- 比對前後兩日持倉，偵測建倉／清倉／加碼／減碼
- 透過 Telegram Bot 推送異動明細
- 呼叫 Claude API 分析經理人選股邏輯，自動發送至 Telegram
- Streamlit 網頁介面查看當日異動與歷史記錄

## 專案結構

```
ActiveFundRadar/
├── run.py            # 主排程，依序執行所有步驟
├── download.py       # 下載 ETF 持倉 xlsx
├── main.py           # 解析 xlsx 並寫入資料庫
├── diff.py           # 比對持倉差異
├── notify.py         # 格式化並發送 Telegram 通知
├── analyze.py        # 呼叫 Claude API 進行選股分析
├── app.py            # Streamlit 網頁介面
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
TELEGRAM_TOKEN=你的_Telegram_Bot_Token
TELEGRAM_CHAT_ID=你的_Chat_ID
ANTHROPIC_API_KEY=你的_Anthropic_API_Key
```

### 3. 初始化資料庫

```bash
python init_db.py
```

### 4. 更新 Cookie

`download.py` 需要有效的 ezmoney.com.tw Cookie，從 Chrome DevTools 複製後更新 `COOKIES` 區塊。

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

### 啟動網頁介面

```bash
python -m streamlit run app.py
```

## 自動排程

使用 Windows 工作排程器，設定每個交易日執行 `run.py`。

## 注意事項

- `.env`、`etf.db`、`Files/` 資料夾均不進版本控制
- Cookie 有效期約數天，過期需手動更新
- 00981A 持股單位為張（1張=1000股），00988A 為股
