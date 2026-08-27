import sqlite3
import pandas as pd
import re
import glob
import os
from datetime import date
from db_utils import sync_to_supabase
import region

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


def parse_00987D_xlsx(filepath):
    """
    解析統一 00987D（美債量化）的 xlsx。
    與股票型 ETF 不同：持倉分成「債券」（面額）與「期貨(名目本金)」（口數）兩張表，
    兩者都寫進 holdings——期貨名目本金佔淨值 20% 以上，是這檔量化債券 ETF 調整
    存續期間的主要工具，只記債券會漏掉最關鍵的異動。
    債券 shares 存面額、期貨 shares 存口數；
    期貨 ticker 後面接契約年月（如「UB 2026/12」）以區分不同到期月份的部位。
    """
    df_raw = pd.read_excel(filepath, header=None, sheet_name=0)

    date_str  = str(df_raw.iloc[0, 0])
    roc_match = re.search(r"(\d{2,3})/(\d{2})/(\d{2})", date_str)
    if roc_match:
        data_date = date(
            int(roc_match.group(1)) + 1911,
            int(roc_match.group(2)),
            int(roc_match.group(3)),
        ).strftime("%Y-%m-%d")
    else:
        data_date = date.today().strftime("%Y-%m-%d")

    def _header_row(keyword):
        for i in range(len(df_raw)):
            if keyword in df_raw.iloc[i].astype(str).tolist():
                return i
        return None

    def _rows_after(header_idx):
        """取 header 之後到第一個空白列為止的資料列"""
        rows = []
        for i in range(header_idx + 1, len(df_raw)):
            val = df_raw.iloc[i, 0]
            if pd.isna(val) or str(val).strip() == "":
                break
            rows.append(df_raw.iloc[i])
        return rows

    records = []

    # 債券：債券代號 / 債券名稱 / 發行人名稱 / 面額 / 持股權重
    bond_row = _header_row("債券代號")
    if bond_row is not None:
        for r in _rows_after(bond_row):
            records.append({
                "ticker": str(r.iloc[0]).strip(),
                "name":   str(r.iloc[1]).strip(),
                "shares": r.iloc[3],
                "weight": r.iloc[4],
            })

    # 期貨：期貨代號 / 期貨名稱 / 持股權重 / 口數 / 契約年月
    fut_row = _header_row("期貨代號")
    if fut_row is not None:
        for r in _rows_after(fut_row):
            records.append({
                "ticker": f"{str(r.iloc[0]).strip()} {str(r.iloc[4]).strip()}",
                "name":   str(r.iloc[1]).strip(),
                "shares": r.iloc[3],
                "weight": r.iloc[2],
            })

    if not records:
        raise ValueError(f"[00987D] 找不到債券或期貨持倉表：{filepath}")

    df = pd.DataFrame(records)
    df["shares"] = pd.to_numeric(
        df["shares"].astype(str).str.replace(",", ""), errors="coerce"
    )
    df["weight"] = (
        df["weight"].astype(str).str.replace("%", "").str.replace(",", "")
        .pipe(pd.to_numeric, errors="coerce") / 100
    )
    df["date"]    = data_date
    df["fund_id"] = "00987D"
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
    target = sys.argv[1:] if len(sys.argv) > 1 else ["00988A", "00981A", "00992A", "00403A", "00991A", "00990A", "00411A", "00987D"]

    base_folder = r"C:\ActiveFundRadar\Files"

    funds = [
        {"folder": "00988A", "fund_id": "00988A"},
        {"folder": "00981A", "fund_id": "00981A"},
        {"folder": "00403A", "fund_id": "00403A"},
        {"folder": "00411A", "fund_id": "00411A"},
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

        # 00988A／00411A 官網無投資區域資料，依持股代號後綴推算近似比例
        if fund["fund_id"] in ("00988A", "00411A"):
            conn = sqlite3.connect("etf.db")
            region_df = region.compute_region_from_holdings(conn, fund["fund_id"], holdings["date"].iloc[0])
            conn.close()
            region.save_region(region_df)

    # 00990A 元大（Selenium 刮 HTML → CSV）
    if "00990A" in target:
        folder_990 = os.path.join(base_folder, "00990A")
        files_990  = glob.glob(os.path.join(folder_990, "00990A_[0-9]*.csv"))
        if not files_990:
            print("[跳過] 00990A 找不到任何 csv 檔案")
        else:
            csv_path = sorted(files_990)[-1]
            print(f"\n[00990A] 使用檔案：{os.path.basename(csv_path)}")
            holdings = parse_00990A_csv(csv_path)
            print(holdings)
            save_to_db(holdings)

        # 投資區域比例（官網爬蟲產生，找不到就跳過，不中斷流程）
        region_files = glob.glob(os.path.join(folder_990, "00990A_region_*.csv"))
        if not region_files:
            print("[警告] 00990A 找不到投資區域 csv 檔案，略過")
        else:
            region_path = sorted(region_files)[-1]
            print(f"[00990A] 使用區域檔案：{os.path.basename(region_path)}")
            region.save_region(region.parse_00990A_region_csv(region_path))

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


    # 00987D 統一美債量化（債券＋期貨，獨立格式）
    if "00987D" in target:
        folder_987 = os.path.join(base_folder, "00987D")
        files_987  = glob.glob(os.path.join(folder_987, "00987D_ETF_Investment_Portfolio_*.xlsx"))
        if not files_987:
            print("[跳過] 00987D 找不到任何 xlsx 檔案")
        else:
            xlsx_path = sorted(files_987)[-1]
            print(f"\n[00987D] 使用檔案：{os.path.basename(xlsx_path)}")
            holdings = parse_00987D_xlsx(xlsx_path)
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