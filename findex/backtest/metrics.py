"""評価メトリクス（D8 §3）: モデル（スコア/グレード/指標）は前方アウトカムを説明できるか。

PITスコア（backtest_scores・look-ahead排除）と前方アウトカム（backtest_outcomes・正解ラベル）を
(code, as_of) で突き合わせ、以下を `backtest_metrics` に記録する:

- total/spearman      : total_score と前方アウトカムの順位相関（as_of横断プール）
- total/decile_spread : total_scoreの上位三分位−下位三分位の平均アウトカム差（上位が下位より
                        減配少・リターン高であることが最低条件）
- indicator/IC        : 各指標の生値 vs 前方アウトカムの順位相関（情報係数）。
                        信号ゼロ近傍の指標は重み低下/廃止候補＝柱2「進化する指標」の客観信号。
- claim/grade_calib   : grade_dividend 間の前方減配率スプレッド（最悪−最良）。

符号の読み: fwd_div_cut は減配=1 なので **負の相関が良い**（高スコア→減配少）。
fwd_total_return / fwd_dps_cagr は **正が良い**。fwd_max_dd は 0 に近い（負で小さい）ほど良い。

捏造しない原則: 値が None/片側欠損のペアは除外し sample_n に正直に反映。サンプル不足
（n<MIN_PAIRS）やグレード変動なし（PIT時点は財務欠落で大半が同一グレード）は value=None で
記録し「検証不能」を可視化する。スコープは生存者標本（PROGRESS §6）かつ財務系はPIT時点で
データ希薄＝実質は配当シグナルの検証であることを前提とする。
"""
from __future__ import annotations

import json
from collections import defaultdict

from .outcomes import DEFAULT_HORIZONS

# 相関を出す最小ペア数（これ未満は統計的に無意味として value=None）
MIN_PAIRS = 8
# 三分位スプレッドの最小サンプル（各分位に最低数を確保するため）
MIN_SPREAD_N = 12
# グレード較正で1グレードを評価対象にする最小サンプル
MIN_GRADE_N = 5

# IC を出す前方アウトカム（配当シグナル検証の主役は減配回避とトータルリターン）
_IC_OUTCOMES = ("fwd_div_cut", "fwd_total_return")
# total レベルで相関/スプレッドを出すアウトカム
_TOTAL_OUTCOMES = ("fwd_div_cut", "fwd_dps_cagr", "fwd_total_return", "fwd_max_dd")


def _avg_ranks(values: list[float]) -> list[float]:
    """同順位は平均順位（1始まり）。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None  # 片方が定数＝相関定義不能（例: PIT時点でグレード全同一）
    return cov / ((vx ** 0.5) * (vy ** 0.5))


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """順位相関。長さ不一致/サンプル不足/定数列は None。"""
    if len(xs) != len(ys) or len(xs) < MIN_PAIRS:
        return None
    return _pearson(_avg_ranks(xs), _avg_ranks(ys))


def tertile_spread(scores: list[float], outcomes: list[float]) -> tuple[float | None, int]:
    """スコア上位三分位 − 下位三分位の平均アウトカム差。"""
    n = len(scores)
    if n < MIN_SPREAD_N:
        return None, n
    pairs = sorted(zip(scores, outcomes), key=lambda p: p[0])
    k = n // 3
    bottom = [o for _, o in pairs[:k]]
    top = [o for _, o in pairs[-k:]]
    return (sum(top) / len(top) - sum(bottom) / len(bottom)), n


def _put(conn, run_id, level, key, metric, value, sample_n) -> None:
    conn.execute(
        "INSERT INTO backtest_metrics (run_id, level, key, metric, value, sample_n) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(run_id, level, key, metric) DO UPDATE SET "
        "value=excluded.value, sample_n=excluded.sample_n",
        (run_id, level, key, metric, value, sample_n),
    )


def build_metrics(conn, run_id: int | None = None, *, horizons=DEFAULT_HORIZONS) -> dict:
    """指定 run（既定=最新）のPITスコアと前方アウトカムから評価メトリクスを算出・記録する。"""
    if run_id is None:
        row = conn.execute("SELECT MAX(run_id) FROM backtest_runs").fetchone()
        run_id = row[0] if row else None
    if run_id is None:
        raise ValueError("backtest_runs が空です。先に `backtest --what pit` を実行してください。")

    conn.execute("DELETE FROM backtest_metrics WHERE run_id=?", (run_id,))
    written = 0
    signal_inds: set[str] = set()

    for h in horizons:
        rows = conn.execute(
            "SELECT bs.total_score, bs.score_json, bs.grade_dividend, "
            "bo.fwd_div_cut, bo.fwd_dps_cagr, bo.fwd_total_return, bo.fwd_max_dd "
            "FROM backtest_scores bs JOIN backtest_outcomes bo "
            "ON bs.code=bo.code AND bs.as_of_date=bo.as_of_date "
            "WHERE bs.run_id=? AND bo.horizon_y=?",
            (run_id, h),
        ).fetchall()
        if not rows:
            continue

        outcome_idx = {"fwd_div_cut": 3, "fwd_dps_cagr": 4, "fwd_total_return": 5, "fwd_max_dd": 6}

        # --- total レベル: spearman + 三分位スプレッド ---
        for oc in _TOTAL_OUTCOMES:
            oi = outcome_idx[oc]
            xs, ys = [], []
            for r in rows:
                if r[0] is None or r[oi] is None:
                    continue
                xs.append(r[0])
                ys.append(r[oi])
            sp = spearman(xs, ys)
            _put(conn, run_id, "total", f"{oc}|h{h}", "spearman",
                 round(sp, 4) if sp is not None else None, len(xs))
            written += 1
            spread, sn = tertile_spread(xs, ys)
            _put(conn, run_id, "total", f"{oc}|h{h}", "decile_spread",
                 round(spread, 6) if spread is not None else None, sn)
            written += 1

        # --- indicator レベル: IC（生値 vs アウトカム） ---
        parsed = []
        for r in rows:
            raw = (json.loads(r[1]).get("raw") if r[1] else None) or {}
            parsed.append((raw, r))
        inds: set[str] = set()
        for raw, _ in parsed:
            inds.update(raw.keys())
        for ind in sorted(inds):
            for oc in _IC_OUTCOMES:
                oi = outcome_idx[oc]
                xs, ys = [], []
                for raw, r in parsed:
                    v = raw.get(ind)
                    if v is None or r[oi] is None:
                        continue
                    xs.append(v)
                    ys.append(r[oi])
                ic = spearman(xs, ys)
                _put(conn, run_id, "indicator", f"{ind}|{oc}|h{h}", "IC",
                     round(ic, 4) if ic is not None else None, len(xs))
                written += 1
                if ic is not None and abs(ic) >= 0.05:
                    signal_inds.add(ind)

        # --- claim レベル: grade_dividend 較正（前方減配率スプレッド） ---
        by_grade: dict[str, list[int]] = defaultdict(list)
        for r in rows:
            if r[2] is None or r[3] is None:
                continue
            by_grade[r[2]].append(r[3])
        rates = {g: sum(v) / len(v) for g, v in by_grade.items() if len(v) >= MIN_GRADE_N}
        total_n = sum(len(v) for v in by_grade.values())
        calib = round(max(rates.values()) - min(rates.values()), 4) if len(rates) >= 2 else None
        _put(conn, run_id, "claim", f"grade_dividend|fwd_div_cut|h{h}", "grade_calib", calib, total_n)
        written += 1

    conn.commit()
    return {"run_id": run_id, "rows": written, "horizons": list(horizons),
            "signal_indicators": sorted(signal_inds)}
