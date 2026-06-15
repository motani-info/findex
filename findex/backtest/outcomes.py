"""前方アウトカム（D8 §2）: as_of から前方N年の「実際に起きたこと」を算出。

これはPITスコアの正解ラベル。**純粋に前方データのみ**で作るので look-ahead の心配がない
（as_of より後のデータを使うのが定義そのもの）。インカム戦略なので減配回避が第一アウトカム。
- fwd_div_cut     : 前方horizon年で減配したか（binary。減配検出は機械の頑健ロジックを流用）
- fwd_dps_cagr    : 前方DPS成長（増配実現）
- fwd_total_return: 価格騰落＋受取配当（初期株価ベースの単純トータルリターン）
- fwd_max_dd      : 前方期間の最大ドローダウン（危機耐性）
"""
from __future__ import annotations

from datetime import datetime

from ..derive.compute import NOCUT_EPS

# バックテストの as_of グリッド（各年6月末）。財務系PITは2008下限だがアウトカムは
# 配当(1989+)/株価(2000+)のみ依存。前方5年が landavailable な範囲を既定にする。
DEFAULT_GRID_START = 2008
DEFAULT_GRID_END = 2020   # 2020+5=2025（前方5年が揃う上限）
DEFAULT_HORIZONS = (3, 5)


def as_of_grid(start: int = DEFAULT_GRID_START, end: int = DEFAULT_GRID_END,
               month: int = 6, day: int = 30) -> list[str]:
    return [f"{y:04d}-{month:02d}-{day:02d}" for y in range(start, end + 1)]


def _dps_by_year(conn, code: str) -> dict[int, float]:
    return {
        fy: dps
        for fy, dps in conn.execute(
            "SELECT fiscal_year, dps FROM dividend_annual "
            "WHERE code=? AND confidence!='review' ORDER BY fiscal_year",
            (code,),
        )
    }


def _price_on_or_before(conn, code: str, iso: str) -> float | None:
    r = conn.execute(
        "SELECT close_adj FROM price_history WHERE code=? AND date<=? AND close_adj>0 "
        "ORDER BY date DESC LIMIT 1",
        (code, iso),
    ).fetchone()
    return r[0] if r else None


def _max_drawdown(conn, code: str, start_iso: str, end_iso: str) -> float | None:
    rows = conn.execute(
        "SELECT close_adj FROM price_history WHERE code=? AND date>=? AND date<=? AND close_adj>0 "
        "ORDER BY date",
        (code, start_iso, end_iso),
    ).fetchall()
    if len(rows) < 2:
        return None
    peak = rows[0][0]
    mdd = 0.0
    for (p,) in rows:
        if p > peak:
            peak = p
        dd = p / peak - 1.0
        if dd < mdd:
            mdd = dd
    return round(mdd, 6)


def _forward_cut(dps: dict[int, float], y0: int, y1: int) -> int | None:
    """前方window (y0, y1] で真の減配があったか（binary）。None=判定不能。

    減配検出は「前年割れ かつ 2年前も割れ」（決算変更/特別配当スパイク復帰の誤検出を回避）。
    windowの先頭が特別配当のスパイク年だと2年前文脈が無く誤検出するため、**y0-2..y1 を文脈に
    含めて系列を作り、減配は前方年（fy>y0）のものだけ数える**（花王FY2012=93特配の罠を回避）。
    """
    series = [(fy, dps[fy]) for fy in range(y0 - 2, y1 + 1) if fy in dps]
    fwd = [fy for fy, _ in series if fy > y0]
    if len(fwd) < 1 or len(series) < 2:
        return None  # 前方に比較対象が無い＝判定不能
    for i in range(1, len(series)):
        fy, v = series[i]
        if fy <= y0:
            continue  # 文脈年（基準確立用。減配としては数えない）
        prev = series[i - 1][1]
        if v >= prev * NOCUT_EPS:
            continue
        if i >= 2 and v >= series[i - 2][1] * NOCUT_EPS:
            continue  # 直前スパイクからの復帰＝減配でない（特配スパイクが窓先頭の罠を回避）
        return 1  # 持続的な減配
    return 0
    # 注: 配当の分割単位不整合/欠損レコードによる単年アーティファクト（神戸物産・沖縄セルラー）は
    # **取得層 flag_dividend_anomalies で source=review に隔離**済み＝ここの系列(confidence!=review)
    # には入らない。バックテスト側で再ガードしない（実減配を誤って消さないため・根因は1箇所で是正）。


