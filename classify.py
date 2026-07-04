"""
classify.py — 使用 Claude API 對持倉標的分類，存入 ticker_categories 表

用法：
    python classify.py            # 分類所有尚未分類的標的
    python classify.py --all      # 重新分類全部（覆蓋已有分類）
    python classify.py 00988A     # 只分類指定基金的標的
    python classify.py --push     # 完成後同步至 Supabase
"""

import sqlite3, json, os, sys, time
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(r'C:\ActiveFundRadar\.env')
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = os.getenv("SQLITE_PATH", r"C:\ActiveFundRadar\etf.db")
client  = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

CATEGORIES = [
    "晶圓代工 / 封測",
    "IC設計 / 處理器",
    "記憶體 / 儲存",
    "被動元件 / 電子零組件",
    "半導體設備 / 材料",
    "PCB / 載板 / 散熱",
    "伺服器 / 雲端基礎建設",
    "車用 / 功率半導體",
    "光通訊 / 雷射",
    "電源管理 / 電力",
    "網通 / 連接器",
    "金融",
    "其他",
]

COLOR_MAP = {
    "晶圓代工 / 封測":       "orange",
    "IC設計 / 處理器":       "green",
    "記憶體 / 儲存":         "purple",
    "被動元件 / 電子零組件":  "pink",
    "半導體設備 / 材料":     "amber",
    "PCB / 載板 / 散熱":    "lime",
    "伺服器 / 雲端基礎建設": "indigo",
    "車用 / 功率半導體":     "blue",
    "光通訊 / 雷射":         "teal",
    "電源管理 / 電力":       "red",
    "網通 / 連接器":         "cyan",
    "金融":                  "gray",
    "其他":                  "stone",
}


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticker_categories (
            ticker      TEXT PRIMARY KEY,
            name        TEXT,
            category    TEXT,
            description TEXT,
            color_key   TEXT,
            updated_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def get_targets(conn, fund_ids=None, force_all=False):
    """取得待分類標的（預設跳過已有分類的）"""
    if fund_ids:
        ph = ",".join(f"'{f}'" for f in fund_ids)
        fund_filter = f"AND h.fund_id IN ({ph})"
    else:
        fund_filter = ""

    if force_all:
        return conn.execute(f"""
            SELECT DISTINCT h.ticker, h.name
            FROM holdings h
            WHERE 1=1 {fund_filter}
            ORDER BY h.ticker
        """).fetchall()

    return conn.execute(f"""
        SELECT DISTINCT h.ticker, h.name
        FROM holdings h
        LEFT JOIN ticker_categories tc ON h.ticker = tc.ticker
        WHERE tc.ticker IS NULL {fund_filter}
        ORDER BY h.ticker
    """).fetchall()


def _match_to_batch(batch: list[tuple], raw: dict) -> dict:
    """
    Claude 有時回傳的 key 格式和輸入不符（如送 'AMD US' 回傳 'AMD'）。
    先做精確比對，找不到再用首碼比對還原成原始 ticker。
    """
    batch_tickers = {t: t for t, _ in batch}   # orig → orig（便於精確查找）
    base_map = {}                               # 首段代號 → orig ticker
    for t, _ in batch:
        base = t.strip().split()[0].upper()
        base_map.setdefault(base, t)            # 只取第一個，避免 6278 / 6278 JP 都在

    matched = {}
    for returned_key, info in raw.items():
        if returned_key in batch_tickers:
            matched[returned_key] = info
        else:
            base = returned_key.strip().split()[0].upper()
            orig = base_map.get(base)
            if orig:
                matched[orig] = info
    return matched


def classify_batch(batch: list[tuple]) -> dict:
    cat_str  = "\n".join(f"  - {c}" for c in CATEGORIES)
    item_str = "\n".join(f"- {t}: {n}" for t, n in batch)

    prompt = f"""你是半導體與科技產業分析師。請將以下股票分類到最適合的類別。

可用類別（只能選這些，用完整名稱）：
{cat_str}

股票列表（格式：代號: 公司名稱）：
{item_str}

重要：回傳純 JSON，每個 key 必須與上方「代號」欄位完全相同（含空格與後綴，如 "AMD US"、"5706 JP"、"2330"），value = {{
  "category": "<完整類別名稱>",
  "description": "<12字以內中文說明，如：DRAM記憶體、MLCC電容>"
}}
不要輸出任何說明或 markdown。"""

    resp = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    # Sonnet 5 回傳時第一個 block 可能是 ThinkingBlock，需找第一個有 .text 的 block
    text = next((b.text for b in resp.content if hasattr(b, "text")), "").strip()
    if "```" in text:
        parts = text.split("```")
        text  = parts[1].lstrip("json").strip() if len(parts) > 1 else text
    raw = json.loads(text)
    return _match_to_batch(batch, raw)


def save_batch(conn, ticker_name_map: dict, results: dict):
    for ticker, info in results.items():
        cat = info.get("category", "其他")
        if cat not in CATEGORIES:
            cat = "其他"
        conn.execute("""
            INSERT OR REPLACE INTO ticker_categories
                (ticker, name, category, description, color_key, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (
            ticker,
            ticker_name_map.get(ticker, ""),
            cat,
            info.get("description", ""),
            COLOR_MAP.get(cat, "stone"),
        ))
    conn.commit()


def push_supabase(conn):
    """把 SQLite ticker_categories 全量同步到 Supabase"""
    url = os.getenv("SUPABASE_URL")
    if not url:
        print("[Supabase] 未設定 SUPABASE_URL，跳過")
        return
    from sqlalchemy import create_engine, text as T
    engine = create_engine(url, pool_pre_ping=True)
    rows   = conn.execute(
        "SELECT ticker, name, category, description, color_key, updated_at FROM ticker_categories"
    ).fetchall()
    with engine.begin() as pg:
        pg.execute(T("""
            CREATE TABLE IF NOT EXISTS ticker_categories (
                ticker      TEXT PRIMARY KEY,
                name        TEXT,
                category    TEXT,
                description TEXT,
                color_key   TEXT,
                updated_at  TEXT
            )
        """))
        for row in rows:
            pg.execute(T("""
                INSERT INTO ticker_categories
                    (ticker, name, category, description, color_key, updated_at)
                VALUES (:ticker, :name, :category, :description, :color_key, :updated_at)
                ON CONFLICT (ticker) DO UPDATE SET
                    name=EXCLUDED.name,
                    category=EXCLUDED.category,
                    description=EXCLUDED.description,
                    color_key=EXCLUDED.color_key,
                    updated_at=EXCLUDED.updated_at
            """), dict(zip(
                ["ticker", "name", "category", "description", "color_key", "updated_at"],
                row
            )))
    print(f"[Supabase] 同步完成：{len(rows)} 筆")


if __name__ == "__main__":
    do_push  = "--push" in sys.argv
    force    = "--all"  in sys.argv
    fund_ids = [a for a in sys.argv[1:] if not a.startswith("--")]

    conn = sqlite3.connect(DB_PATH)
    ensure_table(conn)

    rows = get_targets(conn, fund_ids or None, force)
    if not rows:
        print("所有標的已分類完畢，無需更新。")
        if do_push:
            push_supabase(conn)
        conn.close()
        sys.exit(0)

    print(f"待分類：{len(rows)} 個標的\n")
    ticker_name_map = {t: n for t, n in rows}

    BATCH = 30
    total_ok = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        end   = min(i + BATCH, len(rows))
        print(f"  分類第 {i+1}–{end} 個...", end=" ", flush=True)
        try:
            result = classify_batch(batch)
            save_batch(conn, ticker_name_map, result)
            total_ok += len(result)
            print(f"✅ {len(result)} 個")
        except Exception as e:
            print(f"❌ {e}")
        if end < len(rows):
            time.sleep(1)

    print(f"\n分類完成，共 {total_ok} 個標的")

    if do_push:
        push_supabase(conn)

    conn.close()
