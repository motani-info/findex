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


def test_authoritative_shares_overrides_reported_for_price_metrics():
    """share_count（権威ある現在発行済株数）があれば現在断面のmcap/PER/PBRはそれを真値に使う（T1是正・Option1）。"""
    from pathlib import Path

    from findex.db.database import connect
    from findex.derive.compute import compute_price_metrics_for_code

    conn = connect(":memory:")
    conn.executescript(Path("findex/db/schema.sql").read_text(encoding="utf-8"))
    # 報告株数10M・EPS100・BPS1000・価格500。権威株数=20M（報告の2倍＝期末直前分割で報告が分割前のままの型）。
    conn.execute("INSERT INTO stocks (code, name, accounting_standard, updated_at) VALUES ('9999','テスト','jgaap','now')")
    conn.execute("INSERT INTO price_history (code, date, close_adj, source) VALUES ('9999','2025-06-01',500.0,'yf')")
    conn.execute(
        "INSERT INTO financial_snapshots (code, fiscal_year, source, net_income, eps, bps, "
        "shares_outstanding, equity_attributable, as_of, disclosed_date, collected_at) "
        "VALUES ('9999', 2025, 'jquants', 1000000000, 100.0, 1000.0, 10000000, 10000000000, '2025-03-31', '2025-05-13', 'now')"
    )
    conn.commit()
    # 権威株数なし → 報告株数ベース: per=500/100=5, pbr=500/1000=0.5, mcap=500*10M=5e9
    base = compute_price_metrics_for_code(conn, "9999")
    assert base["per"] == 5.0 and base["pbr"] == 0.5 and base["current_market_cap"] == 5e9
    # 権威株数20M投入 → factor_eff=2: per=10, pbr=1.0, mcap=500*20M=1e10
    conn.execute("INSERT INTO share_count (code, shares, source, as_of, collected_at) VALUES ('9999',20000000,'yfinance','2025-06-01','now')")
    conn.commit()
    out = compute_price_metrics_for_code(conn, "9999")
    assert out["per"] == 10.0
    assert out["pbr"] == 1.0
    assert out["current_market_cap"] == 1e10


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

