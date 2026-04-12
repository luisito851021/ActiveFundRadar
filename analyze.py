import sqlite3
import pandas as pd
import requests
import anthropic
import sys
import os
from datetime import date
from dotenv import load_dotenv

load_dotenv()

# ── 設定區 ────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID")

FUND_NAMES = {
    "00988A": "統一全球創新",
    "00981A": "統一台股增長",
}

# ── Telegram 發送 ─────────────────────────────────
def send_telegram(message: str):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    })
    if resp.status_code == 200:
        print("[Telegram] 發送成功")
    else:
        print(f"[Telegram] 發送失敗：{resp.text}")

# ── 找該基金在 daily_changes 裡 ≤ target_date 的最新日期 ──
def get_latest_change_date(conn, fund_id: str, target_date: str):
    result = pd.read_sql(f"""
        SELECT date FROM daily_changes
        WHERE fund_id = '{fund_id}' AND date <= '{target_date}'
        ORDER BY date DESC LIMIT 1
    """, conn)
    return result.iloc[0]["date"] if not result.empty else None

# ── 從 DB 讀取當日異動 ────────────────────────────
def get_daily_changes(conn, target_date: str, fund_id: str) -> pd.DataFrame:
    return pd.read_sql(f"""
        SELECT
            ticker, name, action,
            delta_shares, shares_today, shares_yest,
            ROUND(weight_today * 100, 2) AS weight_today,
            ROUND(weight_yest  * 100, 2) AS weight_yest,
            ROUND(delta        * 100, 2) AS delta
        FROM daily_changes
        WHERE date = '{target_date}' AND fund_id = '{fund_id}'
        ORDER BY action, ABS(delta) DESC
    """, conn)

# ── 組成給 Claude 的 Prompt ───────────────────────
def build_prompt(df: pd.DataFrame, target_date: str, fund_id: str) -> str:
    fund_name = FUND_NAMES.get(fund_id, fund_id)
    lines = [f"以下是主動型 ETF【{fund_id} {fund_name}】於 {target_date} 的持倉異動資料：\n"]

    for action in ["建倉", "清倉", "加碼", "減碼"]:
        subset = df[df["action"] == action]
        if subset.empty:
            continue
        lines.append(f"【{action}】")
        for _, row in subset.iterrows():
            if action == "建倉":
                lines.append(f"  {row['ticker']} {row['name']}  權重：{row['weight_today']}%")
            elif action == "清倉":
                lines.append(f"  {row['ticker']} {row['name']}  原權重：{row['weight_yest']}%")
            else:
                sign = "+" if row["delta"] > 0 else ""
                lines.append(
                    f"  {row['ticker']} {row['name']}  "
                    f"權重：{row['weight_yest']}% → {row['weight_today']}%"
                    f"（{sign}{row['delta']}%）"
                )
        lines.append("")

    prompt_data = "\n".join(lines)

    return f"""{prompt_data}
請根據以上異動，從兩個角度提供繁體中文分析摘要：

1. 📌 產業佈局變化
   說明本次異動涉及哪些產業，整體配置方向有何轉變。

2. 💡 可能的選股邏輯
   推測經理人此次調倉背後的投資思路，例如追蹤特定產業趨勢、規避風險、或因應總體經濟變化。

請以條列式撰寫，每點 2～3 句，語氣專業但易讀。不需要重複列出原始數據。"""

# ── 呼叫 Claude API ───────────────────────────────
def call_claude(prompt: str, fund_id: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_map = {
        "00988A": (
            "你是一位專業的全球股票市場分析師，熟悉主動型 ETF 的運作機制，"
            "擅長分析美股、日股、韓股、德股等國際市場的產業趨勢與個股選股邏輯。"
            "請根據基金的每日持倉異動資料，提供簡潔、有洞察力的繁體中文分析。"
        ),
        "00981A": (
            "你是一位專業的台灣股票市場分析師，熟悉主動型 ETF 的運作機制與台灣上市公司。"
            "請根據基金的每日持倉異動資料，提供簡潔、有洞察力的繁體中文分析。"
        ),
    }

    system = system_map.get(fund_id, system_map["00981A"])

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        temperature=0.3,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text

# ── 組成 Telegram 訊息 ────────────────────────────
def format_analysis_message(analysis: str, target_date: str, fund_id: str) -> str:
    fund_name = FUND_NAMES.get(fund_id, fund_id)
    return (
        f"🤖 <b>{target_date} {fund_id} {fund_name}</b>\n"
        f"<b>AI 選股邏輯分析</b>\n\n"
        f"{analysis}"
    )

# ── 主程式 ────────────────────────────────────────
# 用法：
#   python analyze.py                        → 今天為上限，兩檔各找自己最新異動日
#   python analyze.py 2026-04-01             → 4/1 為上限，兩檔各找自己最新異動日
#   python analyze.py 2026-04-01 00981A      → 指定日期 + 指定單檔（由 run.py 呼叫）
if __name__ == "__main__":
    ALL_FUNDS = ["00988A", "00981A"]

    if len(sys.argv) == 3:
        # run.py 呼叫：傳入日期 + fund_id，直接用傳入日期，只跑單檔
        ref_date   = sys.argv[1]
        FUNDS      = [sys.argv[2]]
        fixed_date = True
    elif len(sys.argv) == 2:
        # 手動執行：只傳日期，兩檔各自找 ≤ 該日期的最新異動日
        ref_date   = sys.argv[1]
        FUNDS      = ALL_FUNDS
        fixed_date = False
    else:
        # 不傳參數：今天為上限，兩檔各自找最新
        ref_date   = date.today().strftime("%Y-%m-%d")
        FUNDS      = ALL_FUNDS
        fixed_date = False

    conn = sqlite3.connect("etf.db")

    for fund_id in FUNDS:
        print(f"\n{'='*40}")

        # 決定實際分析日期
        if fixed_date:
            actual_date = ref_date
        else:
            actual_date = get_latest_change_date(conn, fund_id, ref_date)
            if actual_date is None:
                print(f"[跳過] {fund_id} 在 {ref_date} 以前找不到任何異動資料")
                continue

        print(f"分析：{fund_id}  日期：{actual_date}")

        df = get_daily_changes(conn, actual_date, fund_id)

        if df.empty:
            print(f"[跳過] {fund_id} {actual_date} 無異動資料，略過分析")
            continue

        print(f"  異動筆數：{len(df)}")

        prompt = build_prompt(df, actual_date, fund_id)
        print("  呼叫 Claude API...")

        try:
            analysis = call_claude(prompt, fund_id)
        except Exception as e:
            print(f"[錯誤] Claude API 呼叫失敗：{e}")
            continue

        message = format_analysis_message(analysis, actual_date, fund_id)
        print(message)
        send_telegram(message)

    conn.close()
    print(f"\n✅ 分析完成")
