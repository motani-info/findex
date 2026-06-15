"""導出層: 前段テーブル → computed_metrics（唯一の出口）。

Phase3-a はストリーク（連続増配/非減配・打ち切り・override昇格・N+）を担当。
- 機械計算は dividend_annual の **confidence!='review'**（単位整合が取れた系列）から。
- result_overrides（zai公表）は**昇格のみ**（機械<公表のとき）。promote時はN+解除。
- 由来(machine/override/censored)と status を JSON で computed_metrics に残す。
合成順序: 機械計算 → result_override（昇格） → N+ フォールバック（[charter]）。
"""
from __future__ import annotations

import json
from datetime import date, datetime

from .. import config
from .streaks import StreakOverride, compute_streaks

NOCUT_EPS = 0.999  # 非減配判定マージン（streaks と整合）


def _listing_year(conn, code: str) -> int | None:
    r = conn.execute("SELECT listing_date FROM stocks WHERE code=?", (code,)).fetchone()
    return int(r[0][:4]) if r and r[0] else None


def _override(conn, code: str, field: str) -> float | None:
    r = conn.execute(
        "SELECT value FROM result_overrides WHERE code=? AND field=?", (code, field)
    ).fetchone()
    return r[0] if r else None


def compute_streaks_for_code(conn, code: str) -> dict:
    """1銘柄のストリークを合成（機械→override→N+）。computed_metrics 断片を返す。"""
    annual = [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT fiscal_year, dps FROM dividend_annual "
            "WHERE code=? AND confidence!='review' ORDER BY fiscal_year",
            (code,),
        )
    ]
    listing_year = _listing_year(conn, code)
    ov_g = _override(conn, code, "consecutive_dividend_growth_years")
    ov_nc = _override(conn, code, "consecutive_no_cut_years")

    machine = compute_streaks(annual, listing_year=listing_year,
                              data_floor_year=config.DATA_FLOOR_YEAR)
    final = compute_streaks(
        annual, listing_year=listing_year, data_floor_year=config.DATA_FLOOR_YEAR,
        override=StreakOverride(
            growth_years=int(ov_g) if ov_g is not None else None,
            nocut_years=int(ov_nc) if ov_nc is not None else None,
        ),
    )

    def src(final_v, machine_v, censored):
        if ov_g is not None and final_v > machine_v:
            return "override"
        return "censored" if censored else "machine"

    g_src = src(final.growth_years, machine.growth_years, machine.is_censored)
    return {
        "consecutive_dividend_growth_years": final.growth_years,
        "consecutive_no_cut_years": final.nocut_years,
        "streak_is_censored": 1 if final.is_censored else 0,
        "_source": {"consecutive_dividend_growth_years": g_src},
        "_status": {
            "consecutive_dividend_growth_years": "censored" if final.is_censored else "ok",
        },
        "_no_data": not annual,
    }


def _price_on_or_before(conn, code: str, target_iso: str) -> float | None:
    r = conn.execute(
        "SELECT close_adj FROM price_history WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
        (code, target_iso),
    ).fetchone()
    return r[0] if r else None


def _latest_eps_pair(conn, code: str, years_back: int = 5, min_span: int = 4):
    """(eps_now, eps_then, adequate) を financial_snapshots から。

    増配の質はEPSの5年比較が前提。financial_snapshotsがJ-Quantsの約2年窓しか無いと
    1-2年比較に縮退し誤分類する → 実スパンが min_span 年未満なら adequate=False（質はinsufficient）。
    EDINET多年バックフィル後に解消。
    """
    rows = conn.execute(
        "SELECT fiscal_year, eps FROM financial_snapshots WHERE code=? AND eps IS NOT NULL ORDER BY fiscal_year",
        (code,),
    ).fetchall()
    if not rows:
        return None, None, False
    eps = {fy: v for fy, v in rows}
    now_fy = rows[-1][0]
    eps_now = eps[now_fy]
    then_fy = now_fy - years_back
    cand = [fy for fy in eps if fy <= then_fy]
    if cand:
        used = max(cand)
    else:
        used = rows[0][0]
    adequate = (now_fy - used) >= min_span
    return eps_now, eps[used], adequate


