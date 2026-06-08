"""SQLite永続化層: ~/.findex/db/findex.db"""
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

DB_PATH = Path.home() / ".findex" / "db" / "findex.db"

# ── マイグレーション定義 ─────────────────────────────────────────
MIGRATIONS: dict[int, list[str]] = {
    7: [
        "ALTER TABLE computed_metrics ADD COLUMN roe REAL",
        "ALTER TABLE computed_metrics ADD COLUMN operating_margin REAL",
        "ALTER TABLE computed_metrics ADD COLUMN payout_ratio REAL",
    ],
    6: [
        """
        CREATE TABLE IF NOT EXISTS momentum_scores (
            code              TEXT NOT NULL,
            scored_at         TEXT NOT NULL,
            total_score       REAL NOT NULL,
            s_rel_ret_3m      REAL,
            s_rel_ret_12m     REAL,
            s_hi52_ratio      REAL,
            s_rev_growth      REAL,
            s_eps_growth      REAL,
            s_roe             REAL,
            s_operating_margin REAL,
            s_vol_ratio       REAL,
            PRIMARY KEY (code, scored_at)
        )
        """,
    ],
    5: [
        """
        CREATE TABLE IF NOT EXISTS dividend_scores (
            code              TEXT NOT NULL,
            scored_at         TEXT NOT NULL,
            rule_version_id   INTEGER NOT NULL,
            total_score       REAL NOT NULL,
            s_consecutive_no_cut_years          REAL,
            s_consecutive_dividend_growth_years REAL,
            s_dividend_reliability              REAL,
            s_dividend_growth_10y_cagr          REAL,
            s_payout_ratio                      REAL,
            s_fcf_payout_coverage               REAL,
            s_eps_growth_5y                     REAL,
            s_revenue_growth_5y_cagr            REAL,
            s_roe                               REAL,
            s_operating_margin                  REAL,
            s_div_yield                         REAL,
            s_mix_coefficient                   REAL,
            s_net_cash_per                      REAL,
            s_roic_minus_wacc                   REAL,
            s_retained_earnings_div_ratio       REAL,
            PRIMARY KEY (code, scored_at)
        )
        """,
    ],
    4: [
        """
        CREATE TABLE IF NOT EXISTS raw_financials (
            code                 TEXT PRIMARY KEY,
            eps                  REAL,
            bps                  REAL,
            shares_outstanding   REAL,
            roe                  REAL,
            operating_margins    REAL,
            payout_ratio         REAL,
            free_cashflow        REAL,
            operating_cashflow   REAL,
            capital_expenditures REAL,
            dividend_rate        REAL,
            market_cap           REAL,
            beta                 REAL,
            total_assets         REAL,
            stockholders_equity  REAL,
            current_assets       REAL,
            total_liabilities    REAL,
            long_term_debt       REAL,
            short_term_debt      REAL,
            retained_earnings    REAL,
            diluted_eps_latest   REAL,
            total_revenue_latest REAL,
            diluted_eps_5y_ago   REAL,
            total_revenue_5y_ago REAL,
            diluted_eps_periods  INTEGER,
            total_revenue_periods INTEGER,
            fetched_at           TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS computed_metrics (
            code                              TEXT PRIMARY KEY,
            per                               REAL,
            pbr                               REAL,
            current_market_cap                REAL,
            div_yield                         REAL,
            mix_coefficient                   REAL,
            net_cash_per                      REAL,
            equity_ratio                      REAL,
            debt_to_equity                    REAL,
            eps_growth_5y                     REAL,
            revenue_growth_5y_cagr            REAL,
            roic_minus_wacc                   REAL,
            fcf_payout_coverage               REAL,
            retained_earnings_div_ratio       REAL,
            annual_div                        REAL,
            consecutive_no_cut_years          INTEGER,
            consecutive_dividend_growth_years INTEGER,
            dividend_growth_5y_cagr           REAL,
            dividend_growth_10y_cagr          REAL,
            dividend_reliability              REAL,
            dividend_cut_count_20y            INTEGER,
            ret_3m                            REAL,
            ret_12m                           REAL,
            rel_ret_3m                        REAL,
            rel_ret_12m                       REAL,
            hi52_ratio                        REAL,
            price_computed_at                 TEXT,
            fin_computed_at                   TEXT,
            div_computed_at                   TEXT
        )
        """,
    ],
    3: [
        # 株価履歴テーブル（モメンタム計算用）
        """
        CREATE TABLE IF NOT EXISTS price_history (
            code   TEXT NOT NULL,
            date   TEXT NOT NULL,
            close  REAL NOT NULL,
            volume INTEGER,
            PRIMARY KEY (code, date)
        )
        """,
        # 配当履歴テーブル（生データ蓄積用）
        """
        CREATE TABLE IF NOT EXISTS dividend_history (
            code    TEXT NOT NULL,
            ex_date TEXT NOT NULL,
            amount  REAL NOT NULL,
            PRIMARY KEY (code, ex_date)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_price_history_code ON price_history (code, date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_div_history_code   ON dividend_history (code, ex_date DESC)",
    ],
    2: [
        # scores に更新タイムスタンプ列を追加（ALTER TABLE は既存列があればエラーを無視）
        "ALTER TABLE scores ADD COLUMN price_updated_at TEXT",
        "ALTER TABLE scores ADD COLUMN fin_updated_at   TEXT",
        "ALTER TABLE scores ADD COLUMN div_updated_at   TEXT",
        # Category B/C の安定値テーブル
        # daily update はここから EPS/BPS/shares/annual_div を読んでCategory A を計算
        """
        CREATE TABLE IF NOT EXISTS stock_fundamentals (
            code                              TEXT PRIMARY KEY,
            eps                               REAL,
            bps                               REAL,
            shares                            REAL,
            net_cash                          REAL,
            equity_ratio                      REAL,
            debt_to_equity                    REAL,
            roe                               REAL,
            operating_margin                  REAL,
            eps_growth_5y                     REAL,
            revenue_growth_5y_cagr            REAL,
            roic_minus_wacc                   REAL,
            fcf_payout_coverage               REAL,
            retained_earnings_div_ratio       REAL,
            payout_ratio                      REAL,
            annual_div                        REAL,
            consecutive_no_cut_years          INTEGER,
            consecutive_dividend_growth_years INTEGER,
            dividend_growth_5y_cagr           REAL,
            dividend_growth_10y_cagr          REAL,
            dividend_reliability              REAL,
            dividend_cut_count_20y            INTEGER,
            fin_updated_at                    TEXT,
            div_updated_at                    TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_fund_code ON stock_fundamentals (code)",
    ],
    1: [
        """
        CREATE TABLE IF NOT EXISTS stocks (
            code        TEXT    PRIMARY KEY,
            name        TEXT    NOT NULL,
            market      TEXT,
            sector      TEXT,
            edinet_code TEXT,
            updated_at  TEXT    NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rule_versions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rules_hash  TEXT    NOT NULL UNIQUE,
            rules_yaml  TEXT    NOT NULL,
            created_at  TEXT    NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scores (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            code             TEXT    NOT NULL,
            scored_at        TEXT    NOT NULL,
            rule_version_id  INTEGER NOT NULL,
            total_score      REAL    NOT NULL,
            score_json       TEXT    NOT NULL,
            raw_json         TEXT,
            FOREIGN KEY (code) REFERENCES stocks(code),
            FOREIGN KEY (rule_version_id) REFERENCES rule_versions(id),
            UNIQUE (code, scored_at, rule_version_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS run_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            mode        TEXT    NOT NULL,
            subset      TEXT,
            started_at  TEXT    NOT NULL,
            finished_at TEXT,
            total       INTEGER,
            succeeded   INTEGER,
            failed      INTEGER,
            skipped     INTEGER,
            exit_code   INTEGER
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            applied_at  TEXT    NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_scores_code_date  ON scores (code, scored_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_scores_date_score ON scores (scored_at, total_score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_stocks_market     ON stocks (market)",
        "CREATE INDEX IF NOT EXISTS idx_stocks_sector     ON stocks (sector)",
    ],
}


# ── 接続・マイグレーション ───────────────────────────────────────

def get_db() -> sqlite3.Connection:
    """DB接続を返す。初回はディレクトリ作成 + migrate() を実行。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """未適用のマイグレーションを順に実行する。"""
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = row[0] or 0
    except sqlite3.OperationalError:
        current = 0

    for version, stmts in sorted(MIGRATIONS.items()):
        if version > current:
            for stmt in stmts:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    # ALTER TABLE で既存列がある場合は無視
                    if "duplicate column" in str(e).lower():
                        pass
                    else:
                        raise
            conn.execute(
                "INSERT OR IGNORE INTO schema_version VALUES (?, datetime('now'))",
                (version,),
            )
    conn.commit()


# ── rule_versions ────────────────────────────────────────────────

def get_or_create_rule_version(conn: sqlite3.Connection, rules_path: Path) -> int:
    """rules.yaml の SHA256 で検索し、なければ INSERT。ID を返す。"""
    content = rules_path.read_text(encoding="utf-8")
    rules_hash = hashlib.sha256(content.encode()).hexdigest()
    row = conn.execute(
        "SELECT id FROM rule_versions WHERE rules_hash = ?", (rules_hash,)
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO rule_versions (rules_hash, rules_yaml, created_at) "
        "VALUES (?, ?, datetime('now'))",
        (rules_hash, content),
    )
    conn.commit()
    return cur.lastrowid


# ── stocks ───────────────────────────────────────────────────────

def upsert_stocks(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    """銘柄マスターを UPSERT する。"""
    from datetime import datetime
    now = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT OR REPLACE INTO stocks (code, name, market, sector, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (str(row["code"]), row.get("name", ""), row.get("market", ""),
             row.get("sector", ""), now)
            for _, row in df.iterrows()
        ],
    )
    conn.commit()


def get_stock_codes(conn: sqlite3.Connection,
                    market: str | None = None,
                    sector: str | None = None) -> list[str]:
    """フィルタ条件に合う銘柄コードを返す。"""
    sql = "SELECT code FROM stocks WHERE 1=1"
    params: list = []
    if market:
        sql += " AND market LIKE ?"
        params.append(f"%{market}%")
    if sector:
        sql += " AND sector LIKE ?"
        params.append(f"%{sector}%")
    return [r[0] for r in conn.execute(sql, params).fetchall()]


# ── scores ───────────────────────────────────────────────────────

def score_exists(conn: sqlite3.Connection,
                 code: str, scored_at: str, rule_version_id: int) -> bool:
    """当日・同ルールのスコアが既存か確認する。"""
    row = conn.execute(
        "SELECT id FROM scores WHERE code=? AND scored_at=? AND rule_version_id=?",
        (code, scored_at, rule_version_id),
    ).fetchone()
    return row is not None


def insert_score(conn: sqlite3.Connection,
                 code: str, scored_at: str,
                 rule_version_id: int,
                 score_json: dict,
                 raw_json: dict | None = None) -> None:
    """スコアを INSERT する。UNIQUE 制約違反は無視（差分スキップ）。"""
    conn.execute(
        "INSERT OR IGNORE INTO scores "
        "(code, scored_at, rule_version_id, total_score, score_json, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            code, scored_at, rule_version_id,
            score_json.get("total", 0.0),
            json.dumps(score_json, ensure_ascii=False),
            json.dumps(raw_json, ensure_ascii=False, default=str) if raw_json else None,
        ),
    )


def get_latest_scores(conn: sqlite3.Connection,
                      scored_at: str,
                      top_n: int | None = None) -> pd.DataFrame:
    """指定日のスコアを total_score 降順で返す。"""
    sql = (
        "SELECT s.code, st.name, st.market, st.sector, s.total_score, s.score_json "
        "FROM scores s LEFT JOIN stocks st ON s.code = st.code "
        "WHERE s.scored_at = ? ORDER BY s.total_score DESC"
    )
    if top_n:
        sql += f" LIMIT {top_n}"
    rows = conn.execute(sql, (scored_at,)).fetchall()
    return pd.DataFrame(rows, columns=["code", "name", "market", "sector",
                                       "total_score", "score_json"])


def get_score_history(conn: sqlite3.Connection, code: str) -> pd.DataFrame:
    """銘柄の全スコア履歴を返す。"""
    rows = conn.execute(
        "SELECT scored_at, total_score, rule_version_id FROM scores "
        "WHERE code=? ORDER BY scored_at DESC",
        (code,),
    ).fetchall()
    return pd.DataFrame(rows, columns=["scored_at", "total_score", "rule_version_id"])


# ── rescore ──────────────────────────────────────────────────────

def get_records_for_rescore(conn: sqlite3.Connection,
                             scored_at: str | None = None,
                             codes: list[str] | None = None) -> list[dict]:
    """rescore 対象レコードを返す。"""
    sql = "SELECT id, code, scored_at, score_json, raw_json FROM scores WHERE 1=1"
    params: list = []
    if scored_at:
        sql += " AND scored_at = ?"
        params.append(scored_at)
    if codes:
        placeholders = ",".join("?" * len(codes))
        sql += f" AND code IN ({placeholders})"
        params.extend(codes)
    rows = conn.execute(sql, params).fetchall()
    return [
        {"id": r[0], "code": r[1], "scored_at": r[2],
         "score_json": json.loads(r[3]) if r[3] else {},
         "raw_json":   json.loads(r[4]) if r[4] else {}}
        for r in rows
    ]


def update_score(conn: sqlite3.Connection,
                 record_id: int, rule_version_id: int,
                 score_json: dict, total_score: float) -> None:
    """rescore で再計算したスコアを上書きする。"""
    conn.execute(
        "UPDATE scores SET rule_version_id=?, score_json=?, total_score=? WHERE id=?",
        (rule_version_id,
         json.dumps(score_json, ensure_ascii=False),
         total_score, record_id),
    )


# ── run_log ──────────────────────────────────────────────────────

# ── stock_fundamentals ──────────────────────────────────────────

FUNDAMENTALS_COLS = [
    "eps", "bps", "shares", "net_cash",
    "equity_ratio", "debt_to_equity", "roe", "operating_margin",
    "eps_growth_5y", "revenue_growth_5y_cagr",
    "roic_minus_wacc", "fcf_payout_coverage",
    "retained_earnings_div_ratio", "payout_ratio",
    "annual_div",
    "consecutive_no_cut_years", "consecutive_dividend_growth_years",
    "dividend_growth_5y_cagr", "dividend_growth_10y_cagr",
    "dividend_reliability", "dividend_cut_count_20y",
    "fin_updated_at", "div_updated_at",
    "market_cap",
]


def upsert_fundamentals(conn: sqlite3.Connection, code: str, data: dict) -> None:
    """stock_fundamentals を UPSERT する。"""
    cols   = [c for c in FUNDAMENTALS_COLS if c in data]
    vals   = [data[c] for c in cols]
    cols_s = ", ".join(cols)
    plc    = ", ".join("?" * len(cols))
    upd    = ", ".join(f"{c}=excluded.{c}" for c in cols)
    conn.execute(
        f"INSERT INTO stock_fundamentals (code, {cols_s}) VALUES (?, {plc}) "
        f"ON CONFLICT(code) DO UPDATE SET {upd}",
        [code, *vals],
    )


def get_fundamentals(conn: sqlite3.Connection,
                     codes: list[str] | None = None) -> pd.DataFrame:
    """stock_fundamentals を DataFrame で返す。"""
    sql = "SELECT * FROM stock_fundamentals"
    params: list = []
    if codes:
        sql += f" WHERE code IN ({','.join('?'*len(codes))})"
        params = codes
    rows = conn.execute(sql, params).fetchall()
    cols = ["code"] + FUNDAMENTALS_COLS
    return pd.DataFrame(rows, columns=cols)


def get_latest_raw_json(conn: sqlite3.Connection,
                        codes: list[str] | None = None) -> dict[str, dict]:
    """各銘柄の最新 raw_json を {code: raw_dict} で返す。"""
    sql = (
        "SELECT code, raw_json FROM scores "
        "WHERE (code, scored_at) IN ("
        "  SELECT code, MAX(scored_at) FROM scores GROUP BY code"
        ")"
    )
    params: list = []
    if codes:
        sql += f" AND code IN ({','.join('?'*len(codes))})"
        params = codes
    rows = conn.execute(sql, params).fetchall()
    return {
        r[0]: json.loads(r[1]) if r[1] else {}
        for r in rows
    }


def upsert_score_with_raw(conn: sqlite3.Connection,
                           code: str, scored_at: str,
                           rule_version_id: int,
                           score_json: dict,
                           raw_json: dict,
                           price_updated_at: str | None = None,
                           fin_updated_at:   str | None = None,
                           div_updated_at:   str | None = None) -> None:
    """スコアを UPSERT（INSERT or REPLACE）する。日次更新用。

    同日に rule_version_id が変わっても重複行を作らないよう、
    まず (code, scored_at) で既存行を UPDATE し、なければ INSERT する。
    """
    updated = conn.execute(
        "UPDATE scores SET "
        "  rule_version_id=?, total_score=?, score_json=?, raw_json=?, "
        "  price_updated_at=? "
        "WHERE code=? AND scored_at=?",
        (
            rule_version_id,
            score_json.get("total", 0.0),
            json.dumps(score_json, ensure_ascii=False),
            json.dumps(raw_json, ensure_ascii=False, default=str),
            price_updated_at,
            code, scored_at,
        ),
    ).rowcount
    if updated == 0:
        conn.execute(
            "INSERT OR IGNORE INTO scores "
            "(code, scored_at, rule_version_id, total_score, score_json, raw_json, "
            " price_updated_at, fin_updated_at, div_updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                code, scored_at, rule_version_id,
                score_json.get("total", 0.0),
                json.dumps(score_json, ensure_ascii=False),
                json.dumps(raw_json, ensure_ascii=False, default=str),
                price_updated_at, fin_updated_at, div_updated_at,
            ),
        )


def bulk_insert_price_history(conn: sqlite3.Connection,
                               records: list[tuple[str, str, float, int | None]]) -> int:
    """price_history に一括 INSERT OR REPLACE する。
    既存レコードがあれば close・volume を上書き（volumeの後付け補完に対応）。
    records: [(code, date, close, volume), ...]
    戻り値: 挿入件数
    """
    conn.executemany(
        "INSERT OR REPLACE INTO price_history (code, date, close, volume) VALUES (?, ?, ?, ?)",
        records,
    )
    return len(records)


def bulk_insert_dividend_history(conn: sqlite3.Connection,
                                  records: list[tuple[str, str, float]]) -> int:
    """dividend_history に一括 INSERT OR IGNORE する。
    records: [(code, ex_date, amount), ...]
    """
    conn.executemany(
        "INSERT OR IGNORE INTO dividend_history (code, ex_date, amount) VALUES (?, ?, ?)",
        records,
    )
    return len(records)


def start_run(conn: sqlite3.Connection, mode: str, subset: str | None = None) -> int:
    """run_log に INSERT し、run_id を返す。"""
    cur = conn.execute(
        "INSERT INTO run_log (mode, subset, started_at) VALUES (?, ?, datetime('now'))",
        (mode, subset),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int,
               succeeded: int, failed: int, skipped: int,
               exit_code: int = 0) -> None:
    """run_log の finished_at・集計値を更新する。"""
    total = succeeded + failed + skipped
    conn.execute(
        "UPDATE run_log SET finished_at=datetime('now'), total=?, "
        "succeeded=?, failed=?, skipped=?, exit_code=? WHERE id=?",
        (total, succeeded, failed, skipped, exit_code, run_id),
    )
    conn.commit()


# ── raw_financials ───────────────────────────────────────────────

RAW_FINANCIALS_COLS = [
    "eps", "bps", "shares_outstanding", "roe", "operating_margins",
    "payout_ratio", "free_cashflow", "operating_cashflow", "capital_expenditures",
    "dividend_rate", "market_cap", "beta",
    "total_assets", "stockholders_equity", "current_assets", "total_liabilities",
    "long_term_debt", "short_term_debt", "retained_earnings",
    "diluted_eps_latest", "total_revenue_latest",
    "diluted_eps_5y_ago", "total_revenue_5y_ago",
    "diluted_eps_periods", "total_revenue_periods",
    "fetched_at",
]


def upsert_raw_financials(conn: sqlite3.Connection, code: str, data: dict) -> None:
    """raw_financials を UPSERT する。"""
    cols = [c for c in RAW_FINANCIALS_COLS if c in data]
    vals = [data[c] for c in cols]
    cols_s = ", ".join(cols)
    plc = ", ".join("?" * len(cols))
    upd = ", ".join(f"{c}=excluded.{c}" for c in cols)
    conn.execute(
        f"INSERT INTO raw_financials (code, {cols_s}) VALUES (?, {plc}) "
        f"ON CONFLICT(code) DO UPDATE SET {upd}",
        [code, *vals],
    )


def get_raw_financials(conn: sqlite3.Connection,
                       codes: list[str] | None = None) -> pd.DataFrame:
    """raw_financials を DataFrame で返す。"""
    sql = "SELECT * FROM raw_financials"
    params: list = []
    if codes:
        sql += f" WHERE code IN ({','.join('?'*len(codes))})"
        params = codes
    rows = conn.execute(sql, params).fetchall()
    cols = ["code"] + RAW_FINANCIALS_COLS
    return pd.DataFrame(rows, columns=cols)


# ── computed_metrics ─────────────────────────────────────────────

COMPUTED_METRICS_COLS = [
    "per", "pbr", "current_market_cap", "div_yield", "mix_coefficient", "net_cash_per",
    "equity_ratio", "debt_to_equity", "eps_growth_5y", "revenue_growth_5y_cagr",
    "roic_minus_wacc", "fcf_payout_coverage", "retained_earnings_div_ratio",
    "annual_div", "consecutive_no_cut_years", "consecutive_dividend_growth_years",
    "dividend_growth_5y_cagr", "dividend_growth_10y_cagr",
    "dividend_reliability", "dividend_cut_count_20y",
    "roe", "operating_margin", "payout_ratio",
    "ret_3m", "ret_12m", "rel_ret_3m", "rel_ret_12m", "hi52_ratio",
    "price_computed_at", "fin_computed_at", "div_computed_at",
]


def upsert_computed_metrics(conn: sqlite3.Connection, code: str, data: dict) -> None:
    """computed_metrics を UPSERT する。"""
    cols = [c for c in COMPUTED_METRICS_COLS if c in data]
    vals = [data[c] for c in cols]
    cols_s = ", ".join(cols)
    plc = ", ".join("?" * len(cols))
    upd = ", ".join(f"{c}=excluded.{c}" for c in cols)
    conn.execute(
        f"INSERT INTO computed_metrics (code, {cols_s}) VALUES (?, {plc}) "
        f"ON CONFLICT(code) DO UPDATE SET {upd}",
        [code, *vals],
    )


def get_computed_metrics(conn: sqlite3.Connection,
                         codes: list[str] | None = None) -> pd.DataFrame:
    """computed_metrics を DataFrame で返す。"""
    all_cols = ["code"] + COMPUTED_METRICS_COLS
    cols_s = ", ".join(all_cols)
    sql = f"SELECT {cols_s} FROM computed_metrics"
    params: list = []
    if codes:
        sql += f" WHERE code IN ({','.join('?'*len(codes))})"
        params = codes
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame(rows, columns=all_cols)


# ── dividend_scores ──────────────────────────────────────────────

DIVIDEND_SCORE_COLS = [
    "rule_version_id", "total_score",
    "s_consecutive_no_cut_years", "s_consecutive_dividend_growth_years",
    "s_dividend_reliability", "s_dividend_growth_10y_cagr",
    "s_payout_ratio", "s_fcf_payout_coverage",
    "s_eps_growth_5y", "s_revenue_growth_5y_cagr",
    "s_roe", "s_operating_margin",
    "s_div_yield", "s_mix_coefficient", "s_net_cash_per",
    "s_roic_minus_wacc", "s_retained_earnings_div_ratio",
]


def upsert_dividend_score(conn: sqlite3.Connection, code: str, scored_at: str,
                          rule_version_id: int, total_score: float,
                          breakdown: dict) -> None:
    """dividend_scores を UPSERT する。"""
    data = {
        "rule_version_id": rule_version_id,
        "total_score": total_score,
    }
    for k, v in breakdown.items():
        col = f"s_{k}" if not k.startswith("s_") else k
        if col in DIVIDEND_SCORE_COLS:
            data[col] = v
    cols = [c for c in DIVIDEND_SCORE_COLS if c in data]
    vals = [data[c] for c in cols]
    cols_s = ", ".join(cols)
    plc = ", ".join("?" * len(cols))
    upd = ", ".join(f"{c}=excluded.{c}" for c in cols)
    conn.execute(
        f"INSERT INTO dividend_scores (code, scored_at, {cols_s}) VALUES (?, ?, {plc}) "
        f"ON CONFLICT(code, scored_at) DO UPDATE SET {upd}",
        [code, scored_at, *vals],
    )


def get_dividend_scores(conn: sqlite3.Connection, top_n: int = 30,
                        filters: dict | None = None) -> list[dict]:
    """dividend_scores の最新スコアを取得する。"""
    sql = (
        "SELECT ds.*, st.name, st.market, st.sector "
        "FROM dividend_scores ds "
        "JOIN stocks st ON ds.code = st.code "
        "WHERE ds.scored_at = (SELECT MAX(scored_at) FROM dividend_scores) "
    )
    params: list = []
    if filters:
        if filters.get("market"):
            sql += " AND st.market = ?"
            params.append(filters["market"])
        if filters.get("sector"):
            sql += " AND st.sector LIKE ?"
            params.append(f"%{filters['sector']}%")
    sql += " ORDER BY ds.total_score DESC"
    if top_n:
        sql += f" LIMIT {top_n}"
    rows = conn.execute(sql, params).fetchall()
    cols = [d[0] for d in conn.execute(
        "SELECT ds.*, st.name, st.market, st.sector "
        "FROM dividend_scores ds JOIN stocks st ON ds.code = st.code LIMIT 0"
    ).description] if rows else []
    return [dict(zip(cols, r)) for r in rows] if cols else []


# ── momentum_scores ──────────────────────────────────────────────

MOMENTUM_SCORE_COLS = [
    "total_score",
    "s_rel_ret_3m", "s_rel_ret_12m", "s_hi52_ratio",
    "s_rev_growth", "s_eps_growth",
    "s_roe", "s_operating_margin", "s_vol_ratio",
]


def upsert_momentum_score(conn: sqlite3.Connection, code: str, scored_at: str,
                          total_score: float, breakdown: dict) -> None:
    """momentum_scores を UPSERT する。"""
    data = {"total_score": total_score}
    for k, v in breakdown.items():
        col = f"s_{k}" if not k.startswith("s_") else k
        if col in MOMENTUM_SCORE_COLS:
            data[col] = v
    cols = [c for c in MOMENTUM_SCORE_COLS if c in data]
    vals = [data[c] for c in cols]
    cols_s = ", ".join(cols)
    plc = ", ".join("?" * len(cols))
    upd = ", ".join(f"{c}=excluded.{c}" for c in cols)
    conn.execute(
        f"INSERT INTO momentum_scores (code, scored_at, {cols_s}) VALUES (?, ?, {plc}) "
        f"ON CONFLICT(code, scored_at) DO UPDATE SET {upd}",
        [code, scored_at, *vals],
    )


def get_momentum_scores(conn: sqlite3.Connection, top_n: int = 30,
                        filters: dict | None = None) -> list[dict]:
    """momentum_scores の最新スコアを取得する。"""
    sql = (
        "SELECT ms.*, st.name, st.market, st.sector "
        "FROM momentum_scores ms "
        "JOIN stocks st ON ms.code = st.code "
        "WHERE ms.scored_at = (SELECT MAX(scored_at) FROM momentum_scores) "
    )
    params: list = []
    if filters:
        if filters.get("market"):
            sql += " AND st.market = ?"
            params.append(filters["market"])
        if filters.get("sector"):
            sql += " AND st.sector LIKE ?"
            params.append(f"%{filters['sector']}%")
    sql += " ORDER BY ms.total_score DESC"
    if top_n:
        sql += f" LIMIT {top_n}"
    rows = conn.execute(sql, params).fetchall()
    cols = [d[0] for d in conn.execute(
        "SELECT ms.*, st.name, st.market, st.sector "
        "FROM momentum_scores ms JOIN stocks st ON ms.code = st.code LIMIT 0"
    ).description] if rows else []
    return [dict(zip(cols, r)) for r in rows] if cols else []
