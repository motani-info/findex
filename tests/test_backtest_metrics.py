"""バックテスト評価メトリクス（D8 §3）の相関ヘルパ。符号・同順位・サンプル不足の扱い。"""
from findex.backtest.metrics import MIN_PAIRS, spearman, tertile_spread


def test_spearman_perfect_monotonic():
    xs = list(range(10))
    ys = [v * 3 + 1 for v in xs]  # 単調増加
    r = spearman(xs, ys)
    assert r is not None and round(r, 6) == 1.0


def test_spearman_perfect_inverse():
    xs = list(range(10))
    ys = [-v for v in xs]
    r = spearman(xs, ys)
    assert r is not None and round(r, 6) == -1.0


def test_spearman_handles_ties():
    # 同順位（平均順位）を含んでも計算できる
    xs = [1, 1, 2, 3, 4, 5, 6, 7, 8]
    ys = [2, 2, 3, 4, 5, 6, 7, 8, 9]
    r = spearman(xs, ys)
    assert r is not None and r > 0.9


def test_spearman_constant_column_is_none():
    # 片方が定数（PIT時点でグレード全同一の状況）＝相関定義不能
    xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    ys = [5] * 10
    assert spearman(xs, ys) is None


def test_spearman_insufficient_sample_is_none():
    n = MIN_PAIRS - 1
    assert spearman(list(range(n)), list(range(n))) is None


def test_tertile_spread_sign():
    # 高スコアほど高アウトカム → 上位三分位−下位三分位は正
    scores = list(range(15))
    outcomes = list(range(15))
    spread, n = tertile_spread(scores, outcomes)
    assert n == 15 and spread is not None and spread > 0


def test_tertile_spread_insufficient():
    spread, n = tertile_spread([1, 2, 3], [1, 2, 3])
    assert spread is None and n == 3
