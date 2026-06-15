"""EDINET会計基準別ラベル辞書の抽出ロジック（純粋関数）の回帰テスト。

実データスパイク（花王IFRS/イオンJGAAP/キヤノンUS）で確認した挙動を固定する:
- 連結ctx（サフィックス無し）のみ採る
- JGAAP有利子負債は構成要素を合算(mode:sum)
- IFRSのinvestment_securities/current_assetsは構造的にinsufficient
- US GAAPは全項目censored（連結が構造化XBRLに出ない）
"""
from findex.fetch.edinet import detect_standard, extract_fields, extract_summary


def _rec(eid, ctx, val):
    return {"要素ID": eid, "コンテキストID": ctx, "値": val}


def test_detect_standard():
    assert detect_standard([_rec("jpdei_cor:AccountingStandardsDEI", "FilingDateInstant", "IFRS")]) == "ifrs"
    assert detect_standard([_rec("jpdei_cor:AccountingStandardsDEI", "x", "Japan GAAP")]) == "jgaap"
    assert detect_standard([_rec("jpdei_cor:AccountingStandardsDEI", "x", "US GAAP")]) == "us"
    assert detect_standard([_rec("foo", "x", "1")]) is None


def test_jgaap_sum_and_consolidated_only():
    recs = [
        _rec("jppfs_cor:RetainedEarnings", "CurrentYearInstant", "100"),
        # 非連結は無視されること
        _rec("jppfs_cor:ShortTermLoansPayable", "CurrentYearInstant_NonConsolidatedMember", "999"),
        _rec("jppfs_cor:ShortTermLoansPayable", "CurrentYearInstant", "30"),
        _rec("jppfs_cor:BondsPayable", "CurrentYearInstant", "20"),
        _rec("jppfs_cor:InterestExpensesNOE", "CurrentYearDuration", "5"),
        _rec("jppfs_cor:CurrentAssets", "CurrentYearInstant", "200"),
        _rec("jppfs_cor:Liabilities", "CurrentYearInstant", "150"),
    ]
    vals, status = extract_fields(recs, "jgaap")
    assert vals["retained_earnings"] == 100
    assert vals["interest_bearing_debt"] == 50  # 30+20（非連結999は除外）
    assert status["interest_bearing_debt"] == "ok"
    assert vals["interest_expense"] == 5
    assert status["investment_securities"] == "missing"  # タグ無し


def test_ifrs_structural_insufficient_and_abs_capex():
    recs = [
        _rec("jpigp_cor:RetainedEarningsIFRS", "CurrentYearInstant", "1000"),
        _rec("jpigp_cor:PurchaseOfPropertyPlantAndEquipmentInvCFIFRS", "CurrentYearDuration", "-61214"),
    ]
    vals, status = extract_fields(recs, "ifrs")
    assert vals["retained_earnings"] == 1000
    assert vals["capex"] == 61214  # 絶対値
    assert status["investment_securities"] == "insufficient"  # IFRSは単独タグ無し
    assert status["current_assets"] == "insufficient"


def test_us_all_censored():
    recs = [_rec("jppfs_cor:RetainedEarnings", "CurrentYearInstant", "100")]
    vals, status = extract_fields(recs, "us")
    assert all(s == "censored" for s in status.values())
    assert all(v is None for v in vals.values())


def test_summary_5y_ifrs_consolidated_only():
    # CurrentYear=2024 として Prior4..Current の EPS/revenue を遡る。非連結は除外。
    eps = "jpcrp_cor:BasicEarningsLossPerShareIFRSSummaryOfBusinessResults"
    rev = "jpcrp_cor:RevenueIFRSSummaryOfBusinessResults"
    recs = [
        _rec(eps, "CurrentYearDuration", "260.30"),
        _rec(eps, "Prior1YearDuration", "231.94"),
        _rec(eps, "Prior4YearDuration", "230.59"),
        _rec(eps, "Prior2YearDuration_NonConsolidatedMember", "9999"),  # 非連結→除外
        _rec(rev, "CurrentYearDuration", "1688633"),
        _rec(rev, "Prior4YearInstant", "0"),  # ctx不一致(revenueはduration)→無視
    ]
    out = extract_summary(recs, "ifrs", 2024)
    assert out[2024]["eps"] == 260.30
    assert out[2023]["eps"] == 231.94
    assert out[2020]["eps"] == 230.59
    assert 2022 not in out  # 非連結のみの年は採らない
    assert out[2024]["revenue"] == 1688633
    assert "revenue" not in out[2020]  # instantはrevenue(duration)に不一致


def test_summary_nonconsolidated_fallback():
    # 連結が一切無い単体決算のみの会社（2391型）→ 単体にフォールバック
    eps = "jpcrp_cor:BasicEarningsLossPerShareSummaryOfBusinessResults"
    recs = [
        _rec(eps, "CurrentYearDuration_NonConsolidatedMember", "60.44"),
        _rec(eps, "Prior4YearDuration_NonConsolidatedMember", "75.12"),
    ]
    out = extract_summary(recs, "jgaap", 2025)
    assert out[2025]["eps"] == 60.44
    assert out[2021]["eps"] == 75.12


def test_summary_prefers_consolidated_over_nonconsolidated():
    # 連結が在れば単体は採らない（混在企業で単体に落ちない）
    eps = "jpcrp_cor:BasicEarningsLossPerShareSummaryOfBusinessResults"
    recs = [
        _rec(eps, "CurrentYearDuration", "100.0"),
        _rec(eps, "CurrentYearDuration_NonConsolidatedMember", "5.0"),
    ]
    out = extract_summary(recs, "jgaap", 2025)
    assert out[2025]["eps"] == 100.0


def test_summary_us_and_unknown_empty():
    recs = [_rec("jpcrp_cor:NetSalesSummaryOfBusinessResults", "CurrentYearDuration", "100")]
    assert extract_summary(recs, "us", 2024) == {}
    assert extract_summary(recs, None, 2024) == {}
    assert extract_summary(recs, "jgaap", None) == {}
