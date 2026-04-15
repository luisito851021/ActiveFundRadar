import streamlit as st
import sqlite3
import pandas as pd
from datetime import date

# ── 設定 ──────────────────────────────────────────
DB_PATH = r"C:\ActiveFundRadar\etf.db"

FUND_NAMES = {
    "00988A": "統一全球創新",
    "00981A": "統一台股增長",
}

ACTION_COLOR = {
    "建倉": "🟢",
    "清倉": "🔴",
    "加碼": "📈",
    "減碼": "📉",
}

FLAG_MAP = {
    "US": "🇺🇸",
    "JP": "🇯🇵",
    "KS": "🇰🇷",
    "GY": "🇩🇪",
    "HK": "🇭🇰",
    "FP": "🇫🇷",
    "LN": "🇬🇧",
}

def get_flag(ticker: str) -> str:
    suffix = ticker.strip().split()[-1].upper()
    return FLAG_MAP.get(suffix, "")

def add_flag_to_name(df: pd.DataFrame) -> pd.DataFrame:
    """在「名稱」欄前插入國旗，回傳新 DataFrame（不改原始）"""
    df = df.copy()
    df["名稱"] = df["代號"].apply(
        lambda t: (get_flag(t) + " ") if get_flag(t) else ""
    ) + df["名稱"]
    return df

# ── DB 工具 ───────────────────────────────────────
@st.cache_resource
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def query(sql: str) -> pd.DataFrame:
    return pd.read_sql(sql, get_conn())

def get_available_dates(fund_id: str) -> list[str]:
    df = query(f"""
        SELECT DISTINCT date FROM daily_changes
        WHERE fund_id = '{fund_id}'
        ORDER BY date DESC
    """)
    return df["date"].tolist()

def get_changes(fund_id: str, target_date: str) -> pd.DataFrame:
    return query(f"""
        SELECT
            ticker                               AS 代號,
            name                                 AS 名稱,
            action                               AS 動作,
            ROUND(weight_today * 100, 2)         AS 今日權重,
            ROUND(weight_yest  * 100, 2)         AS 昨日權重,
            ROUND(delta        * 100, 2)         AS 權重變化,
            delta_shares                         AS 股數變化,
            shares_yest                          AS 昨日股數,
            shares_today                         AS 今日股數
        FROM daily_changes
        WHERE fund_id = '{fund_id}' AND date = '{target_date}'
        ORDER BY
            CASE action
                WHEN '建倉' THEN 1
                WHEN '清倉' THEN 2
                WHEN '加碼' THEN 3
                WHEN '減碼' THEN 4
            END,
            ABS(delta) DESC
    """)

def get_history(fund_id: str, ticker: str) -> pd.DataFrame:
    return query(f"""
        SELECT
            date                                 AS 日期,
            action                               AS 動作,
            ROUND(weight_yest  * 100, 2)         AS 昨日權重,
            ROUND(weight_today * 100, 2)         AS 今日權重,
            ROUND(delta        * 100, 2)         AS 權重變化,
            delta_shares                         AS 股數變化
        FROM daily_changes
        WHERE fund_id = '{fund_id}' AND ticker = '{ticker}'
        ORDER BY date DESC
    """)

def get_all_history(fund_id: str, n_days: int = 30) -> pd.DataFrame:
    return query(f"""
        SELECT
            date                                 AS 日期,
            ticker                               AS 代號,
            name                                 AS 名稱,
            action                               AS 動作,
            ROUND(weight_today * 100, 2)         AS 今日權重,
            ROUND(delta        * 100, 2)         AS 權重變化,
            delta_shares                         AS 股數變化
        FROM daily_changes
        WHERE fund_id = '{fund_id}'
        ORDER BY date DESC, ABS(delta) DESC
        LIMIT {n_days * 30}
    """)

def get_holdings_snapshot(fund_id: str, target_date: str) -> pd.DataFrame:
    return query(f"""
        SELECT
            ticker                               AS 代號,
            name                                 AS 名稱,
            ROUND(weight * 100, 2)               AS 權重,
            shares                               AS 股數
        FROM holdings
        WHERE fund_id = '{fund_id}' AND date = '{target_date}'
        ORDER BY weight DESC
    """)

# ── HTML 表格渲染 ──────────────────────────────────
TABLE_STYLE = """
<style>
.etf-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
    font-family: inherit;
}
.etf-table th {
    text-align: left;
    padding: 6px 12px;
    border-bottom: 2px solid #444;
    color: #aaa;
    font-weight: 500;
    white-space: nowrap;
}
.etf-table td {
    padding: 6px 12px;
    border-bottom: 1px solid #2a2a2a;
    white-space: nowrap;
}
.etf-table tr:hover td { background: #1e1e1e; }
.pos { color: #26a641; font-weight: 600; }
.neg { color: #f85149; font-weight: 600; }
</style>
"""

