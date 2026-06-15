"""評価層v4の純関数テスト（生スコア式・status_based動的分母・質ゲート・業種相対・入れ替え）。"""
from findex.score.engine import _pct_rank, _raw_score, score_one, select_rules


def _r(field, direction="high", threshold=10.0, weight=1.0, **kw):
    return {"field": field, "direction": direction, "threshold": threshold,
            "weight": weight, "max_score": 10, "available": True, **kw}


def test_raw_score_high_low():
    assert _raw_score(10.0, _r("x", "high", 10.0)) == 10.0   # 閾値で満点
    assert _raw_score(5.0, _r("x", "high", 10.0)) == 5.0     # 半分
    assert _raw_score(10.0, _r("x", "low", 10.0)) == 10.0    # low: 閾値で満点
    assert _raw_score(20.0, _r("x", "low", 10.0)) == 5.0     # low: 2倍で半分


def test_raw_score_caps_and_negative():
    # upper_cap: cap超でペナルティ下降（capで満点、2×capで0）
    rule = _r("y", "high", 0.03, upper_cap=0.07)
    assert _raw_score(0.07, rule) == 10.0
    assert _raw_score(0.14, rule) == 0.0
    # penalty_cap: 上限以上で0点
    assert _raw_score(60.0, _r("z", "low", 10.0, penalty_cap=60.0)) == 0.0
    # direction=low で値≤0（ネットキャッシュPER負）＝満点
    assert _raw_score(-5.0, _r("z", "low", 10.0)) == 10.0


def test_status_based_denominator():
    # ok/zero_legit のみ分子・分母。missing/insufficient/censored は両方除外
    rules = [_r("a", weight=2.0), _r("b", weight=1.0), _r("c", weight=1.0), _r("d", weight=1.0)]
    metrics = {"a": 10.0, "b": 0.0, "c": 5.0, "d": 5.0}
    status = {"a": "ok", "b": "zero_legit", "c": "missing", "d": "censored"}
    sj = score_one(metrics, status, rules, sector_margins=[], min_sector_n=4)
    # 分母= a(2.0)+b(1.0)=3.0×10=30。分子= 10×2.0 + 0×1.0 = 20 → 66.67
    assert sj["n_scored"] == 2
    assert sj["den_weight"] == 30.0
    assert sj["total"] == round(20 / 30 * 100, 2)
    assert set(sj["excluded"]) == {"c", "d"}


def test_quality_gate_multiplier():
    rule = _r("yield_on_cost_5y", "high", 0.06, weight=1.2, quality_gate=True)
    base = {"yield_on_cost_5y": 0.06, "dividend_quality": "sound"}
    st = {"yield_on_cost_5y": "ok"}
    assert score_one(base, st, [rule], sector_margins=[], min_sector_n=4)["raw"]["yield_on_cost_5y"] == 10.0
    base["dividend_quality"] = "cyclical"  # ×0.3
    assert score_one(base, st, [rule], sector_margins=[], min_sector_n=4)["raw"]["yield_on_cost_5y"] == 3.0
    base["dividend_quality"] = None  # 質不明→中立×1.0
    assert score_one(base, st, [rule], sector_margins=[], min_sector_n=4)["raw"]["yield_on_cost_5y"] == 10.0


def test_sector_relative_vs_absolute_fallback():
    rule = _r("operating_margin", "high", 0.20, scoring="sector_relative")
    st = {"operating_margin": "ok"}
    # 母数充足（min_sector_n=4）→ パーセンタイル。0.10 は [0.02,0.05,0.10,0.20] 中で下から3番目
    sj = score_one({"operating_margin": 0.10}, st, [rule],
                   sector_margins=[0.02, 0.05, 0.10, 0.20], min_sector_n=4)
    assert sj["raw"]["operating_margin"] == _pct_rank(0.10, [0.02, 0.05, 0.10, 0.20], 10)
    # 母数不足→絶対閾値フォールバック（0.10/0.20×10=5.0）
    sj2 = score_one({"operating_margin": 0.10}, st, [rule],
                    sector_margins=[0.10], min_sector_n=4)
    assert sj2["raw"]["operating_margin"] == 5.0


def test_select_rules_financial_and_large_cap():
    rules = [
        _r("equity_ratio"), _r("roic_minus_wacc"), _r("net_cash_per", "low"),
        _r("retained_earnings_div_ratio", replaces="roic_minus_wacc", applies_to=["large_cap", "financial"]),
        _r("mix_coefficient", "low", replaces="net_cash_per", applies_to=["large_cap", "financial"]),
    ]
    fin = select_rules(rules, market_cap=5e11, sector="その他金融業",
                       large_cap_threshold=1e12, financial_sectors=["その他金融業"])
    fields = {r["field"] for r in fin}
    assert "equity_ratio" not in fields           # 金融は自己資本比率除外
    assert "retained_earnings_div_ratio" in fields  # roic を置換
    assert "roic_minus_wacc" not in fields
    assert "mix_coefficient" in fields and "net_cash_per" not in fields
    # 非金融・小型→基本指標のまま
    base = select_rules(rules, market_cap=1e10, sector="化学",
                        large_cap_threshold=1e12, financial_sectors=["その他金融業"])
    bf = {r["field"] for r in base}
    assert "equity_ratio" in bf and "roic_minus_wacc" in bf and "net_cash_per" in bf
