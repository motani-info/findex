"""洗替の検収（F5・findex verify）の集計ロジックのテスト。

in-memory sqlite に最小テーブルを組み、golden整合・seam穴・review率を検証する。
"""
import json
import sqlite3

import pytest

from findex.verify import run_verify


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(
        """
        CREATE TABLE stocks(code TEXT PRIMARY KEY, listing_date TEXT);
        CREATE TABLE price_history(code TEXT, date TEXT);
        CREATE TABLE financial_snapshots(code TEXT, fiscal_year INT);
        CREATE TABLE dividend_annual(code TEXT, fiscal_year INT, dps REAL, confidence TEXT);
        CREATE TABLE computed_metrics(code TEXT, consecutive_dividend_growth_years INT, status_json TEXT);
        CREATE TABLE result_overrides(code TEXT, field TEXT, value INT);
        """
    )
    # A: golden 健全（導出36 >= 公表36）・連続配当に歯抜け無し
    # B: golden 異常（導出10 < 公表20）＝赤信号
    # C: FY2000 seam 穴（1999,2001…2000欠落）＋ review 行あり
    c.execute("INSERT INTO stocks VALUES('A','1949-05-01'),('B',NULL),('C','1960-01-01')")
    c.executemany("INSERT INTO price_history VALUES(?,?)", [("A", "2020-01-01"), ("B", "2020-01-01")])
    c.execute("INSERT INTO financial_snapshots VALUES('A',2024)")
    c.executemany(
        "INSERT INTO dividend_annual VALUES(?,?,?,?)",
        [("A", 2022, 10, None), ("A", 2023, 11, None), ("A", 2024, 12, None),
         ("C", 1999, 5, None), ("C", 2001, 6, None), ("C", 2002, 7, None),
         ("C", 2003, 99, "review")],  # review は seam 判定から除外される
    )
    c.execute(
        "INSERT INTO computed_metrics VALUES('A',36,?),('B',10,?),('C',2,?)",
        (json.dumps({"roe": "ok", "per": "insufficient"}),
         json.dumps({"roe": "ok"}),
         json.dumps({"roe": "censored"})),
    )
    c.execute("INSERT INTO result_overrides VALUES('A','consecutive_dividend_growth_years',36)")
    c.execute("INSERT INTO result_overrides VALUES('B','consecutive_dividend_growth_years',20)")
    c.commit()
    return c


def test_coverage_counts(conn):
    rep = run_verify(conn)
    cov = rep["coverage"]
    assert cov["total"] == 3
    assert cov["listing_date"] == 2          # A,C（B は NULL）
    assert cov["dividend_annual"] == 2        # A,C
    assert cov["financial_snapshots"] == 1    # A のみ


def test_golden_match_and_mismatch(conn):
    rep = run_verify(conn)
    g = rep["golden"]
    assert g["checked"] == 2
    assert g["matched"] == 1                  # A（36>=36）
    assert rep["golden_ok"] is False          # B が赤信号
    codes = {mm["code"] for mm in g["mismatches"]}
    assert codes == {"B"}                      # 導出10 < 公表20


def test_seam_excludes_review(conn):
    rep = run_verify(conn)
    sm = rep["seam"]
    # C は 1999→2001 で FY2000 欠落（review の 2003 は系列から除外）
    assert sm["codes_with_gaps"] == 1
    assert sm["fy2000_seam"] == 1
    assert (2000, 1) in sm["top_gap_years"]


def test_review_rate(conn):
    rep = run_verify(conn)
    assert rep["review"]["codes_with_review"] == 1   # C
    assert rep["review"]["review_rows"] == 1
