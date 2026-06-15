"""ストリーク計算の純粋ユニットテスト（DB不要・レート制限なし）。

失敗モードごとに合成系列で検証する。実DB突合のgolden testは移行後に追加する。
docs/design/pre2000-data.md §6,§7。
"""
from findex.derive.streaks import StreakOverride, compute_streaks, format_years


def _series(start, vals):
    return [(start + i, v) for i, v in enumerate(vals)]


def test_simple_growth():
    r = compute_streaks(_series(2010, [10, 11, 12, 13, 14]), listing_year=2008)
    assert r.growth_years == 4
    assert r.nocut_years == 4
    assert r.is_censored is False


def test_dividend_cut_breaks_streak():
    # 2014で減配 → 2015以降だけが連続
    r = compute_streaks(_series(2010, [10, 11, 12, 8, 9, 10]), listing_year=2008)
    assert r.growth_years == 2  # 8→9→10
    assert r.nocut_years == 2


def test_gap_breaks_streak():
    # 2013年が欠落（歯抜け）→ 打ち切り（地雷4）
    series = [(2010, 10), (2011, 11), (2012, 12), (2014, 13), (2015, 14)]
    r = compute_streaks(series, listing_year=2008)
    assert r.growth_years == 1  # 13→14 のみ（2012-2014はギャップ）


def test_censored_when_listed_before_data_floor():
    # データが2000始まりで、上場は1990 → 左打ち切り（花王型）
    r = compute_streaks(_series(2000, list(range(10, 36))), listing_year=1990)
    assert r.is_censored is True
    assert format_years(r.nocut_years, r.is_censored).endswith("年以上")


def test_not_censored_for_true_post2000_ipo():
    # データ開始年 == 上場年 → 真のIPO。打ち切りにしない（対照群）
    r = compute_streaks(_series(2006, [10, 11, 12, 13]), listing_year=2006)
    assert r.is_censored is False


def test_ipo_era_gap_not_censored():
    # IPO世代(2000上場)で初配当が下限band(2002)＝IPO→初配当の空白。全履歴保持＝打ち切りでない
    # （電通総研型: 上場2000-11・初配当2002）。上場<最古年 でも 上場>=2000 なら非打ち切り。
    r = compute_streaks(_series(2002, list(range(10, 35))), listing_year=2000)
    assert r.is_censored is False


def test_pre2000_lister_still_censored():
    # 1999上場（網羅開始2000より前）で系列が下限band始まり → 1999配当の欠落を疑い打ち切り
    r = compute_streaks(_series(2000, list(range(10, 35))), listing_year=1999)
    assert r.is_censored is True


def test_override_promotes_only_when_larger():
    # 機械計算26年だが公表36年 → 36に昇格、打ち切り解除（花王）
    r = compute_streaks(
        _series(2000, list(range(10, 36))),
        listing_year=1990,
        override=StreakOverride(growth_years=36),
    )
    assert r.growth_years == 36
    assert r.is_censored is False


def test_override_does_not_lower():
    # 公表が古くて機械計算より小さい → 下げない（地雷5）
    r = compute_streaks(
        _series(2010, [10, 11, 12, 13, 14]),
        listing_year=2008,
        override=StreakOverride(growth_years=2),
    )
    assert r.growth_years == 4


def test_in_progress_year_excluded():
    # 進行中の2026は支払い未確定 → 除外
    r = compute_streaks(_series(2022, [10, 11, 12, 13, 5]), listing_year=2000, drop_in_progress_year=2026)
    assert r.growth_years == 3  # 10→11→12→13


def test_no_cut_allows_flat_dividend():
    # 横ばいは非減配だが増配ではない
    r = compute_streaks(_series(2010, [10, 10, 10, 10]), listing_year=2008)
    assert r.nocut_years == 3
    assert r.growth_years == 0


def test_empty_series():
    r = compute_streaks([], listing_year=2000)
    assert r.growth_years == 0 and r.nocut_years == 0 and r.is_censored is False
