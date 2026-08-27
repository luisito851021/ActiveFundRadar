"""
cross_fund.py — 跨基金共振訊號偵測
找出「同一天寫入」（daily_changes.created_at）被超過 1 檔基金同時異動的標的，
發送到 Discord 共振頻道。用寫入日期而非交易日期分組，
避免各基金交易日回報時間錯開導致漏比對。

用法：
    python cross_fund.py              # 自動抓尚未處理過的寫入日期
    python cross_fund.py 2026-07-04   # 指定寫入日期
"""

import sqlite3
import pandas as pd
import requests
import os
import sys
from datetime import date
from dotenv import load_dotenv

load_dotenv(r'C:\ActiveFundRadar\.env')

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 設定區 ──────────────────────────────────────────
DISCORD_BOT_TOKEN       = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CROSS_CHANNEL   = os.getenv("DISCORD_CHANNEL_CROSS_FUND")
DB_PATH                 = os.getenv("SQLITE_PATH", r"C:\ActiveFundRadar\etf.db")
WEB_URL                 = "https://ezmoneysniper.streamlit.app"

ACTION_EMOJI = {
    "建倉": "🟢",
    "清倉": "🔴",
    "加碼": "📈",
    "減碼": "📉",
}

FUND_NAMES = {
    "00988A": "統一全球創新",
    "00981A": "統一台股增長",
    "00992A": "群益台灣科技創新",
    "00403A": "統一台股升級50",
    "00990A": "元大全球AI",
    "00991A": "復華未來50",
    "00411A": "統一前沿科技",
    "00987D": "統一美債量化",
}

# 台股基金（持股單位：張）
TW_FUNDS = {"00981A", "00992A", "00403A", "00991A"}


ALL_FUNDS = ["00988A", "00981A", "00992A", "00403A", "00991A", "00990A", "00411A", "00987D"]