def compute_outcome(conn, code: str, as_of: str, horizon: int, dps: dict[int, float]) -> dict | None:
    """1 (code, as_of, horizon) の前方アウトカム。算出不能なフィールドは None（捏造しない）。"""
    y0 = int(as_of[:4])
    y1 = y0 + horizon
    end_iso = f"{y1:04d}-{as_of[5:]}"

    # 減配回避（前方window・2年文脈つきで特配スパイクの誤検出を回避）
    fwd_div_cut = _forward_cut(dps, y0, y1)

    # 前方DPS CAGR（基準>0・スパン充足のみ）
    fwd_dps_cagr = None
    d0 = dps.get(y0)
    d1 = dps.get(y1)
    if d0 and d1 and d0 > 0 and d1 > 0:
        raw = (d1 / d0) ** (1 / horizon) - 1
        if -0.5 < raw < 1.0:
            fwd_dps_cagr = round(raw, 6)

    # トータルリターン（価格騰落＋受取配当／初期株価）＋ 最大DD
    p0 = _price_on_or_before(conn, code, as_of)
    p1 = _price_on_or_before(conn, code, end_iso)
    fwd_total_return = None
    if p0 and p1 and p0 > 0:
        div_received = sum(dps[fy] for fy in range(y0 + 1, y1 + 1) if fy in dps)
        fwd_total_return = round((p1 - p0 + div_received) / p0, 6)
    fwd_max_dd = _max_drawdown(conn, code, as_of, end_iso)

    if fwd_div_cut is None and fwd_dps_cagr is None and fwd_total_return is None:
        return None  # 前方データ皆無（若い銘柄等）＝行を作らない
    return {
        "fwd_div_cut": fwd_div_cut, "fwd_dps_cagr": fwd_dps_cagr,
        "fwd_total_return": fwd_total_return, "fwd_max_dd": fwd_max_dd,
    }


def build_outcomes(conn, codes: list[str], *, grid: list[str] | None = None,
                   horizons=DEFAULT_HORIZONS) -> dict:
    """コホート/指定銘柄の前方アウトカムを backtest_outcomes に記録。"""
    grid = grid or as_of_grid()
    n = 0
    cut_dist = {0: 0, 1: 0}
    for code in codes:
        dps = _dps_by_year(conn, code)
        if not dps:
            continue
        for as_of in grid:
            for h in horizons:
                o = compute_outcome(conn, code, as_of, h, dps)
                if o is None:
                    continue
                conn.execute(
                    "INSERT INTO backtest_outcomes "
                    "(code, as_of_date, horizon_y, fwd_div_cut, fwd_dps_cagr, fwd_total_return, fwd_max_dd) "
                    "VALUES (?,?,?,?,?,?,?) ON CONFLICT(code, as_of_date, horizon_y) DO UPDATE SET "
                    "fwd_div_cut=excluded.fwd_div_cut, fwd_dps_cagr=excluded.fwd_dps_cagr, "
                    "fwd_total_return=excluded.fwd_total_return, fwd_max_dd=excluded.fwd_max_dd",
                    (code, as_of, h, o["fwd_div_cut"], o["fwd_dps_cagr"],
                     o["fwd_total_return"], o["fwd_max_dd"]),
                )
                n += 1
                if o["fwd_div_cut"] in cut_dist:
                    cut_dist[o["fwd_div_cut"]] += 1
    conn.commit()
    return {"rows": n, "grid": [grid[0], grid[-1]], "horizons": list(horizons),
            "cut_dist": cut_dist, "scored_at": datetime.now().isoformat(timespec="seconds")}
