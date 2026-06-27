import sqlite3
import pandas as pd
import re
import glob
import os
from datetime import date
from db_utils import sync_to_supabase

FUND_CONFIGS = [
    {"file_pattern": "ETF_Investment_Portfolio_*.xlsx", "fund_id": "00988A"},
]

def parse_etf_xlsx(filepath, fund_id="00988A"):
    df_raw = pd.read_excel(filepath, header=None, sheet_name=0)

    date_str  = str(df_raw.iloc[0, 0])
    roc_match = re.search(r"(\d{2,3})/(\d{2})/(\d{2})", date_str)
    if roc_match:
        y = int(roc_match.group(1)) + 1911
        m = int(roc_match.group(2))
        d = int(roc_match.group(3))
        data_date = date(y, m, d)
    else:
        data_date = date.today()

    header_row = None
    for i in range(len(df_raw)):
        row_vals = df_raw.iloc[i].astype(str).tolist()
        if "股票代號" in row_vals and "持股權重" in row_vals:
            header_row = i
            break

    holdings          = df_raw.iloc[header_row:].copy()
    holdings.columns  = holdings.iloc[0]
    holdings          = holdings.iloc[1:].reset_index(drop=True)
    holdings          = holdings.dropna(subset=["股票代號"])
    holdings.columns  = ["ticker", "name", "shares", "weight"]

    holdings["shares"] = pd.to_numeric(
        holdings["shares"].astype(str).str.replace(",", ""), errors="coerce"
    )
    holdings["weight"] = (
        holdings["weight"].astype(str)
        .str.replace("%", "").str.replace(",", "")
        .pipe(pd.to_numeric, errors="coerce") / 100
    )
    holdings["date"]    = data_date.strftime("%Y-%m-%d")
    holdings["fund_id"] = fund_id
    return holdings[["fund_id", "date", "ticker", "name", "shares", "weight"]]

def parse_00992A_xlsx(filepath):
    """解析群益 00992A 的 xlsx（股票 sheet，第一行即 header，無日期欄）"""
    filename = os.path.basename(filepath)
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    data_date = date_match.group(1) if date_match else date.today().strftime("%Y-%m-%d")

    df = pd.read_excel(filepath, sheet_name="股票", header=0)
    df = df.dropna(subset=["股票代號"])
    df = df.rename(columns={
        "股票代號":    "ticker",
        "股票名稱":    "name",
        "持股權重(%)": "weight",
        "股數":        "shares",
    })

    df["weight"] = (
        df["weight"].astype(str).str.replace("%", "").str.strip()
        .pipe(pd.to_numeric, errors="coerce") / 100
    )
    df["shares"] = pd.to_numeric(
        df["shares"].astype(str).str.replace(",", ""), errors="coerce"
    )
    df["date"]    = data_date
    df["fund_id"] = "00992A"
    return df[["fund_id", "date", "ticker", "name", "shares", "weight"]]


def parse_00990A_csv(filepath):
    """解析元大 00990A Selenium 刮下來的 CSV（ticker, name, shares, weight）"""
    df = pd.read_csv(filepath, encoding="utf-8", dtype=str)
    df["shares"] = pd.to_numeric(df["shares"].str.replace(",", ""), errors="coerce")
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce") / 100
    df["fund_id"] = "00990A"
    return df[["fund_id", "date", "ticker", "name", "shares", "weight"]]


def parse_00991A_xlsx(filepath):
    """解析復華 00991A 的 xlsx（Sheet1，搜尋「證券代號」行為 header，日期在 row 2）"""
    df_raw = pd.read_excel(filepath, sheet_name="Sheet1", header=None)

    # 日期：row 2 col 0 格式「日期: 2026/06/25」
    date_cell = str(df_raw.iloc[2, 0])
    dm = re.search(r"(\d{4})/(\d{2})/(\d{2})", date_cell)
    if dm:
        data_date = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
    else:
        fn = os.path.basename(filepath)
        m2 = re.search(r"(\d{4}-\d{2}-\d{2})", fn)
        data_date = m2.group(1) if m2 else date.today().strftime("%Y-%m-%d")

    # 找 header 行（含「證券代號」）
    header_row = None
    for i in range(len(df_raw)):
        if "證券代號" in df_raw.iloc[i].astype(str).tolist():
            header_row = i
            break
    if header_row is None:
        raise ValueError(f"[00991A] 找不到 header 行（證券代號）: {filepath}")

    df = df_raw.iloc[header_row:].copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)
    df = df.rename(columns={"證券代號": "ticker", "證券名稱": "name", "股數": "shares", "權重(%)": "weight"})
    df = df.dropna(subset=["ticker"])

    # ticker 在 Excel 可能讀成浮點（2330.0），統一轉成純字串
    df["ticker"] = df["ticker"].apply(
        lambda x: str(int(float(str(x).replace(",", "")))) if str(x) not in ("nan", "NaN", "") else None
    )
    df = df.dropna(subset=["ticker"])

    df["shares"] = pd.to_numeric(df["shares"].astype(str).str.replace(",", ""), errors="coerce")
    df["weight"] = (
        df["weight"].astype(str).str.replace("%", "").str.replace(",", "")
        .pipe(pd.to_numeric, errors="coerce") / 100
    )
    df["date"]    = data_date
    df["fund_id"] = "00991A"
    return df[["fund_id", "date", "ticker", "name", "shares", "weight"]]


