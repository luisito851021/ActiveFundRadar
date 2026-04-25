import sqlite3
import pandas as pd
from datetime import date, timedelta
import sys
from db_utils import sync_to_supabase

def get_holdings(conn, date_str, fund_id="00988A"):
    return pd.read_sql(
        f"SELECT * FROM holdings WHERE date='{date_str}' AND fund_id='{fund_id}'", conn
    )

def diff_holdings(today_df, yesterday_df):
    t = today_df.set_index("ticker")
    y = yesterday_df.set_index("ticker")

    today_set     = set(t.index)
    yesterday_set = set(y.index)

    # 建倉
    new_in = t.loc[list(today_set - yesterday_set)].copy()
    new_in["action"]      = "建倉"
    new_in["delta"]       = new_in["weight"]
    new_in["weight_yest"] = 0
    new_in["shares_yest"] = 0

    # 清倉
    dropped = y.loc[list(yesterday_set - today_set)].copy()
    dropped["action"]      = "清倉"
    dropped["delta"]       = -dropped["weight"]
    dropped["weight_yest"] = dropped["weight"]
    dropped["shares_yest"] = dropped["shares"]

    # 加減碼
    changed = []
    for ticker in today_set & yesterday_set:
        w_today = t.loc[ticker, "weight"]
        w_yest  = y.loc[ticker, "weight"]
        s_today = t.loc[ticker, "shares"]
        s_yest  = y.loc[ticker, "shares"]
        delta_w = round(w_today - w_yest, 4)
        delta_s = int(s_today - s_yest)
        if delta_s != 0:
            changed.append({
                "ticker":       ticker,
                "name":         t.loc[ticker, "name"],
                "shares":       s_today,
                "weight":       w_today,
                "action":       "加碼" if delta_s  > 0 else "減碼",
                "delta":        delta_w,
                "weight_yest":  w_yest,
                "shares_yest":  s_yest,
                "delta_shares": delta_s,
            })

    rows = []
    for df_part in [new_in.reset_index(), dropped.reset_index()]:
        df_part["delta_shares"] = df_part["shares"] - df_part["shares_yest"]
        rows.append(df_part[["ticker", "name", "shares", "weight", "action",
                              "delta", "weight_yest", "shares_yest", "delta_shares"]])

    result = pd.concat(rows + [pd.DataFrame(changed)], ignore_index=True)
    return result.sort_values("action")


def save_changes(conn, diff_df, today_date, yesterday_date, fund_id="00988A"):
    if diff_df.empty:
        print("無異動")
        return

    # 防止重複寫入同一天
    existing = pd.read_sql(
    f"SELECT COUNT(*) as cnt FROM daily_changes WHERE date='{today_date}' AND fund_id='{fund_id}'",
    conn
    ).iloc[0]["cnt"]

    print(f"[DEBUG] existing = {existing}, type = {type(existing)}") 

    if existing > 0:
        print(f"[跳過] {fund_id} {today_date} 異動資料已存在，不重複寫入")
        return

    save_df = pd.DataFrame({
    "fund_id":      fund_id,
    "date":         today_date,
    "ticker":       diff_df["ticker"],
    "name":         diff_df["name"],
    "action":       diff_df["action"],
    "shares_today": diff_df["shares"],
    "shares_yest":  diff_df["shares_yest"],
    "delta_shares": diff_df["delta_shares"],
    "weight_today": diff_df["weight"],
    "weight_yest":  diff_df["weight_yest"],
    "delta":        diff_df["delta"],
    })

    save_df.to_sql("daily_changes", conn, if_exists="append", index=False)
    print(f"[成功] 寫入 {len(save_df)} 筆異動記錄")
    print(save_df[["ticker", "action", "shares_yest", "shares_today",
                   "delta_shares", "weight_yest", "weight_today", "delta"]].to_string(index=False))
    sync_to_supabase(save_df, "daily_changes")


if __name__ == "__main__":
    FUNDS = ["00988A", "00981A", "00992A"]

    if len(sys.argv) == 3:
        TODAY     = sys.argv[1]
        YESTERDAY = sys.argv[2]
    elif len(sys.argv) == 2:
        TODAY     = sys.argv[1]
        YESTERDAY = None
    else:
        TODAY     = date.today().strftime("%Y-%m-%d")
        YESTERDAY = None

    conn = sqlite3.connect("etf.db")

    for fund_id in FUNDS:
        print(f"\n{'='*40}")
        print(f"處理：{fund_id}")

        # 自動找前一個有資料的交易日
        prev = YESTERDAY
        if prev is None:
            result = pd.read_sql(
                f"SELECT date FROM holdings WHERE date < '{TODAY}' AND fund_id='{fund_id}' ORDER BY date DESC LIMIT 1",
                conn
            )
            if result.empty:
                print(f"[跳過] {fund_id} 找不到 {TODAY} 之前的資料")
                continue
            prev = result.iloc[0]["date"]

        print(f"比對日期：{prev} → {TODAY}")

        today_df     = get_holdings(conn, TODAY,     fund_id)
        yesterday_df = get_holdings(conn, prev, fund_id)

        if today_df.empty:
            print(f"[跳過] {fund_id} 找不到 {TODAY} 的資料")
            continue

        if yesterday_df.empty:
            print(f"[跳過] {fund_id} 找不到 {prev} 的資料")
            continue

        diff = diff_holdings(today_df, yesterday_df)

        print(f"\n===== {fund_id} 持倉異動明細 =====")
        print(diff.to_string(index=False))

        save_changes(conn, diff, TODAY, prev, fund_id)

    conn.close()
