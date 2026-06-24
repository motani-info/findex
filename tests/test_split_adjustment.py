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


def test_duplicate_split_folded_within_window():
    """同一比率の近接split(yfinance二重計上=ex-date/効力日ズレ)は1回に畳む。
    2726型: 2:1が12日差で重複→factor 4でなく2（T1是正 2026-06-24）。"""
    conn = _mem_db()
    conn.execute("INSERT INTO stock_splits VALUES ('2726','2025-08-28',2.0,'yfinance','now')")
    conn.execute("INSERT INTO stock_splits VALUES ('2726','2025-09-09',2.0,'yfinance','now')")
    # disclosed=2025-04-08 以降の2件は重複→×2（×4でない）
    assert _split_adjustment_factor(conn, "2726", "2025-04-08") == 2.0


def test_genuine_consecutive_splits_not_folded():
    """実在の連続分割(6574=10:1×2・28日差)は畳まない＝×100を保つ（窓14日で弁別）。"""
    conn = _mem_db()
    conn.execute("INSERT INTO stock_splits VALUES ('6574','2025-07-31',10.0,'yfinance','now')")
    conn.execute("INSERT INTO stock_splits VALUES ('6574','2025-08-28',10.0,'yfinance','now')")
    assert _split_adjustment_factor(conn, "6574", "2025-05-15") == 100.0


def test_shares_factor_override_applies_only_to_shares():
    """報告株数の分割基準乖離を明示overrideで是正（T1残・8022/5535型）。
    _shares_factor は override を優先するが、_split_adjustment_factor(DPS系統)は不変。"""
    from findex.derive.compute import _SHARES_FACTOR_OVERRIDE, _shares_factor

    conn = _mem_db()
    # 8022: 開示前(期末3日前)の×3が報告株数に未反映＝日付ロジックは1.0だが override=3.0。
    conn.execute("INSERT INTO stock_splits VALUES ('8022','2025-03-28',3.0,'yfinance','now')")
    assert _split_adjustment_factor(conn, "8022", "2025-05-13") == 1.0  # DPS系統(開示前split無視)
    assert _shares_factor(conn, "8022", "2025-05-13") == 3.0            # shares系統=override
    # 5535: 報告株数に反映済みの×2を日付ロジックが過剰適用→override=1.0で打ち消す。
    conn.execute("INSERT INTO stock_splits VALUES ('5535','2025-05-29',2.0,'yfinance','now')")
    assert _split_adjustment_factor(conn, "5535", "2025-05-12") == 2.0  # DPS系統は×2のまま(正)
    assert _shares_factor(conn, "5535", "2025-05-12") == 1.0            # shares系統=override
    # overrideに無い銘柄は日付ロジックに委譲（回帰なし）。
    assert _shares_factor(conn, "9999", "2025-03-31") == 1.0
    assert set(_SHARES_FACTOR_OVERRIDE) == {"5535", "8022"}


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


def test_empty_yfinance_response_does_not_wipe_existing(monkeypatch):
    """一過性の空応答で既存分割を洗替（DELETE）しない回帰テスト（柱1のデータ喪失事故）。"""
    import pandas as pd

    from findex.fetch import splits as splits_mod

    conn = _mem_db()
    conn.execute("INSERT INTO stock_splits VALUES ('2146','2025-12-29',15.0,'yfinance','now')")
    conn.commit()
    fetcher = splits_mod.SplitsFetcher(conn)

    # yfinance が None / 空Series を返すケース＝「分割なし」と一過性空応答を区別できない。
    for empty in (None, pd.Series(dtype=float)):
        monkeypatch.setattr(
            splits_mod.yf, "Ticker",
            lambda *_a, _e=empty, **_k: type("T", (), {"splits": _e})(),
        )
        res = fetcher.fetch_one("2146")
        assert res == {"rows": 0, "skipped_empty": True}
        # 既存の分割行は温存される（消えていない）。
        n = conn.execute("SELECT COUNT(*) FROM stock_splits WHERE code='2146'").fetchone()[0]
        assert n == 1


def test_real_yfinance_response_replaces_existing(monkeypatch):
    """実データ応答時のみ code 単位で洗替されるか。"""
    import pandas as pd

    from findex.fetch import splits as splits_mod

    conn = _mem_db()
    conn.execute("INSERT INTO stock_splits VALUES ('2146','2099-01-01',999.0,'yfinance','old')")
    conn.commit()
    fetcher = splits_mod.SplitsFetcher(conn)

    s = pd.Series({pd.Timestamp("2025-12-29"): 15.0, pd.Timestamp("2013-06-26"): 200.0})
    monkeypatch.setattr(
        splits_mod.yf, "Ticker",
        lambda *_a, **_k: type("T", (), {"splits": s})(),
    )
    res = fetcher.fetch_one("2146")
    assert res["rows"] == 2
    # 古い誤記録(999.0)は洗替で消え、実データ2件に置き換わる。
    rows = conn.execute("SELECT ratio FROM stock_splits WHERE code='2146' ORDER BY ratio").fetchall()
    assert [r[0] for r in rows] == [15.0, 200.0]