def count_dividend_cuts(vals: list[float]) -> int:
    """真の減配回数。前年割れ かつ 2年前の水準も割れ（スパイク復帰は除外）。

    決算変更/分割/特別配当のスパイク後に基準超で戻る場合は減配でない（花王FY2012=93→64）。
    """
    cuts = 0
    for i in range(1, len(vals)):
        if vals[i] >= vals[i - 1] * NOCUT_EPS:
            continue
        if i >= 2 and vals[i] >= vals[i - 2] * NOCUT_EPS:
            continue
        cuts += 1
    return cuts


def _classify_quality(eps_now, eps_then, dps_mult) -> str:
    """増配の質（D4.5）: DPS倍率=EPS倍率×配当性向変化。sound/payout_driven/cyclical。"""
    if eps_now is None or eps_then is None or eps_then <= 0 or eps_now <= 0:
        return "cyclical"  # 赤字/算出不能=一過性扱い（安全側）
    eps_mult = eps_now / eps_then
    if eps_mult >= 1.5:
        return "sound"        # EPS牽引
    if eps_mult >= 1.0:
        return "payout_driven"  # EPS伸び弱く性向拡大依存
    return "cyclical"          # EPS横ばい/減


def compute_dividend_metrics_for_code(conn, code: str) -> dict | None:
    """YoC・DPS倍率・増配の質・CAGR・信頼性・減配回数（D4.5）。"""
    annual = [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT fiscal_year, dps FROM dividend_annual "
            "WHERE code=? AND confidence!='review' ORDER BY fiscal_year",
            (code,),
        )
    ]
    if len(annual) < 2:
        return None
    vals = [d for _, d in annual]
    annual_div = vals[-1]
    status: dict[str, str] = {}

    # CAGR（旧式踏襲）
    cagr_5y = cagr_10y = None
    if len(vals) >= 6 and vals[-6] > 0 and vals[-1] > 0:
        raw = (vals[-1] / vals[-6]) ** (1 / 5) - 1
        cagr_5y = round(raw, 6) if -0.5 < raw < 1.0 else None
    if len(vals) >= 11 and vals[-11] > 0 and vals[-1] > 0:
        raw = (vals[-1] / vals[-11]) ** (1 / 10) - 1
        cagr_10y = round(raw, 6) if -0.5 < raw < 0.5 else None

    # 減配回数（過去20会計年度）と信頼性
    # 単純YoYだと決算変更/分割/特別配当のスパイク復帰を誤検出（花王FY2012=93→64・36年連続増配）。
    # 真の減配＝前年割れ かつ 2年前の水準も割れ（スパイクから基準超で戻る場合は減配でない）。
    cuts_20y = count_dividend_cuts([d for _, d in annual[-21:]])
    reliability = 1.0 if cuts_20y == 0 else 0.6 if cuts_20y == 1 else 0.0
    status["dividend_reliability"] = "zero_legit" if reliability == 0.0 else "ok"

    # DPS倍率（5年）
    dps_mult = None
    if len(vals) >= 6 and vals[-6] > 0:
        dps_mult = vals[-1] / vals[-6]

    # 増配の質（EPS5年比較が前提。EPS履歴不足なら判定しない＝insufficient）
    eps_now, eps_then, eps_ok = _latest_eps_pair(conn, code, 5)
    if dps_mult and eps_ok:
        quality = _classify_quality(eps_now, eps_then, dps_mult)
        status["dividend_quality"] = "ok"
    else:
        quality = None
        status["dividend_quality"] = "insufficient"

    # YoC（最新DPS ÷ N年前株価。株価2000遡及済→本算出）
    latest_price_date = conn.execute(
        "SELECT MAX(date) FROM price_history WHERE code=?", (code,)
    ).fetchone()[0]
    yoc_5y = yoc_10y = None
    if latest_price_date:
        y = int(latest_price_date[:4])
        p5 = _price_on_or_before(conn, code, f"{y - 5}-12-31")
        p10 = _price_on_or_before(conn, code, f"{y - 10}-12-31")
        if p5 and p5 > 0:
            yoc_5y = annual_div / p5
        if p10 and p10 > 0:
            yoc_10y = annual_div / p10
    status["yield_on_cost_5y"] = "ok" if yoc_5y is not None else "insufficient"

    return {
        "annual_div": annual_div,
        "yield_on_cost_5y": yoc_5y,
        "yield_on_cost_10y": yoc_10y,
        "dividend_multiple": dps_mult,
        "dividend_quality": quality,
        "dividend_growth_5y_cagr": cagr_5y,
        "dividend_growth_10y_cagr": cagr_10y,
        "dividend_reliability": reliability,
        "dividend_cut_count_20y": cuts_20y,
        "_status": status,
    }


