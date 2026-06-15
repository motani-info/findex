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
    nc_src = "override" if (ov_nc is not None and final.nocut_years > machine.nocut_years) \
        else ("censored" if final.is_censored else "machine")
    streak_st = "censored" if final.is_censored else "ok"
    return {
        "consecutive_dividend_growth_years": final.growth_years,
        "consecutive_no_cut_years": final.nocut_years,
        "streak_is_censored": 1 if final.is_censored else 0,
        "_source": {
            "consecutive_dividend_growth_years": g_src,
            "consecutive_no_cut_years": nc_src,
        },
        "_status": {
            # 連続非減配/増配とも打ち切り(N+)なら裸の数字で採点しない＝censored（採点層で分母除外）
            "consecutive_dividend_growth_years": streak_st,
            "consecutive_no_cut_years": streak_st,
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


def _fin_series(conn, code: str, column: str):
    return conn.execute(
        f"SELECT fiscal_year, {column} FROM financial_snapshots "
        f"WHERE code=? AND {column} IS NOT NULL ORDER BY fiscal_year",
        (code,),
    ).fetchall()


def _cagr_5y(rows, *, min_span: int = 4, bound: float = 0.5):
    """(値, status)。5年CAGR。基準負/ゼロ・スパン不足・外れ値は insufficient（捏造しない）。"""
    if len(rows) < 2:
        return None, "insufficient"
    now_fy, v_now = rows[-1]
    then_fy = now_fy - 5
    cand = [(fy, v) for fy, v in rows if fy <= then_fy]
    used_fy, v_old = cand[-1] if cand else rows[0]
    span = now_fy - used_fy
    if span < min_span:
        return None, "insufficient"  # 5年成長に満たない（構造的）
    if v_old <= 0 or v_now <= 0:
        return None, "insufficient"  # 負/ゼロ基準は成長率算出不能
    raw = (v_now / v_old) ** (1 / span) - 1
    if not (-bound < raw < bound):
        return None, "insufficient"  # 外れ値（基準年アーティファクト）→出さない
    return round(raw, 6), "ok"


def _latest_nonnull(conn, code: str, column: str) -> float | None:
    """そのフィールドの最新の非NULL値（深いBSはEDINET最新有報年にのみ在るため）。"""
    r = conn.execute(
        f"SELECT {column} FROM financial_snapshots WHERE code=? AND {column} IS NOT NULL "
        f"ORDER BY fiscal_year DESC LIMIT 1",
        (code,),
    ).fetchone()
    return r[0] if r else None


def _latest_dps(conn, code: str) -> float | None:
    r = conn.execute(
        "SELECT dps FROM dividend_annual WHERE code=? AND confidence!='review' "
        "ORDER BY fiscal_year DESC LIMIT 1",
        (code,),
    ).fetchone()
    return r[0] if r else None


_FIN_COLS = [
    "equity_ratio", "debt_to_equity", "roe", "operating_margin",
    "eps_growth_5y", "revenue_growth_5y_cagr", "roic_minus_wacc",
    "fcf_payout_coverage", "retained_earnings_div_ratio", "payout_ratio", "doe",
]


def _resolve_ibd(equity, ibd, deep_ran: bool, std: str | None):
    """有利子負債の採用値とstatus（D/E・ROICで共有）。

    ibd在り(>0)=ok。ibd==0=zero_legit。ibd無しは基準で分岐:
      JGAAP（標準タクソノミで信頼可）＝深いBS抽出済なら債務タグ皆無=無借金 zero_legit。
      IFRS/US（独自拡張で完全抽出不可）＝insufficient（部分値/0を出さず捏造を避ける）。
    返り値: (採用負債D, status)。okはD=ibd, zero_legitはD=0, それ以外はD=None。
    """
    if not (equity and equity > 0):
        return None, "missing"
    if ibd is not None and ibd > 0:
        return ibd, "ok"
    if ibd == 0:
        return 0.0, "zero_legit"
    if not deep_ran:
        return None, "missing"  # 抽出未実行（EDINETなし/US連結不在）
    if std == "jgaap":
        return 0.0, "zero_legit"  # 無借金
    return None, "insufficient"  # IFRS拡張タグで信頼抽出不可


def compute_financial_metrics_for_code(conn, code: str) -> dict | None:
    """財務由来指標（D4.5）の生値＋5状態status。採点はPhase4。

    点指標は最新の実績年度（net_income在り＝J-Quants確報）から。成長は5年史（EDINET補完）から。
    roic_minus_wacc は市場値/beta（価格層）依存→現状 insufficient。
    """
    # 点指標(PL/CF/株数)は最新の**J-Quants確報**をアンカー（完全な行）。EDINET5年史が当年に
    # net_incomeだけ埋めた薄いorphan行（営業利益・株数を欠く）を掴まないよう jquants 優先。
    core = conn.execute(
        "SELECT fiscal_year, revenue, operating_income, net_income, eps, total_assets, "
        "equity_attributable, operating_cf, shares_outstanding FROM financial_snapshots "
        "WHERE code=? AND net_income IS NOT NULL "
        "ORDER BY (source LIKE '%jquants%') DESC, fiscal_year DESC LIMIT 1",
        (code,),
    ).fetchone()
    if not core:
        return None
    (fy, revenue, op_income, net_income, eps, total_assets, equity, op_cf, shares) = core
    # 深いBS(有利子負債/利益剰余金/capex)はEDINET最新有報年（アンカーと別年のことがある）に
    # 在る。各フィールド独立に「最新の非NULL値」を採る（最新BSスナップショット）。
    capex = _latest_nonnull(conn, code, "capex")
    retained = _latest_nonnull(conn, code, "retained_earnings")
    ibd = _latest_nonnull(conn, code, "interest_bearing_debt")
    # 深いBS抽出が走ったか（債務タグ皆無=無借金 と 抽出未実行=取得不能 を区別する材料）
    deep_ran = (retained is not None) or (capex is not None) or \
        (_latest_nonnull(conn, code, "total_liabilities") is not None)
    std = conn.execute(
        "SELECT accounting_standard FROM stocks WHERE code=?", (code,)
    ).fetchone()
    std = std[0] if std else None
    dps = _latest_dps(conn, code)
    div_total = dps * shares if (dps is not None and shares) else None

    out: dict = {c: None for c in _FIN_COLS}
    status: dict[str, str] = {}

    # 自己資本比率
    if equity is not None and total_assets and total_assets > 0:
        out["equity_ratio"], status["equity_ratio"] = round(equity / total_assets, 6), "ok"
    else:
        status["equity_ratio"] = "missing"

    # 有利子負債比率（ibd採用判定は _resolve_ibd に集約＝ROICと共有）
    ibd_used, status["debt_to_equity"] = _resolve_ibd(equity, ibd, deep_ran, std)
    if status["debt_to_equity"] == "ok":
        out["debt_to_equity"] = round(ibd_used / equity, 6)
    elif status["debt_to_equity"] == "zero_legit":
        out["debt_to_equity"] = 0.0

    # ROE
    if net_income is not None and equity and equity > 0:
        out["roe"], status["roe"] = round(net_income / equity, 6), "ok"
    else:
        status["roe"] = "missing"

    # 営業利益率
    if op_income is not None and revenue and revenue > 0:
        out["operating_margin"], status["operating_margin"] = round(op_income / revenue, 6), "ok"
    else:
        status["operating_margin"] = "missing"

    # 配当性向 = DPS/EPS（赤字は算出不能=insufficient）
    if dps == 0:
        out["payout_ratio"], status["payout_ratio"] = 0.0, "zero_legit"
    elif dps is not None and eps and eps > 0:
        out["payout_ratio"], status["payout_ratio"] = round(dps / eps, 6), "ok"
    elif eps is not None and eps <= 0:
        status["payout_ratio"] = "insufficient"
    else:
        status["payout_ratio"] = "missing"

    # DOE = 年間配当総額÷自己資本（独立算出＝ROE×配当性向の恒等式材料）
    if div_total is not None and equity and equity > 0:
        out["doe"], status["doe"] = round(div_total / equity, 6), "ok"
    else:
        status["doe"] = "missing"

    # 利益剰余金配当倍率（US連結はretained取得不能→insufficient）
    if retained is None:
        status["retained_earnings_div_ratio"] = "insufficient"
    elif div_total and div_total > 0 and retained > 0:
        r = retained / div_total
        if 0 < r < 1000:
            out["retained_earnings_div_ratio"], status["retained_earnings_div_ratio"] = round(r, 4), "ok"
        else:
            status["retained_earnings_div_ratio"] = "insufficient"
    else:
        status["retained_earnings_div_ratio"] = "missing"

    # FCF配当カバレッジ = (CFO−capex)/配当総額（capex無=insufficient。負FCFも実シグナルで保持）
    if op_cf is None or capex is None:
        status["fcf_payout_coverage"] = "insufficient"
    elif div_total and div_total > 0:
        r = (op_cf - capex) / div_total
        if -100 < r < 100:
            out["fcf_payout_coverage"], status["fcf_payout_coverage"] = round(r, 4), "ok"
        else:
            status["fcf_payout_coverage"] = "insufficient"
    else:
        status["fcf_payout_coverage"] = "missing"

    # ROIC−WACC（市場値/beta依存＝build_roicで後追い算出。財務単独runではinsufficient）
    status["roic_minus_wacc"] = "insufficient"

    # 成長（EDINET5年史バックフィルで前提が揃った）
    out["eps_growth_5y"], status["eps_growth_5y"] = _cagr_5y(_fin_series(conn, code, "eps"))
    out["revenue_growth_5y_cagr"], status["revenue_growth_5y_cagr"] = _cagr_5y(
        _fin_series(conn, code, "revenue")
    )

    out["_status"] = status
    out["_fy"] = fy
    return out


def build_financial_metrics(conn, codes: list[str]) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    ok_counts: dict[str, int] = {c: 0 for c in _FIN_COLS}
    set_clause = ",".join(f"{c}=excluded.{c}" for c in _FIN_COLS)
    insert_sql = (
        f"INSERT INTO computed_metrics (code,{','.join(_FIN_COLS)},status_json,fin_computed_at) "
        f"VALUES (?,{','.join('?' * len(_FIN_COLS))},?,?) "
        f"ON CONFLICT(code) DO UPDATE SET {set_clause},"
        f"status_json=excluded.status_json,fin_computed_at=excluded.fin_computed_at"
    )
    for code in codes:
        d = compute_financial_metrics_for_code(conn, code)
        if not d:
            continue
        status_json = _merge_json(conn, code, "status_json", d.pop("_status"))
        conn.execute(insert_sql, (code, *[d[c] for c in _FIN_COLS], status_json, now))
        for c in _FIN_COLS:
            if d[c] is not None:
                ok_counts[c] += 1
        n += 1
    conn.commit()
    return {"rows": n, "ok_counts": ok_counts}


# 市場ベンチマーク=日経225指数(^N225→code 'N225')。TOPIX指数は無料取得不可、TOPIX連動ETF
# (1306)は分割アーティファクト（2026-03の1:10分割が未調整）で分散膨張→不可。指数は分割/配当
# が無くクリーン、Nikkeiは広範市場代理として標準的（TOPIXと相関≒0.95）。
BENCHMARK_CODE = "N225"


def _weekly_closes(conn, code: str, start_iso: str) -> dict[str, float]:
    """週次終値 {YYYY-Www: close}（各週の最終営業日。昇順で上書き＝最後が週末）。"""
    rows = conn.execute(
        "SELECT date, close_adj FROM price_history WHERE code=? AND date>=? AND close_adj>0 "
        "ORDER BY date",
        (code, start_iso),
    ).fetchall()
    by_week: dict[str, float] = {}
    for d, c in rows:
        y, w, _ = date.fromisoformat(d).isocalendar()
        by_week[f"{y}-W{w:02d}"] = c
    return by_week


def compute_beta(conn, code: str, *, years: int = 5, min_points: int = 100) -> float | None:
    """週次リターン回帰の beta = Cov(銘柄, 市場)/Var(市場)。市場=日経225(N225)。

    週次5年(~260点)＝月次より頑健（月次60点は特異変動でノイズ過大）。点が min_points
    未満（上場浅い等）は算出しない（捏造しない）→ insufficient。
    """
    start = f"{date.today().year - years}-{date.today().month:02d}-01"
    s = _weekly_closes(conn, code, start)
    m = _weekly_closes(conn, BENCHMARK_CODE, start)
    weeks = sorted(set(s) & set(m))
    sr: list[float] = []
    mr: list[float] = []
    for i in range(1, len(weeks)):
        p0, p1 = s[weeks[i - 1]], s[weeks[i]]
        q0, q1 = m[weeks[i - 1]], m[weeks[i]]
        if p0 > 0 and q0 > 0:
            sr.append(p1 / p0 - 1)
            mr.append(q1 / q0 - 1)
    n = len(mr)
    if n < min_points:
        return None
    mm = sum(mr) / n
    ms = sum(sr) / n
    var = sum((x - mm) ** 2 for x in mr) / n
    if var <= 0:
        return None
    cov = sum((mr[i] - mm) * (sr[i] - ms) for i in range(n)) / n
    return round(cov / var, 4)


def build_beta(conn, codes: list[str]) -> dict:
    """beta を算出し financial_snapshots の最新年度行に格納。"""
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    vals: list[float] = []
    for code in codes:
        b = compute_beta(conn, code)
        if b is None:
            continue
        fy = conn.execute(
            "SELECT MAX(fiscal_year) FROM financial_snapshots WHERE code=?", (code,)
        ).fetchone()[0]
        if fy is None:
            continue
        conn.execute(
            "UPDATE financial_snapshots SET beta=?, collected_at=? WHERE code=? AND fiscal_year=?",
            (b, now, code, fy),
        )
        n += 1
        vals.append(b)
    conn.commit()
    vals.sort()
    med = vals[len(vals) // 2] if vals else None
    return {"rows": n, "median": med, "min": vals[0] if vals else None,
            "max": vals[-1] if vals else None}


# ROIC−WACC 定数（個別未抽出のため固定。実効税率は法定実効税率近似、Rf=10年国債近似、
# ERP=日本市場の株式リスクプレミアム長期平均近似）。値はモジュール定数として明示。
ROIC_RF = 0.01           # リスクフリーレート
ROIC_ERP = 0.06          # 株式リスクプレミアム（CAPM: Re=Rf+beta×ERP）
ROIC_TAX = 0.30          # 実効税率（NOPAT・税後負債コスト）
ROIC_RD_FALLBACK = 0.02  # 支払利息/有利子負債が取れない場合の負債コスト
ROIC_RD_MAX = 0.20       # Rdの正気域上限（外れ値はfallbackに倒す）
ROIC_BOUND = 0.5         # 結果の正気域（外れ値は出さない＝insufficient）


def compute_roic_for_code(conn, code: str):
    """ROIC−WACC（生値, status）。beta・時価総額（価格層）が揃ってから算出。

    NOPAT=営業利益×(1−税率)、投下資本=自己資本(簿価)+有利子負債D、ROIC=NOPAT/投下資本。
    CAPM Re=Rf+beta×ERP。Rd=支払利息/D（取れねばfallback2%）。WACC=(E/V)Re+(D/V)Rd(1−税率)、
    E=時価総額,V=E+D。**有利子負債が信頼抽出できない社（IFRS拡張タグ等）はD/E insufficientを
    連鎖してROICもinsufficient**（偽値を出さない）。無借金JGAAPはD=0で算出可。
    """
    core = conn.execute(
        "SELECT operating_income, equity_attributable FROM financial_snapshots "
        "WHERE code=? AND net_income IS NOT NULL "
        "ORDER BY (source LIKE '%jquants%') DESC, fiscal_year DESC LIMIT 1",
        (code,),
    ).fetchone()
    if not core:
        return None, "missing"
    op_income, equity = core
    if op_income is None or not (equity and equity > 0):
        return None, "insufficient"  # 銀行/持株等で営業利益不在→ROIC算出不能

    ibd = _latest_nonnull(conn, code, "interest_bearing_debt")
    deep_ran = (
        _latest_nonnull(conn, code, "retained_earnings") is not None
        or _latest_nonnull(conn, code, "capex") is not None
        or _latest_nonnull(conn, code, "total_liabilities") is not None
    )
    std = conn.execute("SELECT accounting_standard FROM stocks WHERE code=?", (code,)).fetchone()
    std = std[0] if std else None
    debt, de_status = _resolve_ibd(equity, ibd, deep_ran, std)
    if de_status not in ("ok", "zero_legit"):
        return None, "insufficient"  # 有利子負債が信頼抽出不可→連鎖insufficient
    # debt = ibd(ok) or 0.0(zero_legit=無借金)

    beta = _latest_nonnull(conn, code, "beta")
    if beta is None:
        return None, "insufficient"  # 上場浅い等でbeta算出不能
    mc = conn.execute("SELECT current_market_cap FROM computed_metrics WHERE code=?", (code,)).fetchone()
    market_cap = mc[0] if mc and mc[0] else None
    if not market_cap or market_cap <= 0:
        return None, "insufficient"

    # Rd=支払利息/有利子負債（D>0かつ実値在りのみ。外れ値・無借金はfallback/不使用）
    ie = _latest_nonnull(conn, code, "interest_expense")
    if debt and debt > 0 and ie is not None and ie >= 0:
        rd = ie / debt
        if not (0 <= rd < ROIC_RD_MAX):
            rd = ROIC_RD_FALLBACK
    else:
        rd = ROIC_RD_FALLBACK

    nopat = op_income * (1 - ROIC_TAX)
    invested = equity + debt  # 簿価投下資本
    roic = nopat / invested
    re = ROIC_RF + beta * ROIC_ERP
    e, d = market_cap, debt  # WACCの重みは市場値
    v = e + d
    wacc = (e / v) * re + (d / v) * rd * (1 - ROIC_TAX)
    val = roic - wacc
    if not (-ROIC_BOUND < val < ROIC_BOUND):
        return None, "insufficient"  # 外れ値（基準アーティファクト）→出さない
    return round(val, 6), "ok"


def build_roic(conn, codes: list[str]) -> dict:
    """ROIC−WACC を算出し computed_metrics に上書き（beta・価格指標の後段）。"""
    now = datetime.now().isoformat(timespec="seconds")
    n = ok = 0
    for code in codes:
        if not conn.execute("SELECT 1 FROM computed_metrics WHERE code=?", (code,)).fetchone():
            continue  # 財務指標が無い銘柄はスキップ（行を作らない）
        val, st = compute_roic_for_code(conn, code)
        status_json = _merge_json(conn, code, "status_json", {"roic_minus_wacc": st})
        conn.execute(
            "UPDATE computed_metrics SET roic_minus_wacc=?, status_json=?, fin_computed_at=? WHERE code=?",
            (val, status_json, now, code),
        )
        n += 1
        if val is not None:
            ok += 1
    conn.commit()
    return {"rows": n, "ok": ok}


def _latest_price(conn, code: str):
    """(date, close_adj) 最新の終値。"""
    return conn.execute(
        "SELECT date, close_adj FROM price_history WHERE code=? AND close_adj>0 "
        "ORDER BY date DESC LIMIT 1",
        (code,),
    ).fetchone()


_PRICE_COLS = ["per", "pbr", "current_market_cap", "div_yield", "mix_coefficient", "net_cash_per"]


def compute_price_metrics_for_code(conn, code: str) -> dict | None:
    """価格由来指標（D4.5）の生値＋5状態status。最新終値×最新J-Quants確報の1株/株数。

    PER=価格/EPS・PBR=価格/BPS・時価総額=価格×株数・配当利回り=DPS/価格・
    ミックス係数=PER×PBR・ネットキャッシュPER=PER×(1−ネットキャッシュ/時価総額)。
    赤字(EPS≤0)はPER算出不能=insufficient（捏造しない）。
    """
    pr = _latest_price(conn, code)
    if not pr:
        return None
    price_date, price = pr
    fin = conn.execute(
        "SELECT eps, bps, shares_outstanding, total_assets, equity_attributable, "
        "cash_and_equivalents FROM financial_snapshots "
        "WHERE code=? AND net_income IS NOT NULL "
        "ORDER BY (source LIKE '%jquants%') DESC, fiscal_year DESC LIMIT 1",
        (code,),
    ).fetchone()
    if not fin:
        return None
    eps, bps, shares, total_assets, equity, cash = fin
    dps = _latest_dps(conn, code)

    out: dict = {c: None for c in _PRICE_COLS}
    status: dict[str, str] = {}

    # PER（赤字は算出不能）
    if eps is None:
        status["per"] = "missing"
    elif eps <= 0:
        status["per"] = "insufficient"
    else:
        out["per"], status["per"] = round(price / eps, 4), "ok"

    # PBR（債務超過は算出不能）
    if bps is None:
        status["pbr"] = "missing"
    elif bps <= 0:
        status["pbr"] = "insufficient"
    else:
        out["pbr"], status["pbr"] = round(price / bps, 4), "ok"

    # 時価総額
    mcap = None
    if shares and shares > 0:
        mcap = price * shares
        out["current_market_cap"], status["current_market_cap"] = mcap, "ok"
    else:
        status["current_market_cap"] = "missing"

    # 配当利回り（無配=zero_legit・異常高は外れ値insufficient）
    if dps == 0:
        out["div_yield"], status["div_yield"] = 0.0, "zero_legit"
    elif dps is not None and price > 0:
        y = dps / price
        if 0 < y <= 0.30:
            out["div_yield"], status["div_yield"] = round(y, 6), "ok"
        else:
            status["div_yield"] = "insufficient"
    else:
        status["div_yield"] = "missing"

    # ミックス係数 = PER×PBR（両方ok時のみ）
    if out["per"] is not None and out["pbr"] is not None:
        out["mix_coefficient"], status["mix_coefficient"] = round(out["per"] * out["pbr"], 4), "ok"
    else:
        status["mix_coefficient"] = "insufficient"

    # ネットキャッシュPER = PER×(1−ネットキャッシュ/時価総額)。ネットキャッシュ=現金−総負債
    if (out["per"] is not None and mcap and mcap > 0 and cash is not None
            and total_assets is not None and equity is not None):
        net_cash = cash - (total_assets - equity)
        r = out["per"] * (1 - net_cash / mcap)
        if -500 < r < 500:
            out["net_cash_per"], status["net_cash_per"] = round(r, 4), "ok"
        else:
            status["net_cash_per"] = "insufficient"
    else:
        status["net_cash_per"] = "insufficient" if out["per"] is None else "missing"

    out["_status"] = status
    out["_price_date"] = price_date
    return out


def build_price_metrics(conn, codes: list[str]) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    ok_counts: dict[str, int] = {c: 0 for c in _PRICE_COLS}
    set_clause = ",".join(f"{c}=excluded.{c}" for c in _PRICE_COLS)
    insert_sql = (
        f"INSERT INTO computed_metrics (code,{','.join(_PRICE_COLS)},status_json,price_computed_at) "
        f"VALUES (?,{','.join('?' * len(_PRICE_COLS))},?,?) "
        f"ON CONFLICT(code) DO UPDATE SET {set_clause},"
        f"status_json=excluded.status_json,price_computed_at=excluded.price_computed_at"
    )
    for code in codes:
        d = compute_price_metrics_for_code(conn, code)
        if not d:
            continue
        status_json = _merge_json(conn, code, "status_json", d.pop("_status"))
        conn.execute(insert_sql, (code, *[d[c] for c in _PRICE_COLS], status_json, now))
        for c in _PRICE_COLS:
            if d[c] is not None:
                ok_counts[c] += 1
        n += 1
    conn.commit()
    return {"rows": n, "ok_counts": ok_counts}


# ══ Phase3-e: claim別グレード＋恒等式チェック（導出層の最終出口） ══════════════
# 主張(claim)ごとに依存指標(status_jsonキー)集合を持ち、その充足度でA〜Dを付ける（D2 §6.2）。
#   core=その主張に必須の指標、extra=期間充足/補助（欠けてもCにはしない＝B止まり）。
# A=core全ok＋extra充足、B=core全okだがextraにcensored/insufficient/missing、
# C=core一部insufficient/missing（評価不能・投稿しない）、D=coreが一つも算出されず（対象外）。
_GRADE_CLAIMS = {
    "grade_dividend": {  # 配当系（dps系列＋listing_date依存）
        "core": ["dividend_reliability"],
        "extra": ["consecutive_dividend_growth_years", "yield_on_cost_5y", "dividend_quality"],
    },
    "grade_valuation": {  # バリュ系（close_adj/eps/bps/shares依存）
        "core": ["per", "pbr"],
        "extra": ["div_yield", "mix_coefficient", "net_cash_per"],
    },
    "grade_health": {  # 財務系（equity/total_assets/net_income依存）
        "core": ["equity_ratio", "roe", "operating_margin"],
        "extra": ["debt_to_equity", "eps_growth_5y", "revenue_growth_5y_cagr", "payout_ratio"],
    },
    "grade_capital": {  # 資本効率系（capex/beta/cost_of_debt依存＝入手難）
        "core": ["roic_minus_wacc", "fcf_payout_coverage"],
        "extra": ["doe", "retained_earnings_div_ratio"],
    },
}
_OK_STATUS = ("ok", "zero_legit")  # 「present以上」＝採用可
IDENTITY_TOL = 0.15  # 恒等式 DOE≒ROE×payout の許容相対誤差（EPS=希薄化/期中平均株数の差を吸収）


def _grade_claim(status: dict, core: list[str], extra: list[str]) -> str:
    """1主張のグレード（A〜D）。core/extra の status から判定。

    D=core全てが未算出/欠損（missing/None＝構造的に対象外。無配の配当系/銀行の財務系等）、
    A/B=core全てok/zero_legit、C=それ以外（insufficient混在＝データは在るが評価不能）。
    insufficient（抽出を試みたが信頼不可）と missing（そもそも無い）を区別する。
    """
    core_st = [status.get(k) for k in core]
    absent = [s for s in core_st if s is None or s == "missing"]
    if len(absent) == len(core_st):
        return "D"  # core が一つも算出されず（構造的に対象外）
    if all(s in _OK_STATUS for s in core_st):
        extra_st = [status.get(k) for k in extra]
        if any(s in ("censored", "insufficient", "missing") for s in extra_st):
            return "B"  # 採用可だが期間不足/補助欠落の注記付き
        return "A"
    return "C"  # core に insufficient/欠損が混在＝評価不能（投稿しない）


def _identity_ok(doe, roe, payout, status: dict) -> int | None:
    """恒等式 DOE ≈ ROE × payout_ratio のクロスチェック（3指標とも ok のときのみ）。

    DOE=配当総額/自己資本、ROE×payout=(純益/自己資本)×(DPS/EPS)。net_income≒EPS×株数 かつ
    配当総額≒DPS×株数 なら一致する。乖離は per-share と総額の不整合/株数ズレを検出（品質監査）。
    判定不能（いずれかが ok でない）は NULL。
    """
    if not all(status.get(k) == "ok" for k in ("doe", "roe", "payout_ratio")):
        return None
    if doe is None or roe is None or payout is None:
        return None
    expected = roe * payout
    denom = max(abs(doe), abs(expected), 1e-9)
    return 1 if abs(doe - expected) / denom <= IDENTITY_TOL else 0


def build_grades(conn, codes: list[str]) -> dict:
    """claim別グレード＋identity_ok を確定（全指標導出の後＝最終出口）。"""
    now = datetime.now().isoformat(timespec="seconds")
    n = 0
    dist: dict[str, dict[str, int]] = {g: {} for g in _GRADE_CLAIMS}
    id_counts = {"ok": 0, "mismatch": 0, "na": 0}
    for code in codes:
        row = conn.execute(
            "SELECT status_json, doe, roe, payout_ratio FROM computed_metrics WHERE code=?",
            (code,),
        ).fetchone()
        if not row:
            continue
        status = json.loads(row[0]) if row[0] else {}
        grades = {g: _grade_claim(status, s["core"], s["extra"]) for g, s in _GRADE_CLAIMS.items()}
        iok = _identity_ok(row[1], row[2], row[3], status)
        conn.execute(
            "UPDATE computed_metrics SET grade_dividend=?, grade_valuation=?, grade_health=?, "
            "grade_capital=?, identity_ok=?, fin_computed_at=? WHERE code=?",
            (grades["grade_dividend"], grades["grade_valuation"], grades["grade_health"],
             grades["grade_capital"], iok, now, code),
        )
        n += 1
        for g, v in grades.items():
            dist[g][v] = dist[g].get(v, 0) + 1
        id_counts["na" if iok is None else "ok" if iok == 1 else "mismatch"] += 1
    conn.commit()
    return {"rows": n, "dist": dist, "identity": id_counts}


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
