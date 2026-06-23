"""売られすぎ指標（52週ドローダウン・騰落率）の単体テスト。

price_history のみ由来・point-in-time。確証主義（履歴不足は insufficient）も検証する。
"""
import sqlite3
from datetime import date, timedelta

from findex.derive.compute import compute_drawdown_metrics_for_code


def _mem_db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE price_history (code TEXT, date TEXT, close_adj REAL, "
        "volume INTEGER, source TEXT, PRIMARY KEY (code, date))"
    )
    return conn


def _seed_daily(conn, code, start_iso, prices):
    """start_iso から日次で prices を投入（休場は無視＝近傍探索の検証には日次で十分）。"""
    d = date.fromisoformat(start_iso)
    for p in prices:
        conn.execute("INSERT INTO price_history VALUES (?,?,?,?,?)", (code, d.isoformat(), p, 0, "test"))
        d += timedelta(days=1)


def test_no_price_returns_none():
    conn = _mem_db()
    assert compute_drawdown_metrics_for_code(conn, "9999") is None


def test_drawdown_from_52w_high():
    conn = _mem_db()
    # 400日ぶん: 高値1000→現値700（30%下落）を構成。
    end = date.today()
    start = end - timedelta(days=399)
    prices = []
    d = start
    while d <= end:
        # 高値は中盤に1000、末尾は700
        days_from_start = (d - start).days
        prices.append(1000.0 if days_from_start == 200 else (700.0 if d == end else 800.0))
        d += timedelta(days=1)
    _seed_daily(conn, "1234", start.isoformat(), prices)
    out = compute_drawdown_metrics_for_code(conn, "1234")
    assert out["_status"]["drawdown_from_high"] == "ok"
    assert out["price_high_52w"] == 1000.0
    assert abs(out["drawdown_from_high"] - 0.30) < 1e-6   # (1000-700)/1000


def test_at_high_drawdown_is_zero():
    conn = _mem_db()
    end = date.today()
    start = end - timedelta(days=399)
    # 単調増加＝現値が高値そのもの → ドローダウン0（売られすぎでない）
    prices = [500.0 + i for i in range((end - start).days + 1)]
    _seed_daily(conn, "1234", start.isoformat(), prices)
    out = compute_drawdown_metrics_for_code(conn, "1234")
    assert out["drawdown_from_high"] == 0.0


def test_short_history_is_insufficient():
    conn = _mem_db()
    # 直近60日しか履歴がない（新規上場直後相当）→「52週高値」と称さない。
    end = date.today()
    start = end - timedelta(days=60)
    _seed_daily(conn, "1234", start.isoformat(), [1000.0] * 61)
    out = compute_drawdown_metrics_for_code(conn, "1234")
    assert out["_status"]["drawdown_from_high"] == "insufficient"
    assert out["drawdown_from_high"] is None
    assert out["_status"]["price_return_1y"] == "insufficient"


def test_trailing_returns_sign():
    conn = _mem_db()
    end = date.today()
    start = end - timedelta(days=399)
    # 1年前=1000、6ヶ月前=900、現在=800 → 1年-20%, 6ヶ月-11.1%
    prices = []
    d = start
    while d <= end:
        delta = (end - d).days
        if delta >= 365:
            prices.append(1000.0)
        elif delta >= 182:
            prices.append(900.0)
        else:
            prices.append(800.0)
        d += timedelta(days=1)
    _seed_daily(conn, "1234", start.isoformat(), prices)
    out = compute_drawdown_metrics_for_code(conn, "1234")
    assert out["_status"]["price_return_1y"] == "ok"
    assert abs(out["price_return_1y"] - (-0.20)) < 1e-6
    assert out["price_return_6m"] < 0