def _merge_json(conn, code: str, col: str, add: dict) -> str:
    r = conn.execute(f"SELECT {col} FROM computed_metrics WHERE code=?", (code,)).fetchone()
    cur = json.loads(r[0]) if r and r[0] else {}
    cur.update(add)
    return json.dumps(cur)


def build_dividend_metrics(conn, codes: list[str]) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    qdist: dict[str, int] = {}
    for code in codes:
        d = compute_dividend_metrics_for_code(conn, code)
        if not d:
            continue
        status_json = _merge_json(conn, code, "status_json", d.pop("_status"))
        conn.execute(
            """
            INSERT INTO computed_metrics
              (code, annual_div, yield_on_cost_5y, yield_on_cost_10y, dividend_multiple,
               dividend_quality, dividend_growth_5y_cagr, dividend_growth_10y_cagr,
               dividend_reliability, dividend_cut_count_20y, status_json, div_computed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(code) DO UPDATE SET
              annual_div=excluded.annual_div, yield_on_cost_5y=excluded.yield_on_cost_5y,
              yield_on_cost_10y=excluded.yield_on_cost_10y, dividend_multiple=excluded.dividend_multiple,
              dividend_quality=excluded.dividend_quality,
              dividend_growth_5y_cagr=excluded.dividend_growth_5y_cagr,
              dividend_growth_10y_cagr=excluded.dividend_growth_10y_cagr,
              dividend_reliability=excluded.dividend_reliability,
              dividend_cut_count_20y=excluded.dividend_cut_count_20y,
              status_json=excluded.status_json, div_computed_at=excluded.div_computed_at
            """,
            (code, d["annual_div"], d["yield_on_cost_5y"], d["yield_on_cost_10y"],
             d["dividend_multiple"], d["dividend_quality"], d["dividend_growth_5y_cagr"],
             d["dividend_growth_10y_cagr"], d["dividend_reliability"], d["dividend_cut_count_20y"],
             status_json, now),
        )
        n += 1
        if d["dividend_quality"]:
            qdist[d["dividend_quality"]] = qdist.get(d["dividend_quality"], 0) + 1
    conn.commit()
    return {"rows": n, "quality_dist": qdist}


def build_streaks(conn, codes: list[str]) -> dict:
    """コホート/指定銘柄のストリークを computed_metrics に upsert。"""
    now = datetime.now().isoformat(timespec="seconds")
    n = censored = overridden = 0
    for code in codes:
        d = compute_streaks_for_code(conn, code)
        if d["_no_data"]:
            continue
        conn.execute(
            """
            INSERT INTO computed_metrics
              (code, consecutive_dividend_growth_years, consecutive_no_cut_years,
               streak_is_censored, source_json, status_json, div_computed_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(code) DO UPDATE SET
              consecutive_dividend_growth_years=excluded.consecutive_dividend_growth_years,
              consecutive_no_cut_years=excluded.consecutive_no_cut_years,
              streak_is_censored=excluded.streak_is_censored,
              source_json=excluded.source_json, status_json=excluded.status_json,
              div_computed_at=excluded.div_computed_at
            """,
            (code, d["consecutive_dividend_growth_years"], d["consecutive_no_cut_years"],
             d["streak_is_censored"], json.dumps(d["_source"]), json.dumps(d["_status"]), now),
        )
        n += 1
        censored += d["streak_is_censored"]
        if d["_source"]["consecutive_dividend_growth_years"] == "override":
            overridden += 1
    conn.commit()
    return {"rows": n, "censored": censored, "overridden": overridden}
