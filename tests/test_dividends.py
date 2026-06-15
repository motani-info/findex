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
