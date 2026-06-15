"""配当の会計年度集計（地雷2）の回帰テスト。"""
from findex.fetch.dividends import fiscal_year_of


def test_fiscal_year_march_end():
    # 3月期: 中間9月・期末3月は同一FYに入る（期末年で命名）
    assert fiscal_year_of("2025-03-28", 3) == 2025
    assert fiscal_year_of("2024-09-30", 3) == 2025


def test_fiscal_year_dec_end():
    # 12月期: 中間6月・期末12月は同一FY
    assert fiscal_year_of("2025-12-29", 12) == 2025
    assert fiscal_year_of("2025-06-27", 12) == 2025


def test_fiscal_year_feb_end():
    # 2月期(イオン): 中間8月・期末2月は同一FY
    assert fiscal_year_of("2025-02-26", 2) == 2025
    assert fiscal_year_of("2024-08-28", 2) == 2025


def test_aggregate_keeps_complete_first_year():
    """花王型: 初年度が完全(2回)なら捨てない（地雷1の条件化・Fix B）。"""
    from findex.fetch.dividends import aggregate_events
    # 12月期。2000に2回(完全)、2001に2回 → FY2000を残す
    ev = [("2000-03-28", 10.0), ("2000-09-26", 12.0),
          ("2001-03-27", 12.0), ("2001-09-25", 13.0)]
    out = aggregate_events(ev, 12)
    assert out[2000] == 22.0
    assert out[2001] == 25.0


def test_aggregate_drops_partial_first_year():
    """初年度が部分的(1回<次年2回)なら捨てる。"""
    from findex.fetch.dividends import aggregate_events
    ev = [("2000-09-26", 12.0),  # 初年度1回のみ=部分的
          ("2001-03-27", 12.0), ("2001-09-25", 13.0)]
    out = aggregate_events(ev, 12)
    assert 2000 not in out
    assert out[2001] == 25.0
