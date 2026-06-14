-- findex v2 スキーマ。docs/design/pre2000-data.md §4 / requirements.md §7
-- 原則: 一方向フロー / 粒度別テーブル / source+更新時刻 / 計算は導出層に集約

-- ── 取得層 ──────────────────────────────────────────────

-- 銘柄マスター（上場日・設立日を保持＝2000年問題の打ち切り判定に必須）
CREATE TABLE IF NOT EXISTS stocks (
    code            TEXT PRIMARY KEY,      -- 4桁証券コード
    name            TEXT NOT NULL,
    market          TEXT,                  -- プライム/スタンダード/グロース等
    sector          TEXT,                  -- 33業種
    edinet_code     TEXT,
    listing_date    TEXT,                  -- 上場年月日（kabutan等。独立した年齢シグナル）
    founded_date    TEXT,                  -- 設立年月日（補助）
    first_data_date TEXT,                  -- DB内最古データ日（導出値。単独では打ち切り判定不可）
    is_active       INTEGER NOT NULL DEFAULT 1,
    updated_at      TEXT NOT NULL
);

-- 株価履歴（調整後終値）
CREATE TABLE IF NOT EXISTS price_history (
    code   TEXT NOT NULL,
    date   TEXT NOT NULL,
    close  REAL NOT NULL,
    volume INTEGER,
    PRIMARY KEY (code, date)
);

-- 配当イベント（生データ。実イベントのみ。合成レコード厳禁＝地雷1）
CREATE TABLE IF NOT EXISTS dividend_events (
    code    TEXT NOT NULL,
    ex_date TEXT NOT NULL,                 -- 権利落ち日
    amount  REAL NOT NULL,                 -- 分割調整済み1株配当
    source  TEXT NOT NULL DEFAULT 'yfinance',
    PRIMARY KEY (code, ex_date)
);

-- 会計年度別配当（正準系列。ストリーク・CAGRはここだけから計算）
CREATE TABLE IF NOT EXISTS dividend_annual (
    code        TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,          -- 4月始まり年度（地雷2）
    dps         REAL NOT NULL,
    source      TEXT NOT NULL,             -- 'events'|'haitoukin'|'ir'|'manual'
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (code, fiscal_year)
);
CREATE INDEX IF NOT EXISTS idx_div_annual_code ON dividend_annual (code, fiscal_year);

-- 公表値オーバーライド（地雷5。公表値 > 機械計算 のときだけ昇格）
CREATE TABLE IF NOT EXISTS streak_overrides (
    code              TEXT PRIMARY KEY,
    growth_years      INTEGER,             -- NULL=上書きしない
    nocut_years       INTEGER,
    as_of_fiscal_year INTEGER NOT NULL,
    source_url        TEXT NOT NULL,
    verified_at       TEXT NOT NULL
);

-- 年度別財務スナップショット（履歴を残す。1行上書きしない）
CREATE TABLE IF NOT EXISTS financial_snapshots (
    code        TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    eps REAL, bps REAL, shares REAL, roe REAL, operating_margin REAL,
    equity_ratio REAL, debt_to_equity REAL, payout_ratio REAL,
    free_cashflow REAL, operating_cashflow REAL, capex REAL,
    total_assets REAL, stockholders_equity REAL, retained_earnings REAL,
    revenue REAL, market_cap REAL, beta REAL,
    source      TEXT NOT NULL DEFAULT 'yfinance',
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (code, fiscal_year)
);

-- ── 導出層 ──────────────────────────────────────────────

-- 派生指標（導出層の唯一の出口。1銘柄1行・最新値）
CREATE TABLE IF NOT EXISTS computed_metrics (
    code TEXT PRIMARY KEY,
    per REAL, pbr REAL, current_market_cap REAL, div_yield REAL,
    mix_coefficient REAL, net_cash_per REAL,
    equity_ratio REAL, debt_to_equity REAL, roe REAL, operating_margin REAL,
    eps_growth_5y REAL, revenue_growth_5y_cagr REAL,
    roic_minus_wacc REAL, fcf_payout_coverage REAL,
    retained_earnings_div_ratio REAL, payout_ratio REAL,
    annual_div REAL,
    consecutive_no_cut_years INTEGER,
    consecutive_dividend_growth_years INTEGER,
    streak_is_censored INTEGER DEFAULT 0,  -- 1=「N年以上」表示（必須機能）
    dividend_growth_5y_cagr REAL, dividend_growth_10y_cagr REAL,
    dividend_reliability REAL, dividend_cut_count_20y INTEGER,
    price_computed_at TEXT, fin_computed_at TEXT, div_computed_at TEXT
);

-- ── 評価層 ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS dividend_scores (
    code            TEXT NOT NULL,
    scored_at       TEXT NOT NULL,
    rule_version_id INTEGER NOT NULL,
    total_score     REAL NOT NULL,
    score_json      TEXT,                  -- 指標ごとの内訳
    PRIMARY KEY (code, scored_at)
);

CREATE TABLE IF NOT EXISTS rule_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rules_sha256 TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

-- ── 出力層・運用 ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS post_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    posted_at   TEXT NOT NULL,
    theme       TEXT NOT NULL,
    body        TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    tweet_id    TEXT,
    status      TEXT NOT NULL              -- 'posted'|'failed'|'skipped'
);

CREATE TABLE IF NOT EXISTS run_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job        TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    status     TEXT NOT NULL,
    detail     TEXT
);

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
