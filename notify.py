import sqlite3
import pandas as pd
import requests
import re
from datetime import date
import sys
import os
from dotenv import load_dotenv

WEB_URL = "https://ezmoneysniper.streamlit.app"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()



# ── 設定區 ────────────────────────────────────────
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID")
DISCORD_BOT_TOKEN  = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNELS = {
    "00988A": os.getenv("DISCORD_CHANNEL_00988A"),
    "00981A": os.getenv("DISCORD_CHANNEL_00981A"),
    "00992A": os.getenv("DISCORD_CHANNEL_00992A"),
    "00403A": os.getenv("DISCORD_CHANNEL_00403A"),
    "00991A": os.getenv("DISCORD_CHANNEL_00991A"),
    "00990A": os.getenv("DISCORD_CHANNEL_00990A"),
    "00411A": os.getenv("DISCORD_CHANNEL_00411A"),
    "00987D": os.getenv("DISCORD_CHANNEL_00987D"),
}

# 只發 Discord、不發 Telegram 的基金
DISCORD_ONLY_FUNDS = {"00992A", "00990A", "00991A"}

def unit_spec(fund_id: str, ticker: str):
    """
    回傳 (標題文字, 數值後綴, 除數)。
    台股基金持股單位為張（1 張 = 1000 股）；
    00987D 是債券量化 ETF，債券記面額、期貨記口數，兩者都存在 shares 欄位，
    以 ticker 是否帶契約年月（含「/」）區分——債券代號是 ISIN，不會出現「/」。
    """
    if fund_id in ("00981A", "00992A", "00403A", "00991A"):
        return "張數", "張", 1000
    if fund_id == "00987D":
        return ("口數", "口", 1) if "/" in ticker else ("面額", "", 1)
    return "股數", "股", 1


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    })
    if resp.status_code == 200:
        print("[Telegram] 發送成功")
    else:
        print(f"[Telegram] 發送失敗：{resp.text}")

def send_discord(message: str, fund_id: str):
    channel_id = DISCORD_CHANNELS.get(fund_id)
    if not DISCORD_BOT_TOKEN or not channel_id:
        print("[Discord] 未設定 Token 或 Channel ID，跳過")
        return
    plain = message.replace("<b>", "**").replace("</b>", "**")
    plain = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"[\2](\1)", plain)
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    chunks = [plain[i:i+2000] for i in range(0, len(plain), 2000)]
    for chunk in chunks:
        resp = requests.post(url, headers=headers, json={"content": chunk})
        if resp.status_code in (200, 201):
            print("[Discord] 發送成功")
        else:
            print(f"[Discord] 發送失敗：{resp.text}")

def already_sent(conn, fund_id: str, target_date: str, kind: str = "notify") -> bool:
    """檢查該基金該日期是否已經發送過通知，避免來源網站卡住不更新時重複發送舊資料"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notify_log (
            fund_id TEXT NOT NULL,
            date    TEXT NOT NULL,
            kind    TEXT NOT NULL,
            PRIMARY KEY (fund_id, date, kind)
        )
    """)
    row = conn.execute(
        "SELECT COUNT(*) FROM notify_log WHERE fund_id=? AND date=? AND kind=?",
        (fund_id, target_date, kind),
    ).fetchone()
    return row[0] > 0

def mark_sent(conn, fund_id: str, target_date: str, kind: str = "notify"):
    conn.execute(
        "INSERT OR IGNORE INTO notify_log (fund_id, date, kind) VALUES (?, ?, ?)",
        (fund_id, target_date, kind),
    )
    conn.commit()

def get_holdings_count(conn, target_date: str, fund_id: str) -> int:
    """取得 holdings 表中 ≤ target_date 的最新日期持倉總數"""
    result = pd.read_sql(f"""
        SELECT COUNT(*) AS cnt FROM holdings
        WHERE fund_id = '{fund_id}'
          AND date = (
              SELECT date FROM holdings
              WHERE fund_id = '{fund_id}' AND date <= '{target_date}'
              ORDER BY date DESC LIMIT 1
          )
    """, conn)
    return int(result.iloc[0]["cnt"])

