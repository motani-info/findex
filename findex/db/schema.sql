-- findex v2 スキーマ — 正本は docs/design/data-model.md (D3)
-- 原則: ①一方向フロー（取得→導出→評価→出力）②粒度別テーブル ③計算は導出層に集約
--       ④全取得値に来歴メタ(source/confidence/as_of/collected_at) ⑤履歴を消さない
--       ⑥修正可能(C)と構造的不能(B/D)を区別（B/Dはresult_override+N+で扱う）
-- 外部キーは張らず code で論理結合（SQLite・移行容易性。整合性は照合ジョブ+D6で担保）

-- ══ 取得層 ══════════════════════════════════════════════

-- stocks — 銘柄マスター＋会計メタ（D3 §2）
-- 全上場「普通株」のみ（ETF/REIT/優先株/出資証券は除外。design-review #8）
-- 上場廃止銘柄も is_active=0 + delisting_date で残す（D8 生存バイアス排除）
CREATE TABLE IF NOT EXISTS stocks (
    code                    TEXT PRIMARY KEY,   -- 4桁証券コード
    name                    TEXT NOT NULL,
    market                  TEXT,               -- プライム/スタンダード/グロース 等
    sector33                TEXT,               -- 33業種
    edinet_code             TEXT,               -- EDINETコードリストzip由来
    fiscal_period_end_month INTEGER,            -- 決算期末月（FY正規化の基準・地雷2）
    consolidated            INTEGER,            -- 連結有無（指標を同一基準に）
    accounting_standard     TEXT,               -- JGAAP/IFRS/US（EDINETラベル辞書切替に必須）
    listing_date            TEXT,               -- 上場年月日（打ち切り判定の独立シグナル・地雷7）
    founded_date            TEXT,               -- 設立年月日（補助）
    first_data_date         TEXT,               -- DB内最古データ日（導出。単独では打ち切り判定不可）
    is_active               INTEGER NOT NULL DEFAULT 1,  -- 1=現役 0=上場廃止
    delisting_date          TEXT,               -- 上場廃止日（生存バイアス対策・D8前提）
    updated_at              TEXT NOT NULL
);

