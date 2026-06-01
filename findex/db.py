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
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = WAL")
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
                conn.execute(stmt)
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
