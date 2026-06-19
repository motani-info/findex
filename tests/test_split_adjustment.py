"""株式分割補正の回帰テスト（doc11）。"""
import sqlite3

from findex.derive.compute import _split_adjustment_factor


def _mem_db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE stock_splits (code TEXT, date TEXT, ratio REAL, "
        "source TEXT DEFAULT 'yfinance', collected_at TEXT, PRIMARY KEY (code, date))"
    )
    return conn


def test_no_split_returns_1():
    conn = _mem_db()
    assert _split_adjustment_factor(conn, "9999", "2025-03-31") == 1.0


def test_single_split_after_as_of():
    conn = _mem_db()
    conn.execute("INSERT INTO stock_splits VALUES ('2146','2025-12-29',15.0,'yfinance','now')")
    assert _split_adjustment_factor(conn, "2146", "2025-03-31") == 15.0


def test_split_before_as_of_ignored():
    conn = _mem_db()
    conn.execute("INSERT INTO stock_splits VALUES ('2146','2013-06-26',200.0,'yfinance','now')")
    # as_of=2025-03-31 → 2013年の分割は対象外
    assert _split_adjustment_factor(conn, "2146", "2025-03-31") == 1.0


def test_multiple_splits_cumulative():
    conn = _mem_db()
    conn.execute("INSERT INTO stock_splits VALUES ('8227','2024-02-19',2.0,'yfinance','now')")
    conn.execute("INSERT INTO stock_splits VALUES ('8227','2026-02-19',3.0,'yfinance','now')")
    # as_of=2024-03-31 → 2024-02分割は対象外（before as_of）、2026-02分割のみ
    assert _split_adjustment_factor(conn, "8227", "2024-03-31") == 3.0
    # as_of=2023-12-31 → 両方とも対象
    assert _split_adjustment_factor(conn, "8227", "2023-12-31") == 6.0
