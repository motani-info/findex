"""配当アーティファクト隔離（flag_dividend_anomalies）の弁別テスト（Step1・取得層の根因是正）。

2種のアーティファクト（①部分集計＝半期欠落 ②単年誤値）を review 隔離しつつ、実減配
（日産型：払い回数正常の値減配・頻度を下げる持続的減配）は残すことを検証する。
"""
import sqlite3

from findex.fetch.dividends import flag_dividend_anomalies


def _db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE stocks(code TEXT PRIMARY KEY, fiscal_period_end_month INTEGER);
        CREATE TABLE dividend_annual(code TEXT, fiscal_year INTEGER, dps REAL,
            source TEXT, confidence TEXT, updated_at TEXT,
            PRIMARY KEY(code, fiscal_year));
        CREATE TABLE dividend_events(code TEXT, ex_date TEXT, amount REAL);
        """
    )
    return conn


def _seed(conn, code, annual, events, fm=12):
    """annual=[(fy,dps)], events=[(ex_date,amount)]。全て source=events/present で投入。"""
    conn.execute("INSERT INTO stocks VALUES (?,?)", (code, fm))
    for fy, dps in annual:
        conn.execute(
            "INSERT INTO dividend_annual VALUES (?,?,?,?,?,?)",
            (code, fy, dps, "events", "present", None),
        )
    for ex, amt in events:
        conn.execute("INSERT INTO dividend_events VALUES (?,?,?)", (code, ex, amt))
    conn.commit()


def _conf(conn, code, fy):
    return conn.execute(
        "SELECT confidence FROM dividend_annual WHERE code=? AND fiscal_year=?", (code, fy)
    ).fetchone()[0]


def test_extreme_value_anomaly_flagged():
    # 神戸物産型: 年1回払い・単年だけ前年の15%まで急落＋翌年復帰＝yfinance単年誤値
    conn = _db()
    _seed(conn, "X", [(2018, 10.0), (2019, 1.5), (2020, 11.0)],
          [("2018-06-01", 10.0), ("2019-06-01", 1.5), ("2020-06-01", 11.0)])
    flag_dividend_anomalies(conn, ["X"])
    assert _conf(conn, "X", 2019) == "review"
    assert _conf(conn, "X", 2018) == "present" and _conf(conn, "X", 2020) == "present"


def test_isolated_incomplete_aggregation_flagged():
    # 沖縄セルラー型: 半期払い(2回/年)で単年だけ1回しか取れず半額・翌年は2回に復帰
    conn = _db()
    _seed(conn, "Y", [(2018, 20.0), (2019, 10.0), (2020, 21.0)],
          [("2018-06-01", 10.0), ("2018-12-01", 10.0),
           ("2019-06-01", 10.0),  # 12月分が欠落＝1回のみ
           ("2020-06-01", 10.5), ("2020-12-01", 10.5)])
    flag_dividend_anomalies(conn, ["Y"])
    assert _conf(conn, "Y", 2019) == "review"


def test_real_value_cut_not_flagged():
    # 日産型(値): 年1回払い・前年の50%への減配（35%閾値より上）＝実減配→隔離しない
    conn = _db()
    _seed(conn, "Z", [(2018, 10.0), (2019, 5.0), (2020, 10.0)],
          [("2018-06-01", 10.0), ("2019-06-01", 5.0), ("2020-06-01", 10.0)])
    flag_dividend_anomalies(conn, ["Z"])
    assert _conf(conn, "Z", 2019) == "present"


def test_sustained_frequency_reduction_not_flagged():
    # 日産型(頻度): 通常2回/年が危機で複数年連続1回に＝持続的な実減配→隔離しない
    conn = _db()
    _seed(conn, "W", [(2017, 20.0), (2018, 10.0), (2019, 11.0), (2020, 22.0)],
          [("2017-06-01", 10.0), ("2017-12-01", 10.0),
           ("2018-06-01", 10.0),               # 1回（減）
           ("2019-06-01", 11.0),               # 翌年も1回＝持続的→アーティファクトでない
           ("2020-06-01", 11.0), ("2020-12-01", 11.0)])
    flag_dividend_anomalies(conn, ["W"])
    assert _conf(conn, "W", 2018) == "present"
