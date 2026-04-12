import sqlite3

def init_db(db_path="etf.db"):
    conn = sqlite3.connect(db_path)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            date    TEXT,
            ticker  TEXT,
            name    TEXT,
            shares  INTEGER,
            weight  REAL,
            PRIMARY KEY (date, ticker)
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_changes (
            date         TEXT,
            ticker       TEXT,
            name         TEXT,
            action       TEXT,
            weight_today REAL,
            weight_yest  REAL,
            delta        REAL
        )
    """)
    
    conn.commit()
    conn.close()
    print("資料庫建立成功：etf.db")

init_db()