def ensure_log_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cross_fund_log (
            date TEXT PRIMARY KEY
        )
    """)
    conn.commit()


def mark_processed(conn, write_date: str):
    conn.execute("INSERT OR IGNORE INTO cross_fund_log (date) VALUES (?)", (write_date,))
    conn.commit()


def get_unprocessed_write_dates(conn) -> list[str]:
    """
    取得尚未比對過共振的「寫入日期」（daily_changes.created_at，近 30 天內），由舊到新排序。
    改用寫入日期分組，取代舊版「用 date（交易日）互相比對」邏輯——
    各基金回報的交易日本來就會錯開（全球型基金固定慢一天、或某檔臨時補資料），
    用 date 互相比對容易漏掉「同一天寫入、但交易日標示不同」的異動。
    寫入日期才是真正代表「這批是同一次排程結果」的欄位。
    """
    ensure_log_table(conn)
    rows = conn.execute("""
        SELECT DISTINCT created_at FROM daily_changes
        WHERE created_at IS NOT NULL
          AND created_at >= date('now', '-30 days')
          AND created_at NOT IN (SELECT date FROM cross_fund_log)
        ORDER BY created_at ASC
    """).fetchall()
    return [r[0] for r in rows]


def get_cross_fund_signals(conn, write_date: str) -> pd.DataFrame:
    """找出同一寫入日期（created_at）裡，被超過 1 檔基金異動的標的（不分各基金交易日是否一致）"""
    return pd.read_sql(f"""
        WITH multi_fund_tickers AS (
            SELECT ticker FROM daily_changes
            WHERE created_at = '{write_date}'
            GROUP BY ticker
            HAVING COUNT(DISTINCT fund_id) > 1
        )
        SELECT
            dc.ticker,
            dc.name,
            dc.fund_id,
            dc.action,
            dc.delta_shares,
            dc.shares_today,
            dc.shares_yest,
            ROUND(dc.weight_today * 100, 2) AS weight_today,
            ROUND(dc.weight_yest  * 100, 2) AS weight_yest,
            ROUND(dc.delta        * 100, 2) AS delta_w
        FROM daily_changes dc
        WHERE dc.created_at = '{write_date}'
          AND dc.ticker IN (SELECT ticker FROM multi_fund_tickers)
        ORDER BY
            (SELECT COUNT(DISTINCT fund_id) FROM daily_changes
             WHERE created_at = '{write_date}' AND ticker = dc.ticker) DESC,
            dc.ticker,
            dc.fund_id
    """, conn)


def _fmt_shares(fund_id: str, shares: int, delta: int) -> str:
    """依基金別格式化股/張數"""
    if fund_id in TW_FUNDS:
        return f"{delta // 1000:+,} 張（{shares // 1000:,} 張）"
    return f"{delta:+,} 股（{shares:,} 股）"


def format_message(df: pd.DataFrame, display_date: str) -> str:
    """
    display_date：訊息標題顯示的日期（用最新的台股日期，或今天）。
    df 可能合併了不同 data_date 的基金（全球 ETF 日期比台股少一天），
    統一顯示為同一次排程的結果。
    """
    if df.empty:
        return f"📡 **{display_date} 共振訊號**\n\n今日無多基金共同異動標的"

    tickers = df["ticker"].unique().tolist()

    lines = [
        f"📡 **{display_date} 共振訊號**",
        f"共 **{len(tickers)}** 檔標的被多檔基金同日異動\n",
    ]

    for ticker in tickers:
        sub = df[df["ticker"] == ticker]
        name = sub.iloc[0]["name"]
        fund_count = sub["fund_id"].nunique()

        lines.append(f"**{ticker}** {name}　（{fund_count} 檔基金）")

        for _, row in sub.iterrows():
            fund_id = row["fund_id"]
            action  = row["action"]
            emoji   = ACTION_EMOJI.get(action, "❓")
            fname   = FUND_NAMES.get(fund_id, fund_id)

            delta  = int(row["delta_shares"])
            shares = int(row["shares_today"])

            if action in ("建倉", "清倉"):
                detail = (
                    f"{shares // 1000:,} 張  權重 {row['weight_today']}%"
                    if fund_id in TW_FUNDS
                    else f"{shares:,} 股  權重 {row['weight_today']}%"
                )
            else:
                sign = "+" if delta > 0 else ""
                if fund_id in TW_FUNDS:
                    detail = (
                        f"{sign}{delta // 1000:,} 張"
                        f"（{int(row['shares_yest']) // 1000:,}→{shares // 1000:,} 張）"
                        f"  權重 {row['weight_yest']}%→{row['weight_today']}%"
                    )
                else:
                    detail = (
                        f"{sign}{delta:,} 股"
                        f"（{int(row['shares_yest']):,}→{shares:,} 股）"
                        f"  權重 {row['weight_yest']}%→{row['weight_today']}%"
                    )

            lines.append(f"  {emoji} **{fund_id}** {fname}：{action}  {detail}")

        lines.append("")

    lines.append(f"🔗 [查看完整持倉 → ezMoneySniper]({WEB_URL})")
    return "\n".join(lines)


def send_discord(message: str) -> bool:
    if not DISCORD_BOT_TOKEN or not DISCORD_CROSS_CHANNEL:
        print("[Discord] 未設定 Token 或 Channel ID，跳過")
        return False
    url = f"https://discord.com/api/v10/channels/{DISCORD_CROSS_CHANNEL}/messages"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    chunks = [message[i:i+2000] for i in range(0, len(message), 2000)]
    ok = True
    for chunk in chunks:
        resp = requests.post(url, headers=headers, json={"content": chunk})
        if resp.status_code in (200, 201):
            print("[Discord] 發送成功")
        else:
            print(f"[Discord] 發送失敗：{resp.text}")
            ok = False
    return ok


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    ensure_log_table(conn)

    manual = len(sys.argv) > 1
    if manual:
        write_dates = [sys.argv[1]]
    else:
        write_dates = get_unprocessed_write_dates(conn)
        if not write_dates:
            print("[cross_fund] 沒有新的寫入日期需要比對，結束")
            conn.close()
            sys.exit(0)
        print(f"[cross_fund] 自動偵測未處理的寫入日期：{write_dates}")

    # 各寫入日期獨立查詢後合併為一則訊息
    # display_date 用最新寫入日期作為標題（write_dates 由舊到新排序）
    display_date = write_dates[-1]
    frames = []
    for write_date in write_dates:
        df = get_cross_fund_signals(conn, write_date)
        if not df.empty:
            frames.append(df)
        if not manual:
            mark_processed(conn, write_date)

    conn.close()

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    message = format_message(combined, display_date)
    print("\n" + message)
    send_discord(message)
