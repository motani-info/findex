"""SQLite 接続・初期化・バックアップ。

WAL + busy_timeout で更新ジョブと読み取りの同時アクセスに耐える（地雷9）。
破壊的操作の前に backup_db() を呼ぶ。
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .. import config

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SCHEMA_VERSION = 2  # D3 全面再生成（result_overrides汎用化・claim別グレード・backtest・universe）


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    config.ensure_dirs()
    path = db_path or config.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """スキーマを適用（IF NOT EXISTS なので冪等）。"""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate_add_columns(conn)            # 既存DBへの冪等な列追加（CREATE IF NOT EXISTSでは増えない）
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()


def _migrate_add_columns(conn) -> None:
    """既存テーブルに後から増えた列を冪等に追加する（新規DBはスキーマで作成済）。"""
    wanted = {
        "financial_snapshots": [("disclosed_date", "TEXT")],   # 分割補正の基準日（doc11是正）
        # 売られすぎ指標（price_history 由来・新規取得なし）。後追加のため既存DBへ冪等に列追加。
        "computed_metrics": [
            ("price_high_52w", "REAL"), ("drawdown_from_high", "REAL"),
            ("price_return_1y", "REAL"), ("price_return_6m", "REAL"),
        ],
    }
    for table, cols in wanted.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def backup_db(db_path: Path | None = None) -> Path | None:
    """findex.db.bak-YYYYMMDD を作る。存在しなければ何もしない。"""
    path = db_path or config.DB_PATH
    if not path.exists():
        return None
    dest = path.with_name(f"{path.name}.bak-{date.today():%Y%m%d}")
    shutil.copy2(path, dest)
    return dest