-- price_history — 株価履歴（2000年〜。yfinance主・J-Quants補完）（D3 §3）
CREATE TABLE IF NOT EXISTS price_history (
    code      TEXT NOT NULL,
    date      TEXT NOT NULL,                    -- YYYY-MM-DD
    close_adj REAL NOT NULL,                    -- 調整後終値
    volume    INTEGER,
    source    TEXT NOT NULL,                    -- jquants / yfinance
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_price_code_date ON price_history (code, date);

-- dividend_events — 配当イベント生データ（権利落ち日粒度。合成厳禁・地雷1）（D3 §4）
CREATE TABLE IF NOT EXISTS dividend_events (
    code    TEXT NOT NULL,
    ex_date TEXT NOT NULL,                      -- 権利落ち日
    amount  REAL NOT NULL,                      -- 分割調整済み1株配当
    source  TEXT NOT NULL DEFAULT 'yfinance',
    PRIMARY KEY (code, ex_date)
);

-- dividend_annual — 会計年度別配当（正準系列・findexの心臓部）（D3 §5）
-- ストリーク・配当CAGRはこのテーブルだけから計算
-- 競合時の優先: manual > ir > haitoukin > jquants > events
CREATE TABLE IF NOT EXISTS dividend_annual (
    code        TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,               -- 4月始まり会計年度（地雷2）
    dps         REAL NOT NULL,                  -- 年間1株配当（分割調整済み）
    source      TEXT NOT NULL,                  -- events/jquants/haitoukin/ir/manual
    confidence  TEXT,                           -- verified/present/review
    as_of       TEXT,                           -- 公表/基準時点
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (code, fiscal_year)
);
CREATE INDEX IF NOT EXISTS idx_div_annual_code ON dividend_annual (code, fiscal_year);

-- financial_snapshots — 年度別財務（J-Quants + EDINET。履歴保持）（D3 §6）
CREATE TABLE IF NOT EXISTS financial_snapshots (
    code        TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    -- PL・1株（jquants）
    revenue              REAL,
    operating_income     REAL,
    net_income           REAL,
    eps                  REAL,
    bps                  REAL,
    shares_outstanding   REAL,
    -- BS主要（jquants/edinet）
    total_assets         REAL,
    equity_attributable  REAL,                  -- 自己資本（親会社株主）
    -- CF（jquants）
    operating_cf         REAL,
    capex                REAL,                   -- EDINET（FCF=CFO−capexの鍵・旧0%）
    cash_and_equivalents REAL,
    -- BS深掘り（edinet）
    retained_earnings    REAL,
    current_assets       REAL,
    total_liabilities    REAL,
    interest_bearing_debt REAL,
    interest_expense     REAL,                  -- cost_of_debt算出（ROIC-WACC）
    investment_securities REAL,                 -- ネットキャッシュ×0.7（旧DB不在）
    effective_tax_rate   REAL,                  -- ROIC NOPAT
    -- 導出
    beta                 REAL,                  -- 株価×TOPIX回帰（自前算出）
    market_cap           REAL,
    -- 来歴メタ（§1）
    source      TEXT NOT NULL,
    confidence  TEXT,
    as_of       TEXT,
    collected_at TEXT NOT NULL,
    PRIMARY KEY (code, fiscal_year)
);

-- result_overrides — 結果補正（公表値オーバーライド・汎用）（D3 §7・D2.7）
-- 旧 streak_overrides をフィールド非依存に一般化。昇格のみ(override≥機械計算)
CREATE TABLE IF NOT EXISTS result_overrides (
    code              TEXT NOT NULL,
    field             TEXT NOT NULL,            -- consecutive_dividend_growth_years 等
    value             REAL NOT NULL,            -- 公表された結果値
    as_of_fiscal_year INTEGER NOT NULL,         -- その値が何年度時点か（経年補正に必須）
    source            TEXT NOT NULL,            -- zai/ir/minkabu 等
    source_url        TEXT,
    definition_note   TEXT,                     -- 定義差の根拠（例「上場前から起算」）
    confidence        TEXT NOT NULL,            -- verified（2ソース一致）/ single
    verified_at       TEXT,
    verified_by       TEXT,
    PRIMARY KEY (code, field)
);

-- ══ 導出層 ══════════════════════════════════════════════

-- computed_metrics — 派生指標＋claim別グレード（導出層の唯一の出口）（D3 §8）
-- スコアラはここだけ読む。1銘柄1行・最新値。
-- status_json: 各指標の5状態(ok/zero_legit/missing/insufficient/censored)を保持（動的分母の材料）
-- source_json: 各指標の由来(machine/override/censored)を保持（結果補正が効いたかの監査）
CREATE TABLE IF NOT EXISTS computed_metrics (
    code TEXT PRIMARY KEY,
    -- 価格由来（日次）
    per REAL, pbr REAL, current_market_cap REAL, div_yield REAL,
    mix_coefficient REAL, net_cash_per REAL,
    -- 財務由来（四半期）
    equity_ratio REAL, debt_to_equity REAL, roe REAL, operating_margin REAL,
    eps_growth_5y REAL, revenue_growth_5y_cagr REAL,
    roic_minus_wacc REAL, fcf_payout_coverage REAL,
    retained_earnings_div_ratio REAL, payout_ratio REAL,
    doe REAL,                                   -- =ROE×配当性向（D4.5 v4新規）
    -- 配当由来（半年）
    annual_div REAL,
    yield_on_cost_5y REAL, yield_on_cost_10y REAL,  -- YoC（取得利回り・D4.5）
    dividend_multiple REAL,                     -- DPS倍率（YoC質係数の分解元）
    dividend_quality TEXT,                      -- sound/payout_driven/cyclical（増配の質）
    consecutive_no_cut_years INTEGER,
    consecutive_dividend_growth_years INTEGER,
    streak_is_censored INTEGER NOT NULL DEFAULT 0,  -- 1=「N年以上」表示（必須機能）
    dividend_growth_5y_cagr REAL, dividend_growth_10y_cagr REAL,
    dividend_reliability REAL, dividend_cut_count_20y INTEGER,
    -- 品質（claim別グレード A〜D。D2 §6）
    grade_dividend TEXT, grade_valuation TEXT, grade_health TEXT, grade_capital TEXT,
    identity_ok INTEGER,                        -- 恒等式チェック（DOE=ROE×payout 等）
    -- 来歴・状態（materialize最小化のためJSONで保持）
    status_json TEXT,                           -- {指標: 5状態}
    source_json TEXT,                           -- {指標: machine/override/censored}
    -- 更新時刻
    price_computed_at TEXT, fin_computed_at TEXT, div_computed_at TEXT
);

-- ══ 評価層 ══════════════════════════════════════════════

-- dividend_scores — スコア履歴（採点日別に積む）（D3 §9）
CREATE TABLE IF NOT EXISTS dividend_scores (
    code            TEXT NOT NULL,
    scored_at       TEXT NOT NULL,
    rule_version_id INTEGER NOT NULL,
    total_score     REAL NOT NULL,
    grade_dividend  TEXT, grade_valuation TEXT, grade_health TEXT, grade_capital TEXT,
    score_json      TEXT,                       -- 指標ごとの内訳（status併記）
    PRIMARY KEY (code, scored_at)
);

-- rule_versions — rules.yaml を SHA256 で版管理（再現性）
CREATE TABLE IF NOT EXISTS rule_versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rules_sha256 TEXT NOT NULL UNIQUE,
    version_tag  TEXT,                          -- v4 / v5 等
    created_at   TEXT NOT NULL
);

