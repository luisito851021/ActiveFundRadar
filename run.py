import subprocess
import sys
from datetime import datetime
import sqlite3

def run(script, args=[]):
    cmd = [sys.executable, script] + args
    print(f"\n{'='*40}")
    print(f"執行：{' '.join(cmd)}")
    print('='*40)
    result = subprocess.run(cmd, cwd=r"C:\ActiveFundRadar")
    return result.returncode == 0

def get_latest_date_by_fund(fund_id, db_path=r"C:\ActiveFundRadar\etf.db"):
    """取得各 ETF 最新一筆 holdings 日期"""
    conn = sqlite3.connect(db_path)
    result = conn.execute(
        f"SELECT date FROM holdings WHERE fund_id='{fund_id}' ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return result[0] if result else None

if __name__ == "__main__":
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n🚀 ActiveFundRadar 自動執行開始：{now}")

    # Step 1：下載 XLSX
    if not run("download.py"):
        print("[中止] 下載失敗，請檢查網路或 Cookie 是否過期")
        sys.exit(1)

    # Step 2：寫入資料庫
    if not run("main.py"):
        print("[中止] 寫入資料庫失敗")
        sys.exit(1)

    # Step 3：各 ETF 找自己最新日期來做 diff 和 notify
    FUNDS = ["00988A", "00981A"]

    for fund_id in FUNDS:
        latest = get_latest_date_by_fund(fund_id)
        if not latest:
            print(f"[跳過] {fund_id} 資料庫無資料")
            continue

        print(f"\n📅 {fund_id} 最新日期：{latest}")

        if not run("diff.py", [latest]):
            print(f"[警告] {fund_id} diff 執行失敗")
            continue

        # 發送持倉異動明細
        run("notify.py", [latest, fund_id])

        # 發送 AI 選股邏輯分析（每檔分開）
        run("analyze.py", [latest, fund_id]) 

    print(f"\n✅ 全部完成：{datetime.now().strftime('%H:%M:%S')}")