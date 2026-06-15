"""配当由来指標の純関数テスト（減配検出の頑健化・増配の質）。"""
from findex.derive.compute import _classify_quality, count_dividend_cuts


def test_cut_ignores_spike_revert():
    # 花王型: 58→93(15ヶ月変則)→64 はスパイク復帰で減配でない（64>58）
    assert count_dividend_cuts([55, 56, 58, 93, 64, 70]) == 0


def test_cut_counts_real_sustained_cut():
    # 10→8 で水準が下がり継続 → 減配1回
    assert count_dividend_cuts([10, 10, 8, 8]) == 1


def test_cut_counts_drop_below_baseline():
    # 10→12→8: 8は2年前(10)も下回る → 真の減配
    assert count_dividend_cuts([10, 12, 8]) == 1


def test_cut_multiple_declines():
    # 継続的下落（日産型）
    assert count_dividend_cuts([40, 30, 20, 10]) == 3


def test_quality_sound_payout_cyclical():
    assert _classify_quality(150, 100, 1.6) == "sound"          # EPS倍率1.5
    assert _classify_quality(120, 100, 1.6) == "payout_driven"  # EPS伸び弱→性向拡大
    assert _classify_quality(90, 100, 1.6) == "cyclical"        # EPS減
    assert _classify_quality(-5, 100, 1.6) == "cyclical"        # 赤字
    assert _classify_quality(100, None, 1.6) == "cyclical"      # 算出不能