-- ══ 出力層（D5） ════════════════════════════════════════

-- themes — X/サイトのテーマ定義レジストリ
CREATE TABLE IF NOT EXISTS themes (
    theme_id  TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    angle_ref TEXT,                             -- analysis-angles.md の切り口参照
    format    TEXT,                             -- A(単発)/B(画像主体)/C(スレッド)
    enabled   INTEGER NOT NULL DEFAULT 1
);

-- post_queue — 生成済み・投稿待ち
CREATE TABLE IF NOT EXISTS post_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    theme_id     TEXT NOT NULL,
    body         TEXT NOT NULL,
    image_paths  TEXT,                          -- json: 添付PNGパス
    claims       TEXT,                          -- json: 使用数字とstatus/source/as_of（事後監査）
    gates_passed INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'draft', -- draft/approved/posted/blocked
    created_at   TEXT NOT NULL
);

-- post_log — X投稿履歴。本文SHA256で30日窓の二重投稿防止
CREATE TABLE IF NOT EXISTS post_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    posted_at   TEXT NOT NULL,
    theme       TEXT NOT NULL,
    body        TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    tweet_id    TEXT,
    status      TEXT NOT NULL,                  -- posted/failed/skipped
    engagement  TEXT                            -- json: いいね/RT/インプレ（事後取得）
);

-- ══ バックテスト（D8・モデル検証） ═════════════════════════
-- PIT（時点正確）スコアとアウトカム。現在採点 dividend_scores とは別系統。

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_version_id INTEGER NOT NULL,
    as_of_grid      TEXT NOT NULL,              -- 例 2008..2024
    universe_def    TEXT NOT NULL,              -- 時点ユニバース定義（生存バイアス排除）
    params_json     TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_scores (
    run_id      INTEGER NOT NULL,
    code        TEXT NOT NULL,
    as_of_date  TEXT NOT NULL,                  -- 入力をこの時点で絞って算出（look-ahead排除）
    total_score REAL,
    score_json  TEXT,
    grade_dividend TEXT, grade_valuation TEXT, grade_health TEXT, grade_capital TEXT,
    PRIMARY KEY (run_id, code, as_of_date)
);

CREATE TABLE IF NOT EXISTS backtest_outcomes (
    code            TEXT NOT NULL,
    as_of_date      TEXT NOT NULL,
    horizon_y       INTEGER NOT NULL,
    fwd_div_cut     INTEGER,                    -- 期間内に減配したか（減配回避の検証）
    fwd_dps_cagr    REAL,                       -- 前方DPS成長（増配実現）
    fwd_total_return REAL,                      -- トータルリターン
    fwd_max_dd      REAL,                       -- 最大ドローダウン
    PRIMARY KEY (code, as_of_date, horizon_y)
);

CREATE TABLE IF NOT EXISTS backtest_metrics (
    run_id    INTEGER NOT NULL,
    level     TEXT NOT NULL,                    -- total/claim/indicator
    key       TEXT NOT NULL,                    -- claim名 or 指標名
    metric    TEXT NOT NULL,                    -- spearman/IC/decile_spread/grade_calib
    value     REAL,
    sample_n  INTEGER,
    PRIMARY KEY (run_id, level, key, metric)
);

-- ══ 運用 ════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS stock_splits (
    code          TEXT NOT NULL,
    date          TEXT NOT NULL,      -- 分割効力日 (YYYY-MM-DD)
    ratio         REAL NOT NULL,      -- 分割比率（例: 15.0 = 1株→15株）
    source        TEXT NOT NULL DEFAULT 'yfinance',
    collected_at  TEXT NOT NULL,
    PRIMARY KEY (code, date)
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
