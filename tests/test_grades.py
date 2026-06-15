"""claim別グレード＋恒等式チェックの純関数テスト（Phase3-e）。"""
from findex.derive.compute import _GRADE_CLAIMS, _grade_claim, _identity_ok


def test_grade_a_all_ok():
    # core全ok＋extra全ok → A
    st = {"per": "ok", "pbr": "ok", "div_yield": "ok", "mix_coefficient": "ok", "net_cash_per": "ok"}
    c = _GRADE_CLAIMS["grade_valuation"]
    assert _grade_claim(st, c["core"], c["extra"]) == "A"


def test_grade_b_extra_gap():
    # core全okだがextraに穴（censored/insufficient/missing）→ B
    st = {"per": "ok", "pbr": "ok", "div_yield": "missing", "mix_coefficient": "ok", "net_cash_per": "ok"}
    c = _GRADE_CLAIMS["grade_valuation"]
    assert _grade_claim(st, c["core"], c["extra"]) == "B"


def test_grade_b_censored_streak():
    # 配当系: reliability ok だが連続増配が打ち切り(N+)→ B（採用可・注記付き）
    st = {"dividend_reliability": "ok", "consecutive_dividend_growth_years": "censored",
          "yield_on_cost_5y": "ok", "dividend_quality": "ok"}
    c = _GRADE_CLAIMS["grade_dividend"]
    assert _grade_claim(st, c["core"], c["extra"]) == "B"


def test_grade_c_core_insufficient():
    # core に insufficient 混在＝評価不能 → C（missing でなく insufficient でも C）
    st = {"roic_minus_wacc": "insufficient", "fcf_payout_coverage": "insufficient", "doe": "ok"}
    c = _GRADE_CLAIMS["grade_capital"]
    assert _grade_claim(st, c["core"], c["extra"]) == "C"


def test_grade_c_core_partial_missing():
    # core 一部 ok・一部 missing（銀行の営業益率欠落型）→ C
    st = {"equity_ratio": "ok", "roe": "ok", "operating_margin": "missing"}
    c = _GRADE_CLAIMS["grade_health"]
    assert _grade_claim(st, c["core"], c["extra"]) == "C"


def test_grade_d_core_all_absent():
    # core が一つも算出されず（無配の配当系＝status自体が無い）→ D
    c = _GRADE_CLAIMS["grade_dividend"]
    assert _grade_claim({}, c["core"], c["extra"]) == "D"
    # capital core が両方 missing → D（insufficient とは区別）
    c2 = _GRADE_CLAIMS["grade_capital"]
    assert _grade_claim({"roic_minus_wacc": "missing", "fcf_payout_coverage": "missing"},
                        c2["core"], c2["extra"]) == "D"


def test_identity_ok_holds():
    # DOE ≈ ROE×payout（誤差<15%）→ 1
    st = {"doe": "ok", "roe": "ok", "payout_ratio": "ok"}
    assert _identity_ok(0.0638, 0.109693, 0.591625, st) == 1


def test_identity_mismatch():
    # 自己株式多で per-share と総額が乖離（キヤノン型・誤差32%）→ 0
    st = {"doe": "ok", "roe": "ok", "payout_ratio": "ok"}
    assert _identity_ok(0.0565, 0.085739, 0.4467, st) == 0


def test_identity_na_when_not_all_ok():
    # いずれかが ok でない（赤字でpayout insufficient等）→ 判定不能 NULL
    st = {"doe": "ok", "roe": "ok", "payout_ratio": "insufficient"}
    assert _identity_ok(0.05, 0.1, None, st) is None
    # 値が None → NULL
    st2 = {"doe": "ok", "roe": "ok", "payout_ratio": "ok"}
    assert _identity_ok(None, 0.1, 0.5, st2) is None
