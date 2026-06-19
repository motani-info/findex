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


def test_payout_ratio_uses_split_adjusted_eps():
    """分割後基準のDPSと分割前基準のEPSの混在が補正されるか（doc11リグレッション）。"""
    from pathlib import Path

    from findex.db.database import connect
    from findex.derive.compute import compute_financial_metrics_for_code

    conn = connect(":memory:")
    conn.executescript(Path("findex/db/schema.sql").read_text(encoding="utf-8"))
    # 1:5分割銘柄。EPS=500(分割前)、DPS=40(分割後)。
    # 補正前: payout=40/500=8%（誤）／補正後: EPS=100、payout=40/100=40%（正）
    conn.execute(
        "INSERT INTO stocks (code, name, accounting_standard, updated_at) VALUES ('9999','テスト','jgaap','now')"
    )
    conn.execute(
        "INSERT INTO financial_snapshots (code, fiscal_year, source, net_income, eps, "
        "total_assets, equity_attributable, shares_outstanding, as_of, collected_at) "
        "VALUES ('9999', 2025, 'jquants', 5000000000, 500.0, 100000000000, 50000000000, 10000000, '2025-03-31', 'now')"
    )
    conn.execute(
        "INSERT INTO dividend_annual (code, fiscal_year, dps, source, confidence, updated_at) "
        "VALUES ('9999', 2026, 40.0, 'events', 'present', 'now')"
    )
    conn.execute(
        "INSERT INTO stock_splits VALUES ('9999','2025-12-29',5.0,'yfinance','now')"
    )
    conn.commit()
    out = compute_financial_metrics_for_code(conn, "9999")
    assert out["payout_ratio"] == round(40.0 / 100.0, 6)  # 0.4 = 40%

