"""バックテスト前方アウトカムの減配検出（D8）。スパイク/分割アーティファクト/実減配の弁別。"""
from findex.backtest.outcomes import _forward_cut


def test_no_cut_monotonic():
    dps = {2018: 10, 2019: 11, 2020: 12, 2021: 13}
    assert _forward_cut(dps, 2018, 2021) == 0


def test_sustained_cut():
    # 11→5 で据え置き（復帰しない）＝真の減配
    dps = {2018: 10, 2019: 11, 2020: 5, 2021: 5}
    assert _forward_cut(dps, 2018, 2021) == 1


def test_special_dividend_spike_at_window_start():
    # 花王型: window先頭が特配スパイク(93)。2年文脈(58)で復帰扱い＝減配でない
    dps = {2010: 58, 2011: 58, 2012: 93, 2013: 64, 2014: 70, 2015: 80, 2016: 94}
    assert _forward_cut(dps, 2012, 2016) == 0


def test_split_artifact_excluded():
    # 神戸物産型: 単年で前年の17%まで急落＋翌年に前年水準超へ復帰＝分割単位不整合
    dps = {2006: 1.875, 2007: 0.9375, 2009: 0.15625, 2010: 1.25, 2011: 1.40625}
    assert _forward_cut(dps, 2008, 2013) == 0
    # 沖縄セルラー型: ÷2 の急落＋復帰
    dps2 = {2006: 11.25, 2007: 15.0, 2008: 17.5, 2010: 9.375, 2011: 19.0, 2012: 19.25}
    assert _forward_cut(dps2, 2008, 2013) == 0


def test_real_modest_cut_kept_even_if_later_recovers():
    # JT型: 154→140(91%・実減配)。後で188に増配しても閾値(55%)超なので真の減配として残す
    dps = {2018: 150, 2019: 154, 2020: 154, 2021: 140, 2022: 188}
    assert _forward_cut(dps, 2019, 2022) == 1


def test_insufficient_when_no_forward_point():
    assert _forward_cut({2018: 10}, 2018, 2021) is None
