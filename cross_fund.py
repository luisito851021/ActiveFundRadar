"""
cross_fund.py — 跨基金共振訊號偵測
找出當日被超過 1 檔基金同時異動的標的，發送到 Discord 共振頻道。

用法：
    python cross_fund.py              # 自動抓最新有資料的日期
    python cross_fund.py 2026-07-04   # 指定日期
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
}

# 台股基金（持股單位：張）
TW_FUNDS = {"00981A", "00992A", "00403A", "00991A"}


ALL_FUNDS = ["00988A", "00981A", "00992A", "00403A", "00991A", "00990A"]


def get_active_dates(conn) -> list[str]:
    """
    取得「每檔基金各自最新日期」的聯集，去重後排序。
    全球 ETF (00988A/00990A) 日期比台股 ETF 少一天，
    這樣兩個日期都能被查到，不會漏掉跨基金訊號。
    """
    placeholders = ",".join(f"'{f}'" for f in ALL_FUNDS)
    rows = conn.execute(f"""
        SELECT DISTINCT date FROM (
            SELECT MAX(date) AS date
            FROM daily_changes
            WHERE fund_id IN ({placeholders})
            GROUP BY fund_id
        )
        WHERE date IS NOT NULL
        ORDER BY date DESC
    """).fetchall()
    return [r[0] for r in rows]


def get_cross_fund_signals(conn, target_date: str) -> pd.DataFrame:
    """
    找出當日被超過 1 檔基金異動的標的。
    只納入「以 target_date 為最新資料日期」的基金，
    避免跨日重複回報已發送過的訊號。
    """
    return pd.read_sql(f"""
        WITH active_funds AS (
            -- 只取「最新日期 = target_date」的基金
            SELECT fund_id FROM daily_changes
            GROUP BY fund_id
            HAVING MAX(date) = '{target_date}'
        ),
        multi_fund_tickers AS (
            -- 在 active_funds 中，當日被超過 1 檔基金異動的 ticker
            SELECT ticker FROM daily_changes
            WHERE date = '{target_date}'
              AND fund_id IN (SELECT fund_id FROM active_funds)
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
        WHERE dc.date = '{target_date}'
          AND dc.fund_id IN (SELECT fund_id FROM active_funds)
          AND dc.ticker IN (SELECT ticker FROM multi_fund_tickers)
        ORDER BY
            (SELECT COUNT(DISTINCT fund_id) FROM daily_changes
             WHERE date = '{target_date}' AND ticker = dc.ticker) DESC,
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

    if len(sys.argv) > 1:
        dates_to_check = [sys.argv[1]]
    else:
        dates_to_check = get_active_dates(conn)
        if not dates_to_check:
            print("[cross_fund] 資料庫無資料，結束")
            conn.close()
            sys.exit(0)
        print(f"[cross_fund] 自動偵測日期：{dates_to_check}")

    # 各日期獨立查詢後合併為一則訊息
    # display_date 用最新日期（台股）作為標題
    display_date = dates_to_check[0]
    frames = []
    for target_date in dates_to_check:
        df = get_cross_fund_signals(conn, target_date)
        if not df.empty:
            frames.append(df)

    conn.close()

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    message = format_message(combined, display_date)
    print("\n" + message)
    send_discord(message)