def render_changes_html(display: pd.DataFrame, delta_raw: pd.Series, fund_id: str) -> str:
    rows = ""
    for i, row in display.iterrows():
        flag = get_flag(row["代號"]) if fund_id == "00988A" else ""
        flag_str = f"{flag} " if flag else ""
        d = delta_raw.iloc[i]
        cls = "pos" if d > 0 else ("neg" if d < 0 else "")
        rows += (
            f"<tr>"
            f"<td>{row['代號']}</td>"
            f"<td>{flag_str}{row['名稱']}</td>"
            f"<td>{row['今日權重']:.2f}%</td>"
            f"<td>{row['昨日權重']:.2f}%</td>"
            f"<td class='{cls}'>{d:+.2f}%</td>"
            f"<td>{int(row['股數變化']):,}</td>"
            f"<td>{int(row['昨日股數']):,}</td>"
            f"<td>{int(row['今日股數']):,}</td>"
            f"</tr>"
        )
    return (
        TABLE_STYLE
        + "<table class='etf-table'>"
        + "<thead><tr>"
        + "<th>代號</th><th>名稱</th><th>今日權重</th><th>昨日權重</th>"
        + "<th>權重變化</th><th>股數變化</th><th>昨日股數</th><th>今日股數</th>"
        + "</tr></thead>"
        + f"<tbody>{rows}</tbody></table>"
    )

def render_snapshot_html(df: pd.DataFrame, fund_id: str) -> str:
    rows = ""
    for _, row in df.iterrows():
        flag = get_flag(row["代號"]) if fund_id == "00988A" else ""
        flag_str = f"{flag} " if flag else ""
        rows += (
            f"<tr>"
            f"<td>{row['代號']}</td>"
            f"<td>{flag_str}{row['名稱']}</td>"
            f"<td>{row['權重']:.2f}%</td>"
            f"<td>{int(row['股數']):,}</td>"
            f"</tr>"
        )
    return (
        TABLE_STYLE
        + "<table class='etf-table'>"
        + "<thead><tr><th>代號</th><th>名稱</th><th>權重</th><th>股數</th></tr></thead>"
        + f"<tbody>{rows}</tbody></table>"
    )

def render_history_html(df: pd.DataFrame, fund_id: str) -> str:
    rows = ""
    for _, row in df.iterrows():
        flag = get_flag(row["代號"]) if fund_id == "00988A" else ""
        flag_str = f"{flag} " if flag else ""
        d = row["權重變化"]
        cls = "pos" if d > 0 else ("neg" if d < 0 else "")
        rows += (
            f"<tr>"
            f"<td>{row['日期']}</td>"
            f"<td>{row['代號']}</td>"
            f"<td>{flag_str}{row['名稱']}</td>"
            f"<td>{row['動作']}</td>"
            f"<td>{row['今日權重']:.2f}%</td>"
            f"<td class='{cls}'>{d:+.2f}%</td>"
            f"<td>{int(row['股數變化']):,}</td>"
            f"</tr>"
        )
    return (
        TABLE_STYLE
        + "<table class='etf-table'>"
        + "<thead><tr>"
        + "<th>日期</th><th>代號</th><th>名稱</th><th>動作</th>"
        + "<th>今日權重</th><th>權重變化</th><th>股數變化</th>"
        + "</tr></thead>"
        + f"<tbody>{rows}</tbody></table>"
    )

# ── 頁面設定 ──────────────────────────────────────
st.set_page_config(
    page_title="ActiveFundRadar",
    page_icon="📡",
    layout="wide",
)

st.title("📡 ActiveFundRadar")
st.caption("主動型 ETF 持倉監控系統")

# ── 側欄 ──────────────────────────────────────────
with st.sidebar:
    st.header("🔧 篩選條件")
    fund_id = st.selectbox(
        "選擇基金",
        options=list(FUND_NAMES.keys()),
        format_func=lambda x: f"{x} {FUND_NAMES[x]}",
    )

    available_dates = get_available_dates(fund_id)
    if not available_dates:
        st.warning("此基金尚無異動資料")
        st.stop()

    selected_date = st.selectbox("選擇日期", options=available_dates)
    st.divider()
    st.caption(f"資料庫路徑：{DB_PATH}")

# ── Tab 佈局 ──────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📊 當日異動", "📋 完整持倉", "📈 歷史紀錄"])