def get_daily_changes(conn, target_date: str, fund_id: str) -> pd.DataFrame:
    return pd.read_sql(f"""
        SELECT
            date, ticker, name, action,
            delta_shares, shares_today, shares_yest,
            ROUND(weight_today * 100, 2) AS weight_today,
            ROUND(weight_yest  * 100, 2) AS weight_yest,
            ROUND(delta        * 100, 2) AS delta
        FROM daily_changes
        WHERE date = '{target_date}' AND fund_id = '{fund_id}'
    """, conn)

def get_flag(ticker: str) -> str:
    """根據 ticker 後綴（市場代碼）回傳國旗 emoji"""
    suffix = ticker.strip().split()[-1].upper()
    return {
        "US": "🇺🇸",
        "JP": "🇯🇵",
        "KS": "🇰🇷",
        "GY": "🇩🇪",
        "HK": "🇭🇰",
        "FP": "🇫🇷",
        "LN": "🇬🇧",
        "KP": "🇰🇷",
        "GR": "🇩🇪",
        "CH": "🇨🇳",   # 中國 A 股（上海/深圳）
        "NA": "🇳🇱",   # 荷蘭（阿姆斯特丹）
    }.get(suffix, "🇹🇼")  # 純數字台股或其他預設台灣

_MARKET_SUFFIX = {
    "US": "",
    "JP": ".T",
    "KS": ".KS",
    "KP": ".KS",
    "GY": ".DE",
    "GR": ".DE",
    "HK": ".HK",
    "FP": ".PA",
    "LN": ".L",
    "NA": ".AS",   # 荷蘭阿姆斯特丹
    "TW": ".TW",
}

def to_yahoo_ticker(bloomberg_ticker: str) -> str:
    parts = bloomberg_ticker.strip().split()
    base = parts[0]
    suffix = parts[1].upper() if len(parts) > 1 else ""
    if not suffix and base.isdigit():
        return base + ".TW"
    if suffix == "CH":  # 中國 A 股：6 開頭滬市 .SS，其餘（0/3）深市 .SZ
        return base + (".SS" if base.startswith("6") else ".SZ")
    return base + _MARKET_SUFFIX.get(suffix, "")

def fetch_price_changes(bloomberg_tickers: list) -> dict:
    """批次抓取 Yahoo Finance 當日漲幅，回傳 {bloomberg_ticker: '+3.24%'}"""
    yahoo_to_bb = {}
    for bt in bloomberg_tickers:
        yt = to_yahoo_ticker(bt)
        if yt:
            yahoo_to_bb[yt] = bt

    if not yahoo_to_bb:
        return {}

    try:
        import yfinance as yf
        import pandas as pd

        yt_list = list(yahoo_to_bb.keys())
        raw = yf.download(yt_list, period="5d", auto_adjust=True, progress=False)

        if isinstance(raw.columns, pd.MultiIndex):
            close = raw["Close"]
        else:
            close = raw[["Close"]].rename(columns={"Close": yt_list[0]})

        result = {}
        for yt, bt in yahoo_to_bb.items():
            if yt not in close.columns:
                continue
            series = close[yt].dropna()
            if len(series) < 2:
                continue
            prev, curr = series.iloc[-2], series.iloc[-1]
            if prev > 0:
                val = (curr - prev) / prev * 100
                result[bt] = f"{'+' if val >= 0 else ''}{val:.2f}%"
        return result
    except Exception as e:
        print(f"[yfinance] 抓取失敗：{e}")
        return {}

