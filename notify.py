import sqlite3
import pandas as pd
import requests
from datetime import date
import sys
import os
from dotenv import load_dotenv

load_dotenv()



# ── 設定區 ────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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
        ORDER BY action, weight_today DESC   
    """, conn)

def format_message(df: pd.DataFrame, target_date: str, fund_id: str = "00988A") -> str:
    if df.empty:
        return f"📊 <b>{target_date} {fund_id} 持倉異動</b>\n\n今日無異動"
    lines = [f"📊 <b>{target_date} {fund_id} 持倉異動</b>\n"]

    for action, symbol in [("建倉", "🟢"), ("清倉", "🔴"), ("加碼", "📈"), ("減碼", "📉")]:
        subset = df[df["action"] == action]
        if subset.empty:
            continue

        lines.append(f"{symbol} <b>{action}</b>")
        for _, row in subset.iterrows():
            # 00981A 台股用張（1張=1000股），00988A 用股
            if fund_id == "00981A":
                unit       = "張"
                shares_t   = int(row['shares_today']) // 1000
                shares_y   = int(row['shares_yest'])  // 1000
                delta_s    = int(row['delta_shares'])  // 1000
            else:
                unit       = "股"
                shares_t   = int(row['shares_today'])
                shares_y   = int(row['shares_yest'])
                delta_s    = int(row['delta_shares'])

            if action in ("建倉", "清倉"):
                lines.append(
                    f"  {row['ticker']} {row['name']}\n"
                    f"  {unit}數：{shares_t:,}{unit}  權重：{row['weight_today']}%"
                )
            else:
                sign = "+" if delta_s > 0 else ""
                lines.append(
                    f"  {row['ticker']} {row['name']}\n"
                    f"  {unit}數：{sign}{delta_s:,}{unit} "
                    f"({shares_y:,}→{shares_t:,})\n"
                    f"  權重：{row['weight_yest']}%→{row['weight_today']}%"
                    f"（{'+' if row['delta']>0 else ''}{row['delta']}%）"
                )
        lines.append("")

    return "\n".join(lines)

if __name__ == "__main__":
    FUNDS = ["00988A", "00981A"]

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
        message = format_message(df, target_date, fund_id)
        print(message)
        send_telegram(message)

    conn.close()
