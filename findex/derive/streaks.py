"""ストリーク計算の正準モジュール（連続増配・連続非減配・打ち切り判定）。

**プロジェクト内でストリークを計算するのはここだけ**。DBアクセスと純粋計算を分離し、
入力は (fiscal_year, dps) のリストと付随情報のみ。docs/design/pre2000-data.md §2,§5。

判定式:
    is_censored = (listing_year < earliest_div_year) かつ (streak_start_year == earliest_div_year)
"""
from __future__ import annotations

from dataclasses import dataclass

# 浮動小数マージン（地雷の正準仕様）
GROWTH_MARGIN = 1.0001   # dps > prev * 1.0001 を増配とみなす
NOCUT_MARGIN = 0.999     # dps >= prev * 0.999 を非減配とみなす


@dataclass(frozen=True)
class StreakResult:
    growth_years: int          # 連続増配年数
    nocut_years: int           # 連続非減配年数
    is_censored: bool          # True なら「N年以上」表示
    earliest_year: int | None  # 評価に使った系列の最古年度
    latest_year: int | None    # 評価に使った最新（確定）年度


@dataclass(frozen=True)
class StreakOverride:
    growth_years: int | None = None
    nocut_years: int | None = None


def compute_streaks(
    annual: list[tuple[int, float]],
    *,
    listing_year: int | None = None,
    data_floor_year: int = 2002,
    data_start_year: int = 2000,
    drop_in_progress_year: int | None = None,
    override: StreakOverride | None = None,
) -> StreakResult:
    """会計年度別配当からストリークを計算する。

    annual: (fiscal_year, dps) のリスト（順不同可・重複は後勝ち）。
    listing_year: 上場年。打ち切り判定の独立シグナル。None なら下限band到達で打ち切り扱い。
    data_floor_year: この年以下で系列が始まると左打ち切りを疑う（デフォルト 2002）。
    drop_in_progress_year: 進行中で支払い未確定の年度。指定時は除外する。
    override: 公表値。機械計算より大きいときだけ昇格させる（地雷5）。
    """
    # 正規化（重複除去・昇順）
    series = sorted({fy: dps for fy, dps in annual}.items())
    if not series:
        return StreakResult(0, 0, False, None, None)

    if drop_in_progress_year is not None:
        series = [(fy, dps) for fy, dps in series if fy != drop_in_progress_year]
    if not series:
        return StreakResult(0, 0, False, None, None)

    earliest_year = series[0][0]
    latest_year = series[-1][0]

    growth_years, growth_start = _streak(series, kind="growth")
    nocut_years, nocut_start = _streak(series, kind="nocut")

    # --- 打ち切り判定 ---
    # ストリークが系列先頭まで遡って切れている（= 開始年が最古年と一致）かつ
    # 系列が下限band で始まっている場合、それ以前のデータ欠落を疑う。
    reaches_floor = (nocut_start == earliest_year) and (earliest_year <= data_floor_year)
    if listing_year is None:
        # 上場日が無ければ安全側: 下限band到達は打ち切り扱い。
        is_censored = reaches_floor
    else:
        # 上場日があれば確定判定。打ち切り＝「データ下限より前に既に公開・配当していた履歴の欠落」。
        # ①上場が最古配当年より前（公開時点で既に配当があったはず）かつ
        # ②上場がデータ網羅開始年(2000)より前（IPO以降を完全保持できない世代）の両方が必要。
        # IPO世代(>=2000上場)は IPO→初配当の空白があっても全履歴を保持＝打ち切りでない（電通総研2000上場/初配当2002）。
        is_censored = (
            reaches_floor and listing_year < earliest_year and listing_year < data_start_year
        )

    # --- 公表値オーバーライド（公表 > 機械計算 のときだけ昇格）---
    if override is not None:
        if override.growth_years is not None and override.growth_years > growth_years:
            growth_years = override.growth_years
            is_censored = False
        if override.nocut_years is not None and override.nocut_years > nocut_years:
            nocut_years = override.nocut_years
            is_censored = False

    return StreakResult(
        growth_years=growth_years,
        nocut_years=nocut_years,
        is_censored=is_censored,
        earliest_year=earliest_year,
        latest_year=latest_year,
    )


def _streak(series: list[tuple[int, float]], *, kind: str) -> tuple[int, int | None]:
    """末尾から遡って連続年数とその開始年度を返す。歯抜け（年度不連続）で打ち切る。"""
    if not series:
        return 0, None

    years = 0
    start_year = series[-1][0]
    for i in range(len(series) - 1, 0, -1):
        cur_fy, cur_dps = series[i]
        prev_fy, prev_dps = series[i - 1]
        if cur_fy - prev_fy != 1:  # 歯抜け → ここで打ち切り（地雷4）
            break
        if kind == "growth":
            ok = cur_dps > prev_dps * GROWTH_MARGIN
        else:  # nocut
            ok = cur_dps >= prev_dps * NOCUT_MARGIN
        if not ok:
            break
        years += 1
        start_year = prev_fy
    return years, start_year


def format_years(years: int, is_censored: bool) -> str:
    """表示用。打ち切りなら「N年以上」、そうでなければ「N年」。嘘の数字を出さない。"""
    return f"{years}年以上" if is_censored else f"{years}年"
