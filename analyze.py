import sqlite3
import pandas as pd
import requests
import anthropic
import sys
import os
from datetime import date
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

# ── 設定區 ────────────────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
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

FUND_NAMES = {
    "00988A": "統一全球創新",
    "00981A": "統一台股增長",
    "00992A": "群益台灣科技創新",
    "00403A": "統一台股升級50",
    "00991A": "復華未來50",
    "00990A": "元大全球AI",
    "00411A": "統一前沿科技",
    "00987D": "統一美債量化",
}

DISCORD_ONLY_FUNDS = {"00992A", "00990A", "00991A"}

# 多空並陳（合併解讀 + 精簡多空，各一句）：8 檔全套用
BULL_BEAR_FUNDS = {"00988A", "00981A", "00992A", "00403A", "00991A", "00990A", "00411A", "00987D"}

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

# ── Discord 發送 ──────────────────────────────────
def send_discord(message: str, fund_id: str):
    channel_id = DISCORD_CHANNELS.get(fund_id)
    if not DISCORD_BOT_TOKEN or not channel_id:
        print("[Discord] 未設定 Token 或 Channel ID，跳過")
        return

    clean = message.replace("<b>", "**").replace("</b>", "**")
    chunks = [clean[i:i+1900] for i in range(0, len(clean), 1900)]

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    for chunk in chunks:
        resp = requests.post(url, headers=headers, json={"content": chunk})
        if resp.status_code in (200, 201):
            print("[Discord] 發送成功")
        else:
            print(f"[Discord] 發送失敗：{resp.text}")

def already_sent(conn, fund_id: str, target_date: str, kind: str = "analyze") -> bool:
    """檢查該基金該日期是否已經發送過通知，避免來源網站卡住不更新時重複呼叫 Claude API 並重發"""
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

def mark_sent(conn, fund_id: str, target_date: str, kind: str = "analyze"):
    conn.execute(
        "INSERT OR IGNORE INTO notify_log (fund_id, date, kind) VALUES (?, ?, ?)",
        (fund_id, target_date, kind),
    )
    conn.commit()

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

    if fund_id in BULL_BEAR_FUNDS:
        sections = [
            "1. 📌 調倉重點與邏輯\n"
            "   用 3～4 句綜合說明本次異動涉及哪些產業、整體配置方向的轉變，"
            "以及你推測經理人背後的投資思路（what 與 why 合併闡述，不要逐筆重述原始數據）。",
            "2. ⚖️ 多空視角（各限一句話）\n"
            "   🐂 偏多：一句話說明這次調倉看多的理由。\n"
            "   🐻 偏空：一句話說明同一批異動可能反映的疑慮或風險。",
        ]
        instruction = "請以條列式撰寫，第 1 點 3～4 句、第 2 點多空各一句，語氣專業但易讀。不需要重複列出原始數據。"
    else:
        sections = [
            "1. 📌 產業佈局變化\n   說明本次異動涉及哪些產業，整體配置方向有何轉變。",
            "2. 💡 可能的選股邏輯\n   推測經理人此次調倉背後的投資思路，例如追蹤特定產業趨勢、規避風險、或因應總體經濟變化。",
        ]
        instruction = "請以條列式撰寫，每點 2～3 句，語氣專業但易讀。不需要重複列出原始數據。"
    body = "\n\n".join(sections)

    return f"""{prompt_data}
請根據以上異動，提供繁體中文分析摘要：

{body}

{instruction}"""

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
        "00992A": (
            "你是一位專業的台灣科技股市場分析師，熟悉主動型 ETF 的運作機制，"
            "專注於台灣半導體、AI、電子、通訊等科技產業的產業趨勢與個股選股邏輯。"
            "請根據基金的每日持倉異動資料，提供簡潔、有洞察力的繁體中文分析。"
        ),
        "00403A": (
            "你是一位專業的台灣股票市場分析師，熟悉主動型 ETF 的運作機制與台灣上市公司。"
            "專注於台灣50大市值企業的產業趨勢與選股邏輯。"
            "請根據基金的每日持倉異動資料，提供簡潔、有洞察力的繁體中文分析。"
        ),
        "00991A": (
            "你是一位專業的台灣股票市場分析師，熟悉主動型 ETF 的運作機制與台灣上市公司。"
            "專注於台灣中小型成長股、科技產業與新興題材的趨勢與個股選股邏輯。"
            "請根據基金的每日持倉異動資料，提供簡潔、有洞察力的繁體中文分析。"
        ),
        "00990A": (
            "你是一位專業的全球科技股市場分析師，熟悉主動型 ETF 的運作機制，"
            "專注於 AI、半導體、記憶體、資料中心等科技產業的全球趨勢與個股選股邏輯，"
            "涵蓋美股、日股、韓股、德股及台股。"
            "請根據基金的每日持倉異動資料，提供簡潔、有洞察力的繁體中文分析。"
        ),
        "00411A": (
            "你是一位專業的全球科技股市場分析師，熟悉主動型 ETF 的運作機制，"
            "專注於半導體、AI 基礎建設、光通訊、太空與國防等前沿科技題材的產業趨勢與個股選股邏輯，"
            "涵蓋美股、日股、歐股及台股。"
            "請根據基金的每日持倉異動資料，提供簡潔、有洞察力的繁體中文分析。"
        ),
        "00987D": (
            "你是一位專業的固定收益市場分析師，熟悉主動型債券 ETF 與量化策略的運作機制，"
            "專注於美國公債殖利率曲線、存續期間配置與美債期貨（如超長美債 UB）的操作邏輯。"
            "請注意：持倉中「面額」為債券部位規模，「口數」為期貨契約口數，"
            "期貨部位是經理人調整存續期間的主要工具。"
            "請根據基金的每日持倉異動資料，提供簡潔、有洞察力的繁體中文分析。"
        ),
    }

    system = system_map.get(fund_id, system_map["00981A"])

    if fund_id in BULL_BEAR_FUNDS:
        system += "分析請保持中立，多空兩面都要給出有依據的觀點，僅供研究參考，不構成買賣建議。"

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = response.usage
    print(f"  [Token] input={usage.input_tokens}  output={usage.output_tokens}  total={usage.input_tokens + usage.output_tokens}")
    # Sonnet 5 回傳時第一個 block 可能是 ThinkingBlock，需找第一個有 .text 的 block
    return next((b.text for b in response.content if hasattr(b, "text")), "").strip()

