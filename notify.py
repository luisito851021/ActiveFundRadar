import sqlite3
import pandas as pd
import requests
from datetime import date
import sys
import os
from dotenv import load_dotenv

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
}

# 只發 Discord、不發 Telegram 的基金
DISCORD_ONLY_FUNDS = {"00992A"}

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
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    chunks = [plain[i:i+2000] for i in range(0, len(plain), 2000)]
    for chunk in chunks:
        resp = requests.post(url, headers=headers, json={"content": chunk})
        if resp.status_code in (200, 201):
            print("[Discord] 發送成功")
        else:
            print(f"[Discord] 發送失敗：{resp.text}")

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
    }.get(suffix, "🇹🇼")  # 純數字台股或其他預設台灣

def format_message(df: pd.DataFrame, target_date: str, fund_id: str = "00988A", conn=None) -> str:
    if df.empty:
        return f"📊 <b>{target_date} {fund_id} 持倉異動</b>\n\n今日無異動"

    # ── 統計 ──────────────────────────────────────
    total   = get_holdings_count(conn, target_date, fund_id) if conn else "?"
    n_new   = len(df[df["action"] == "建倉"])
    n_add   = len(df[df["action"] == "加碼"])
    n_cut   = len(df[df["action"] == "減碼"])
    n_close = len(df[df["action"] == "清倉"])

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
            # 00981A 台股用張（1張=1000股），00988A 用股
            if fund_id in ("00981A", "00992A"):
                unit       = "張"
                shares_t   = int(row['shares_today']) // 1000
                shares_y   = int(row['shares_yest'])  // 1000
                delta_s    = int(row['delta_shares'])  // 1000
            else:
                unit       = "股"
                shares_t   = int(row['shares_today'])
                shares_y   = int(row['shares_yest'])
                delta_s    = int(row['delta_shares'])

            flag   = get_flag(row['ticker']) if fund_id == "00988A" else ""
            prefix = f"{flag} " if flag else ""

            if action in ("建倉", "清倉"):
                lines.append(
                    f"  {prefix}{row['ticker']} {row['name']}\n"
                    f"  {unit}數：{shares_t:,}{unit}  權重：{row['weight_today']}%\n"
                )
            else:
                sign = "+" if delta_s > 0 else ""
                lines.append(
                    f"  {prefix}{row['ticker']} {row['name']}\n"
                    f"  {unit}數：{sign}{delta_s:,}{unit} "
                    f"({shares_y:,}→{shares_t:,})\n"
                    f"  權重：{row['weight_yest']}%→{row['weight_today']}%"
                    f"（{'+' if row['delta']>0 else ''}{row['delta']}%）\n"
                )
        lines.append("")

    return "\n".join(lines)

if __name__ == "__main__":
    FUNDS = ["00988A", "00981A", "00992A"]

    if len(sys.argv) == 3:
        target_date = sys.argv[1]
        FUNDS = [sys.argv[2]]
    elif len(sys.argv) == 2:
        target_date = sys.argv[1]
    else:
        target_date = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect("etf.db")

    for fund_id in FUNDS:
        df = get_daily_changes(conn, target_date, fund_id)
        if df.empty:
            print(f"[跳過] {fund_id} {target_date} 無異動資料")
            continue
        message = format_message(df, target_date, fund_id, conn=conn)
        print(message)
        if fund_id not in DISCORD_ONLY_FUNDS:
            send_telegram(message)
        send_discord(message, fund_id)

    conn.close()