# ════════════════════════════════════════════════
# Tab 1：當日異動
# ════════════════════════════════════════════════
with tab1:
    st.subheader(f"{selected_date}　{fund_id} {FUND_NAMES[fund_id]}　持倉異動")

    df_changes = get_changes(fund_id, selected_date)

    if df_changes.empty:
        st.info("此日期無異動資料")
    else:
        col1, col2, col3, col4 = st.columns(4)
        for action, col, color in [
            ("建倉", col1, "🟢"),
            ("清倉", col2, "🔴"),
            ("加碼", col3, "📈"),
            ("減碼", col4, "📉"),
        ]:
            cnt = len(df_changes[df_changes["動作"] == action])
            col.metric(f"{color} {action}", f"{cnt} 檔")

        st.divider()

        for action in ["建倉", "清倉", "加碼", "減碼"]:
            subset = df_changes[df_changes["動作"] == action].reset_index(drop=True)
            if subset.empty:
                continue

            st.markdown(f"#### {ACTION_COLOR[action]} {action}")
            display = subset.drop(columns=["動作"])
            delta_raw = display["權重變化"].copy()
            st.markdown(
                render_changes_html(display, delta_raw, fund_id),
                unsafe_allow_html=True,
            )

        # 點選個股查歷史
        st.divider()
        st.markdown("#### 🔍 查詢個股歷史異動")
        tickers = df_changes["代號"].tolist()
        names   = df_changes["名稱"].tolist()
        options = [f"{t} {n}" for t, n in zip(tickers, names)]
        chosen  = st.selectbox("選擇個股", options=["— 請選擇 —"] + options)

        if chosen != "— 請選擇 —":
            chosen_ticker = chosen.split(" ")[0]
            hist = get_history(fund_id, chosen_ticker)
            if not hist.empty:
                st.dataframe(hist, use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════
# Tab 2：完整持倉快照
# ════════════════════════════════════════════════
with tab2:
    st.subheader(f"{selected_date}　{fund_id} {FUND_NAMES[fund_id]}　完整持倉")

    snap_date_df = query(f"""
        SELECT DISTINCT date FROM holdings
        WHERE fund_id = '{fund_id}' AND date <= '{selected_date}'
        ORDER BY date DESC LIMIT 1
    """)

    if snap_date_df.empty:
        st.info("此日期前無持倉快照資料")
    else:
        snap_date = snap_date_df.iloc[0]["date"]
        if snap_date != selected_date:
            st.caption(f"（holdings 最近資料為 {snap_date}）")

        df_snap = get_holdings_snapshot(fund_id, snap_date)

        col_a, col_b = st.columns([2, 1])
        with col_a:
            st.markdown(
                render_snapshot_html(df_snap, fund_id),
                unsafe_allow_html=True,
            )
        with col_b:
            st.metric("持股總數", f"{len(df_snap)} 檔")
            st.metric("權重加總", f"{df_snap['權重'].sum():.2f}%")
            top5 = df_snap.head(5)
            st.markdown("**前五大持股**")
            for _, row in top5.iterrows():
                flag = get_flag(row["代號"]) if fund_id == "00988A" else ""
                flag_str = f"{flag} " if flag else ""
                st.markdown(f"- {row['代號']} {flag_str}{row['名稱']}　{row['權重']}%")

# ════════════════════════════════════════════════
# Tab 3：歷史紀錄
# ════════════════════════════════════════════════
with tab3:
    st.subheader(f"{fund_id} {FUND_NAMES[fund_id]}　歷史異動紀錄")

    col_left, col_right = st.columns([1, 3])

    with col_left:
        action_filter = st.multiselect(
            "動作篩選",
            options=["建倉", "清倉", "加碼", "減碼"],
            default=["建倉", "清倉", "加碼", "減碼"],
        )
        keyword = st.text_input("代號 / 名稱搜尋")

    df_hist = get_all_history(fund_id)

    if not df_hist.empty:
        if action_filter:
            df_hist = df_hist[df_hist["動作"].isin(action_filter)]
        if keyword:
            mask = (
                df_hist["代號"].str.contains(keyword, case=False, na=False) |
                df_hist["名稱"].str.contains(keyword, case=False, na=False)
            )
            df_hist = df_hist[mask]

        df_hist = df_hist.reset_index(drop=True)

        with col_right:
            st.caption(f"共 {len(df_hist)} 筆")

        st.markdown(
            render_history_html(df_hist, fund_id),
            unsafe_allow_html=True,
        )
    else:
        st.info("尚無歷史資料")