# ── 組成訊息 ──────────────────────────────────────
def format_analysis_message(analysis: str, target_date: str, fund_id: str) -> str:
    fund_name = FUND_NAMES.get(fund_id, fund_id)
    return (
        f"🤖 <b>{target_date} {fund_id} {fund_name}</b>\n"
        f"<b>AI 選股邏輯分析</b>\n\n"
        f"{analysis}"
    )

# ── 主程式 ────────────────────────────────────────
if __name__ == "__main__":
    ALL_FUNDS = ["00988A", "00981A", "00992A", "00403A", "00991A", "00990A", "00411A", "00987D"]

    if len(sys.argv) == 3:
        ref_date   = sys.argv[1]
        FUNDS      = [sys.argv[2]]
        fixed_date = True
    elif len(sys.argv) == 2:
        ref_date   = sys.argv[1]
        FUNDS      = ALL_FUNDS
        fixed_date = False
    else:
        ref_date   = date.today().strftime("%Y-%m-%d")
        FUNDS      = ALL_FUNDS
        fixed_date = False

    conn = sqlite3.connect("etf.db")

    for fund_id in FUNDS:
        print(f"\n{'='*40}")

        if fixed_date:
            actual_date = ref_date
        else:
            actual_date = get_latest_change_date(conn, fund_id, ref_date)
            if actual_date is None:
                print(f"[跳過] {fund_id} 在 {ref_date} 以前找不到任何異動資料")
                continue

        print(f"分析：{fund_id}  日期：{actual_date}")

        if already_sent(conn, fund_id, actual_date, "analyze"):
            print(f"[跳過] {fund_id} {actual_date} 已經發送過分析，不重複發送")
            continue

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
        if fund_id not in DISCORD_ONLY_FUNDS:
            send_telegram(message)
        send_discord(message, fund_id)
        mark_sent(conn, fund_id, actual_date, "analyze")

    conn.close()
    print(f"\n✅ 分析完成")
