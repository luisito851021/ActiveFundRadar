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

# ── 頁面設定 ──────────────────────────────────────
st.set_page_config(
    page_title="ActiveFundRadar",
    page_icon="📡",
    layout="wide",
)

st.title("📡 ActiveFundRadar")
st.caption("主動型 ETF 持倉監控系統")

# ── 側欄：選基金 ──────────────────────────────────
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
        # 統計卡片
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

        # 各動作分區顯示
        for action in ["建倉", "清倉", "加碼", "減碼"]:
            subset = df_changes[df_changes["動作"] == action]
            if subset.empty:
                continue

            icon = ACTION_COLOR[action]
            st.markdown(f"#### {icon} {action}")

            display = subset.drop(columns=["動作"]).reset_index(drop=True)

            # 權重變化上色
            def color_delta(val):
                if val > 0:
                    return "color: #26a641"
                elif val < 0:
                    return "color: #f85149"
                return ""

            st.dataframe(
                display.style.map(color_delta, subset=["權重變化"]),
                use_container_width=True,
                hide_index=True,
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

    # 找 holdings 裡最接近 selected_date 的日期
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
            st.dataframe(df_snap, use_container_width=True, hide_index=True)
        with col_b:
            st.metric("持股總數", f"{len(df_snap)} 檔")
            st.metric("權重加總", f"{df_snap['權重'].sum():.2f}%")
            top5 = df_snap.head(5)
            st.markdown("**前五大持股**")
            for _, row in top5.iterrows():
                st.markdown(f"- {row['代號']} {row['名稱']}　{row['權重']}%")

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
        # 套用篩選
        if action_filter:
            df_hist = df_hist[df_hist["動作"].isin(action_filter)]
        if keyword:
            mask = (
                df_hist["代號"].str.contains(keyword, case=False, na=False) |
                df_hist["名稱"].str.contains(keyword, case=False, na=False)
            )
            df_hist = df_hist[mask]

        with col_right:
            st.caption(f"共 {len(df_hist)} 筆")

        st.dataframe(df_hist, use_container_width=True, hide_index=True)
    else:
        st.info("尚無歷史資料")