def format_message(df: pd.DataFrame, target_date: str, fund_id: str = "00988A", conn=None) -> str:
    if df.empty:
        return f"📊 <b>{target_date} {fund_id} 持倉異動</b>\n\n今日無異動"

    # ── 統計 ──────────────────────────────────────
    total   = get_holdings_count(conn, target_date, fund_id) if conn else "?"
    n_new   = len(df[df["action"] == "建倉"])
    n_add   = len(df[df["action"] == "加碼"])
    n_cut   = len(df[df["action"] == "減碼"])
    n_close = len(df[df["action"] == "清倉"])

    # ── 00988A 批次抓取 Yahoo Finance 漲幅 ────────
    price_changes = {}
    if fund_id in ("00988A", "00990A", "00411A"):
        print("[yfinance] 抓取持股漲幅中...")
        price_changes = fetch_price_changes(df["ticker"].tolist())

    lines = [
        f"📊 <b>{target_date} {fund_id} 持倉異動</b>",
        f"持股{total}檔、新增{n_new}檔、加碼{n_add}檔、減碼{n_cut}檔、清倉{n_close}檔\n",
    ]

    for action, symbol in [("建倉", "🟢"), ("清倉", "🔴"), ("加碼", "📈"), ("減碼", "📉")]:
        subset = df[df["action"] == action].copy()
        if subset.empty:
            continue

        # 各區塊內按股數變化絕對值降序排列
        subset = subset.reindex(
            subset["delta_shares"].abs().sort_values(ascending=False).index
        )

        lines.append(f"{symbol} <b>{action}</b>")
        for _, row in subset.iterrows():
            unit_label, unit, div = unit_spec(fund_id, row['ticker'])
            shares_t = int(row['shares_today']) // div
            shares_y = int(row['shares_yest'])  // div
            delta_s  = int(row['delta_shares']) // div

            flag   = get_flag(row['ticker']) if fund_id in ("00988A", "00990A", "00411A") else ""
            prefix = f"{flag} " if flag else ""
            pct_str = price_changes.get(row['ticker'], "")
            pct_part = f"  漲幅：{pct_str}\n" if pct_str else ""

            if action in ("建倉", "清倉"):
                lines.append(
                    f"  {prefix}{row['ticker']} {row['name']}\n"
                    f"  {unit_label}：{shares_t:,}{unit}  權重：{row['weight_today']}%\n"
                    f"{pct_part}"
                )
            else:
                sign = "+" if delta_s > 0 else ""
                lines.append(
                    f"  {prefix}{row['ticker']} {row['name']}\n"
                    f"  {unit_label}：{sign}{delta_s:,}{unit} "
                    f"({shares_y:,}→{shares_t:,})\n"
                    f"  權重：{row['weight_yest']}%→{row['weight_today']}%"
                    f"（{'+' if row['delta']>0 else ''}{row['delta']}%）\n"
                    f"{pct_part}"
                )
        lines.append("")

    lines.append(f'🔗 <a href="{WEB_URL}">查看完整持倉 → ezMoneySniper</a>')
    return "\n".join(lines)

if __name__ == "__main__":
    FUNDS = ["00988A", "00981A", "00992A", "00403A", "00991A", "00990A", "00411A", "00987D"]

    if len(sys.argv) == 3:
        target_date = sys.argv[1]
        FUNDS = [sys.argv[2]]
    elif len(sys.argv) == 2:
        target_date = sys.argv[1]
    else:
        target_date = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect("etf.db")

    for fund_id in FUNDS:
        if already_sent(conn, fund_id, target_date, "notify"):
            print(f"[跳過] {fund_id} {target_date} 已經發送過通知，不重複發送")
            continue

        df = get_daily_changes(conn, target_date, fund_id)
        message = format_message(df, target_date, fund_id, conn=conn)
        print(message)
        if fund_id not in DISCORD_ONLY_FUNDS:
            send_telegram(message)
        send_discord(message, fund_id)
        mark_sent(conn, fund_id, target_date, "notify")

    conn.close()