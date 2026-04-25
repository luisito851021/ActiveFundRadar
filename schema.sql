-- 在 Supabase SQL Editor 執行此檔案建立資料表

CREATE TABLE IF NOT EXISTS holdings (
    fund_id  TEXT    NOT NULL,
    date     TEXT    NOT NULL,
    ticker   TEXT    NOT NULL,
    name     TEXT,
    shares   BIGINT,
    weight   DOUBLE PRECISION,
    PRIMARY KEY (fund_id, date, ticker)
);

CREATE TABLE IF NOT EXISTS daily_changes (
    fund_id      TEXT    NOT NULL,
    date         TEXT    NOT NULL,
    ticker       TEXT    NOT NULL,
    name         TEXT,
    action       TEXT,
    shares_today BIGINT,
    shares_yest  BIGINT,
    delta_shares BIGINT,
    weight_today DOUBLE PRECISION,
    weight_yest  DOUBLE PRECISION,
    delta        DOUBLE PRECISION,
    PRIMARY KEY (fund_id, date, ticker)
);

-- 加速查詢的索引
CREATE INDEX IF NOT EXISTS idx_holdings_fund_date       ON holdings      (fund_id, date);
CREATE INDEX IF NOT EXISTS idx_daily_changes_fund_date  ON daily_changes (fund_id, date);
CREATE INDEX IF NOT EXISTS idx_daily_changes_fund_ticker ON daily_changes (fund_id, ticker);