def save_to_db(holdings_df, db_path="etf.db"):
    conn     = sqlite3.connect(db_path)
    date_val = holdings_df["date"].iloc[0]
    fund_val = holdings_df["fund_id"].iloc[0]

    existing = pd.read_sql(
        f"SELECT COUNT(*) as cnt FROM holdings WHERE date='{date_val}' AND fund_id='{fund_val}'",
        conn
    ).iloc[0]["cnt"]

    if existing > 0:
        print(f"[跳過] {fund_val} {date_val} 資料已存在")
    else:
        holdings_df.to_sql("holdings", conn, if_exists="append", index=False)
        print(f"[成功] {fund_val} 寫入 {len(holdings_df)} 筆 ({date_val})")
        conn.close()
        sync_to_supabase(holdings_df, "holdings")
        return

    conn.close()

if __name__ == "__main__":
    import sys
    target = sys.argv[1:] if len(sys.argv) > 1 else ["00988A", "00981A", "00992A", "00403A", "00991A", "00990A"]

    base_folder = r"C:\ActiveFundRadar\Files"

    funds = [
        {"folder": "00988A", "fund_id": "00988A"},
        {"folder": "00981A", "fund_id": "00981A"},
        {"folder": "00403A", "fund_id": "00403A"},
    ]

    for fund in funds:
        if fund["fund_id"] not in target:
            continue
        folder = os.path.join(base_folder, fund["folder"])
        files = glob.glob(os.path.join(folder, f"{fund['fund_id']}_ETF_Investment_Portfolio_*.xlsx"))
        if not files:
            files = glob.glob(os.path.join(folder, "ETF_Investment_Portfolio_*.xlsx"))

        if not files:
            print(f"[跳過] {fund['fund_id']} 找不到任何 xlsx 檔案")
            continue

        xlsx_path = sorted(files)[-1]
        print(f"\n[{fund['fund_id']}] 使用檔案：{os.path.basename(xlsx_path)}")

        holdings = parse_etf_xlsx(xlsx_path, fund_id=fund["fund_id"])
        print(holdings)
        save_to_db(holdings)

    # 00990A 元大（Selenium 刮 HTML → CSV）
    if "00990A" in target:
        folder_990 = os.path.join(base_folder, "00990A")
        files_990  = glob.glob(os.path.join(folder_990, "00990A_*.csv"))
        if not files_990:
            print("[跳過] 00990A 找不到任何 csv 檔案")
        else:
            csv_path = sorted(files_990)[-1]
            print(f"\n[00990A] 使用檔案：{os.path.basename(csv_path)}")
            holdings = parse_00990A_csv(csv_path)
            print(holdings)
            save_to_db(holdings)

    # 00991A 復華（獨立格式）
    if "00991A" in target:
        folder_991 = os.path.join(base_folder, "00991A")
        files_991  = glob.glob(os.path.join(folder_991, "00991A_*.xlsx"))
        if not files_991:
            print("[跳過] 00991A 找不到任何 xlsx 檔案")
        else:
            xlsx_path = sorted(files_991)[-1]
            print(f"\n[00991A] 使用檔案：{os.path.basename(xlsx_path)}")
            holdings = parse_00991A_xlsx(xlsx_path)
            print(holdings)
            save_to_db(holdings)

    # 00992A 群益（獨立格式）
    if "00992A" in target:
        folder_992 = os.path.join(base_folder, "00992A")
        files_992  = glob.glob(os.path.join(folder_992, "00992A_*.xlsx"))
        if not files_992:
            print("[跳過] 00992A 找不到任何 xlsx 檔案")
        else:
            xlsx_path = sorted(files_992)[-1]
            print(f"\n[00992A] 使用檔案：{os.path.basename(xlsx_path)}")
            holdings = parse_00992A_xlsx(xlsx_path)
            print(holdings)
            save_to_db(holdings)