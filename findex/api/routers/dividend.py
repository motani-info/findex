"""配当スコアAPI — dividend_scores テーブルを SELECT するだけ"""
from fastapi import APIRouter
from typing import Optional
from findex.api.db import get_conn

router = APIRouter(prefix="/api/dividend", tags=["dividend"])


@router.get("/rank")
def dividend_rank(
    top: int = 30,
    market: Optional[str] = None,
    sector: Optional[str] = None,
    min_yield: Optional[float] = None,
    max_per: Optional[float] = None,
    max_pbr: Optional[float] = None,
    min_no_cut: Optional[int] = None,
    min_cap: Optional[float] = None,
    max_cap: Optional[float] = None,
    large_cap: bool = False,
    mid_cap: bool = False,
    small_cap: bool = False,
):
    """配当スコアランキング。dividend_scores + computed_metrics を参照。"""
    # 時価総額区分は OR 条件でまとめる
    cap_conditions = []
    cap_params: list = []
    if large_cap:
        cap_conditions.append("cm.current_market_cap >= ?")
        cap_params.append(int(0.5 * 1e12))
    if mid_cap:
        cap_conditions.append("(cm.current_market_cap >= ? AND cm.current_market_cap < ?)")
        cap_params.extend([int(0.1 * 1e12), int(0.5 * 1e12)])
    if small_cap:
        cap_conditions.append("cm.current_market_cap < ?")
        cap_params.append(int(0.1 * 1e12))

    where = [
        "ds.scored_at = (SELECT MAX(scored_at) FROM dividend_scores)",
    ]
    params: list = []

    if market:
        where.append("st.market = ?")
        params.append(market)
    if sector:
        where.append("st.sector LIKE ?")
        params.append(f"%{sector}%")
    if cap_conditions:
        where.append(f"({' OR '.join(cap_conditions)})")
        params.extend(cap_params)
    elif min_cap is not None or max_cap is not None:
        if min_cap is not None:
            where.append("cm.current_market_cap >= ?")
            params.append(int(min_cap * 1e12))
        if max_cap is not None:
            where.append("cm.current_market_cap < ?")
            params.append(int(max_cap * 1e12))
    if min_no_cut is not None:
        where.append("cm.consecutive_no_cut_years >= ?")
        params.append(min_no_cut)
    if min_yield is not None:
        where.append("cm.div_yield >= ?")
        params.append(min_yield)
    if max_per is not None:
        where.append("(cm.per IS NULL OR cm.per <= ?)")
        params.append(max_per)
    if max_pbr is not None:
        where.append("(cm.pbr IS NULL OR cm.pbr <= ?)")
        params.append(max_pbr)

    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT ds.code, st.name, st.market, st.sector,
                   ds.total_score, ds.scored_at,
                   cm.roe, cm.operating_margin,
                   cm.equity_ratio, cm.payout_ratio, cm.current_market_cap,
                   cm.consecutive_no_cut_years, cm.consecutive_dividend_growth_years,
                   cm.per, cm.pbr, cm.div_yield
            FROM dividend_scores ds
            JOIN stocks st ON ds.code = st.code
            LEFT JOIN computed_metrics cm ON ds.code = cm.code
            WHERE {" AND ".join(where)}
            ORDER BY ds.total_score DESC
            LIMIT ?
        """, [*params, top]).fetchall()

    result = []
    for r in rows:
        code, name, mkt, sect, score, scored_at = r[0], r[1], r[2], r[3], r[4], r[5]
        roe, op_margin = r[6], r[7]
        eq_ratio, payout, mc = r[8], r[9], r[10]
        no_cut, div_growth = r[11], r[12]
        per, pbr, div_yield_raw = r[13], r[14], r[15]

        result.append({
            "code":         code,
            "name":         name,
            "market":       mkt,
            "sector":       sect,
            "score":        score,
            "updated_at":   scored_at[:10] if scored_at else None,
            "div_yield":    round(div_yield_raw * 100, 2) if div_yield_raw else None,
            "roe":          round(roe * 100, 2) if roe else None,
            "no_cut":       no_cut,
            "div_growth":   div_growth,
            "equity_ratio": round(eq_ratio * 100, 1) if eq_ratio else None,
            "market_cap":   mc,
            "op_margin":    round(op_margin * 100, 1) if op_margin else None,
            "payout_ratio": round(payout * 100, 1) if payout else None,
            "per":          round(per, 1) if per else None,
            "pbr":          round(pbr, 2) if pbr else None,
        })

    return {"items": result, "total": len(result)}


@router.get("/check/{code}")
def dividend_check(code: str):
    """単一銘柄の配当スコア詳細。dividend_scores テーブルから取得。"""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT ds.*, st.name, st.sector
            FROM dividend_scores ds
            JOIN stocks st ON ds.code = st.code
            WHERE ds.code = ?
            ORDER BY ds.scored_at DESC LIMIT 1
        """, (code,)).fetchone()

    if not row:
        return {"error": "not found"}

    # カラム名を取得
    with get_conn() as conn:
        desc = conn.execute(
            "SELECT ds.*, st.name, st.sector FROM dividend_scores ds "
            "JOIN stocks st ON ds.code = st.code LIMIT 0"
        ).description
    cols = [d[0] for d in desc]
    data = dict(zip(cols, row))

    # raw: computed_metrics + raw_financials からフロントが必要とする指標を構築
    with get_conn() as conn:
        cm = conn.execute(
            "SELECT * FROM computed_metrics WHERE code=?", (code,)
        ).fetchone()
        rf = conn.execute(
            "SELECT * FROM raw_financials WHERE code=?", (code,)
        ).fetchone()

    raw = {}
    if cm:
        cm_d = dict(cm)
        raw.update({
            "div_yield": cm_d.get("div_yield"),
            "per": cm_d.get("per"),
            "pbr": cm_d.get("pbr"),
            "mix_coefficient": cm_d.get("mix_coefficient"),
            "net_cash_per": cm_d.get("net_cash_per"),
            "equity_ratio": cm_d.get("equity_ratio"),
            "debt_to_equity": cm_d.get("debt_to_equity"),
            "eps_growth_5y": cm_d.get("eps_growth_5y"),
            "revenue_growth_5y_cagr": cm_d.get("revenue_growth_5y_cagr"),
            "fcf_payout_coverage": cm_d.get("fcf_payout_coverage"),
            "roic_minus_wacc": cm_d.get("roic_minus_wacc"),
            "retained_earnings_div_ratio": cm_d.get("retained_earnings_div_ratio"),
            "consecutive_no_cut_years": cm_d.get("consecutive_no_cut_years"),
            "consecutive_dividend_growth_years": cm_d.get("consecutive_dividend_growth_years"),
            "dividend_growth_5y_cagr": cm_d.get("dividend_growth_5y_cagr"),
            "dividend_growth_10y_cagr": cm_d.get("dividend_growth_10y_cagr"),
            "dividend_reliability": cm_d.get("dividend_reliability"),
            "dividend_cut_count_20y": cm_d.get("dividend_cut_count_20y"),
            "market_cap": cm_d.get("current_market_cap"),
        })
    if rf:
        rf_d = dict(rf)
        raw.update({
            "roe": rf_d.get("roe"),
            "operating_margin": rf_d.get("operating_margins"),
            "payout_ratio": rf_d.get("payout_ratio"),
        })

    # breakdown: s_ プレフィックスのカラムを抽出
    breakdown = {k.removeprefix("s_"): v for k, v in data.items()
                 if k.startswith("s_") and v is not None}

    return {
        "code":        data["code"],
        "name":        data["name"],
        "sector":      data["sector"],
        "total_score": data["total_score"],
        "scored_at":   data["scored_at"],
        "raw":         raw,
        "breakdown":   breakdown,
    }
