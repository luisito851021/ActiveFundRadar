import os
from dotenv import load_dotenv

load_dotenv()

def _get_engine():
    url = os.getenv("SUPABASE_URL")
    if not url:
        return None
    from sqlalchemy import create_engine
    return create_engine(url, pool_pre_ping=True)

def sync_to_supabase(df, table_name: str):
    """依 fund_id + date 刪除舊資料後重新寫入 Supabase，SUPABASE_URL 未設定時靜默跳過"""
    engine = _get_engine()
    if engine is None:
        return

    fund_id  = df["fund_id"].iloc[0]
    date_val = df["date"].iloc[0]

    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {table_name} WHERE fund_id = :f AND date = :d"),
                {"f": fund_id, "d": date_val},
            )
        df.to_sql(table_name, engine, if_exists="append", index=False, method="multi")
        print(f"[Supabase] {table_name} {fund_id} {date_val} 同步完成（{len(df)} 筆）")
    except Exception as e:
        print(f"[Supabase] {table_name} 同步失敗：{e}")
    finally:
        engine.dispose()
