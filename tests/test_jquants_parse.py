"""J-Quants fins/summary パースの回帰テスト。

実データで踏んだバグを固定:
- EarnForecastRevision（予想・訂正開示）は CurPerType=FY でも Sales空→除外
- 同一年度に実績の財務諸表開示があればそれを採る
"""
from findex.fetch.jquants import parse_fy_dividends, parse_fy_records


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


# ── doc13: J-Quans 確定年間配当 DivAnn の抽出（ghost利回り根治） ──────────────

def _div_fy(end, divann, doctype="FYFinancialStatements_NonConsolidated_JP", curper="FY"):
    return {"CurPerType": curper, "CurFYEn": end, "DocType": doctype, "DivAnn": divann}


def test_parse_fy_dividends_captures_zero_munhai():
    """サンウェルズ型: 確定無配(DivAnn=0.0)を含めて年度別に抽出（yfinanceが出せない0配当）。"""
    recs = [
        _div_fy("2024-03-31", "14.0"),   # 有配
        _div_fy("2025-03-31", "0.0"),    # 無配転落（確定）
    ]
    assert parse_fy_dividends(recs) == {2024: 14.0, 2025: 0.0}


def test_parse_fy_dividends_excludes_forecast_and_empty():
    """予想(四半期のFDivAnn)・未開示(空文字)は採らない＝確定実績のみ（捏造しない）。"""
    recs = [
        _div_fy("2026-03-31", "0.0", doctype="1QFinancialStatements_NonConsolidated_JP", curper="1Q"),  # 四半期=除外
        _div_fy("2025-03-31", ""),       # 未開示（空）=除外
        _div_fy("2024-03-31", "14.0"),   # 確定実績=採用
    ]
    assert parse_fy_dividends(recs) == {2024: 14.0}
