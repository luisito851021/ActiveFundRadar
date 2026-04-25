"""
將本機 SQLite 資料一次性搬移至 Supabase PostgreSQL
使用前：在 Supabase SQL Editor 執行 schema.sql 建表
執行：python migrate.py
"""
import os
import sqlite3
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH  = os.getenv("SQLITE_PATH", r"C:\ActiveFundRadar\etf.db")
SUPABASE_URL = os.getenv("SUPABASE_URL")

if not SUPABASE_URL:
    raise RuntimeError("請在 .env 設定 SUPABASE_URL（PostgreSQL 連線字串）")

sqlite_conn = sqlite3.connect(SQLITE_PATH)
pg_engine   = create_engine(SUPABASE_URL)

def migrate_table(table: str):
    df = pd.read_sql(f"SELECT * FROM {table}", sqlite_conn)
    print(f"  {table}: {len(df)} 筆")
    df.to_sql(table, pg_engine, if_exists="append", index=False, method="multi", chunksize=500)
    print(f"  {table}: 寫入完成")

print("=== 開始搬移 ===")
migrate_table("holdings")
migrate_table("daily_changes")
print("=== 完成 ===")

sqlite_conn.close()
pg_engine.dispose()
