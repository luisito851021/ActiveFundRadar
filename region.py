"""
region.py — 投資區域比例（00990A 官方爬蟲 / 00988A 依代號後綴推算），存入 region_ratios 表

用法：
    python region.py 00988A 2026-07-05   # 手動測試：依 holdings 推算並寫入
"""

import os
import sqlite3
import sys

import pandas as pd
from dotenv import load_dotenv

load_dotenv(r'C:\ActiveFundRadar\.env')

DB_PATH = os.getenv("SQLITE_PATH", r"C:\ActiveFundRadar\etf.db")

REGION_SUFFIX_MAP = {
    "US": "美國",
    "JP": "日本",
    "KS": "韓國",
    "GY": "德國",
    "GR": "德國",
    "HK": "香港",
    "FP": "法國",
    "LN": "英國",
}


def region_of(ticker: str) -> str:
    """依 Bloomberg 風格代號後綴判斷地區，純數字（無後綴）視為台灣"""
    parts = ticker.strip().split()
    if len(parts) > 1:
        return REGION_SUFFIX_MAP.get(parts[-1].upper(), "其他")
    return "台灣"


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS region_ratios (
            fund_id TEXT NOT NULL,
            date    TEXT NOT NULL,
            region  TEXT NOT NULL,
            ratio   REAL,
            count   INTEGER,
            PRIMARY KEY (fund_id, date, region)
        )
    """)
    conn.commit()


def compute_region_from_holdings(conn, fund_id: str, date: str) -> pd.DataFrame:
    """給無官方區域資料的基金（如 00988A）用：依 holdings 權重加總近似推算"""
    df = pd.read_sql(
        "SELECT ticker, weight FROM holdings WHERE fund_id=? AND date=?",
        conn, params=(fund_id, date),
    )
    if df.empty:
        return df

    df["region"] = df["ticker"].apply(region_of)
    grouped = df.groupby("region").agg(ratio=("weight", "sum"), count=("ticker", "count")).reset_index()
    grouped["fund_id"] = fund_id
    grouped["date"] = date
    return grouped[["fund_id", "date", "region", "ratio", "count"]]


def parse_00990A_region_csv(filepath: str) -> pd.DataFrame:
    """給 00990A 用：讀 Selenium 爬蟲存的區域比例 CSV（date,region,ratio,count），ratio 轉小數"""
    df = pd.read_csv(filepath, encoding="utf-8", dtype=str)
    df["ratio"] = pd.to_numeric(df["ratio"], errors="coerce") / 100
    df["count"] = pd.to_numeric(df["count"], errors="coerce").astype("Int64")
    df["fund_id"] = "00990A"
    return df[["fund_id", "date", "region", "ratio", "count"]]


def save_region(df: pd.DataFrame, db_path: str = DB_PATH):
    if df is None or df.empty:
        print("[跳過] 區域資料為空，不寫入")
        return

    fund_id = df["fund_id"].iloc[0]
    date_val = df["date"].iloc[0]

    conn = sqlite3.connect(db_path)
    ensure_table(conn)

    existing = conn.execute(
        "SELECT COUNT(*) FROM region_ratios WHERE fund_id=? AND date=?",
        (fund_id, date_val),
    ).fetchone()[0]

    if existing > 0:
        print(f"[跳過] {fund_id} {date_val} 區域資料已存在")
        conn.close()
        return

    df.to_sql("region_ratios", conn, if_exists="append", index=False)
    print(f"[成功] {fund_id} 區域資料寫入 {len(df)} 筆 ({date_val})")
    conn.close()

    push_supabase_region(df)


def push_supabase_region(df: pd.DataFrame):
    """比照 classify.py 的 push_supabase()：CREATE TABLE IF NOT EXISTS + DELETE/INSERT"""
    url = os.getenv("SUPABASE_URL")
    if not url:
        print("[Supabase] 未設定 SUPABASE_URL，跳過")
        return

    fund_id = df["fund_id"].iloc[0]
    date_val = df["date"].iloc[0]

    from sqlalchemy import create_engine, text as T
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as pg:
            pg.execute(T("""
                CREATE TABLE IF NOT EXISTS region_ratios (
                    fund_id TEXT NOT NULL,
                    date    TEXT NOT NULL,
                    region  TEXT NOT NULL,
                    ratio   DOUBLE PRECISION,
                    count   INTEGER,
                    PRIMARY KEY (fund_id, date, region)
                )
            """))
            pg.execute(
                T("DELETE FROM region_ratios WHERE fund_id = :f AND date = :d"),
                {"f": fund_id, "d": date_val},
            )
        df.to_sql("region_ratios", engine, if_exists="append", index=False, method="multi")
        print(f"[Supabase] region_ratios {fund_id} {date_val} 同步完成（{len(df)} 筆）")
    except Exception as e:
        print(f"[Supabase] region_ratios 同步失敗：{e}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法：python region.py <fund_id> <date>")
        sys.exit(1)

    _fund_id, _date = sys.argv[1], sys.argv[2]
    _conn = sqlite3.connect(DB_PATH)
    _df = compute_region_from_holdings(_conn, _fund_id, _date)
    _conn.close()
    print(_df)
    save_region(_df)
