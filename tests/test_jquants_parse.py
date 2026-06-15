"""J-Quants fins/summary パースの回帰テスト。

実データで踏んだバグを固定:
- EarnForecastRevision（予想・訂正開示）は CurPerType=FY でも Sales空→除外
- 同一年度に実績の財務諸表開示があればそれを採る
"""
from findex.fetch.jquants import parse_fy_records


def _fy(disc, end, doctype, sales, op="100"):
    return {"CurPerType": "FY", "DiscDate": disc, "CurFYEn": end,
            "DocType": doctype, "Sales": sales, "OP": op, "NP": "50", "EPS": "1.0"}


def test_excludes_forecast_revision():
    recs = [
        _fy("2025-04-04", "2025-02-28", "EarnForecastRevision", ""),       # 空・除外
        _fy("2025-04-11", "2025-02-28", "FYFinancialStatements_Consolidated_JP", "10134877000000"),
        _fy("2026-01-07", "2026-02-28", "EarnForecastRevision", ""),       # 進行年の予想・除外
    ]
    out = parse_fy_records(recs)
    assert [f.fiscal_year for f in out] == [2025]
    assert out[0].base["revenue"] == 10134877000000
    assert out[0].accounting_standard == "jgaap"


def test_standard_detection_ifrs():
    recs = [_fy("2025-08-05", "2025-06-30", "FYFinancialStatements_Consolidated_IFRS", "192633000000")]
    out = parse_fy_records(recs)
    assert out[0].accounting_standard == "ifrs"


def test_skips_quarterly_and_empty_sales():
    recs = [
        {"CurPerType": "2Q", "CurFYEn": "2025-02-28", "DocType": "2QFinancialStatements", "Sales": "5000"},
        _fy("2025-04-11", "2025-02-28", "FYFinancialStatements_Consolidated_JP", ""),  # 売上空・除外
    ]
    assert parse_fy_records(recs) == []
