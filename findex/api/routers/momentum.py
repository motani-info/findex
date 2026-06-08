"""モメンタムスコアAPI — momentum_scores テーブルを SELECT するだけ"""
from fastapi import APIRouter
from typing import Optional
from findex.api.db import get_conn

router = APIRouter(prefix="/api/momentum", tags=["momentum"])


@router.get("/rank")
def momentum_rank(
    top: int = 30,
    market: Optional[str] = None,
    sector: Optional[str] = None,
    min_div_score: Optional[float] = None,
    large_cap: bool = False,
    mid_cap: bool = False,
    small_cap: bool = False,
):
    """モメンタムランキング。momentum_scores テーブルを参照。計算なし。"""
    where = [
        "ms.scored_at = (SELECT MAX(scored_at) FROM momentum_scores)",
    ]
    params: list = []
    joins = [
        "JOIN stocks st ON ms.code = st.code",
        "LEFT JOIN stock_fundamentals sf ON ms.code = sf.code",
        "LEFT JOIN computed_metrics cm ON ms.code = cm.code",
    ]

    if market:
        where.append("st.market = ?")
        params.append(market)
    if sector:
        where.append("st.sector LIKE ?")
        params.append(f"%{sector}%")
    if large_cap:
        where.append("sf.market_cap >= 500000000000")
    elif mid_cap:
        where.append("sf.market_cap >= 100000000000 AND sf.market_cap < 500000000000")
    elif small_cap:
        where.append("sf.market_cap < 100000000000")
    if min_div_score is not None:
        joins.append(
            "LEFT JOIN (SELECT code, total_score FROM dividend_scores "
            "WHERE scored_at = (SELECT MAX(scored_at) FROM dividend_scores)) ds ON ms.code = ds.code"
        )
        where.append("ds.total_score >= ?")
        params.append(min_div_score)

    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT ms.code, st.name, st.sector,
                   ms.total_score, ms.scored_at,
                   ms.s_rel_ret_3m, ms.s_rel_ret_12m, ms.s_hi52_ratio,
                   ms.s_rev_growth, ms.s_eps_growth, ms.s_roe, ms.s_operating_margin,
                   sf.market_cap, sf.revenue_growth_5y_cagr, sf.eps_growth_5y,
                   cm.ret_3m, cm.ret_12m, cm.rel_ret_3m, cm.rel_ret_12m, cm.hi52_ratio
            FROM momentum_scores ms
            {" ".join(joins)}
            WHERE {" AND ".join(where)}
            ORDER BY ms.total_score DESC
            LIMIT ?
        """, [*params, top]).fetchall()

    result = []
    for r in rows:
        code, name, sector_val = r[0], r[1], r[2]
        total, scored_at = r[3], r[4]
        s_3m, s_12m, s_hi52, s_rev, s_eps, s_roe, s_op = r[5], r[6], r[7], r[8], r[9], r[10], r[11]
        mc, rev_growth, eps_growth = r[12], r[13], r[14]
        cm_ret_3m, cm_ret_12m, cm_rel_3m, cm_rel_12m, cm_hi52 = r[15], r[16], r[17], r[18], r[19]

        result.append({
            "code":           code,
            "name":           name,
            "sector":         sector_val,
            "momentum_score": total,
            "scored_at":      scored_at[:10] if scored_at else None,
            "ret_12m":        round(cm_ret_12m * 100, 1) if cm_ret_12m is not None else None,
            "ret_3m":         round(cm_ret_3m * 100, 1) if cm_ret_3m is not None else None,
            "rel_ret_12m":    round(cm_rel_12m * 100, 1) if cm_rel_12m is not None else None,
            "rel_ret_3m":     round(cm_rel_3m * 100, 1) if cm_rel_3m is not None else None,
            "hi52_ratio":     round(cm_hi52 * 100) if cm_hi52 is not None else None,
            "rev_growth":     round(rev_growth * 100, 1) if rev_growth else None,
            "eps_growth":     round(eps_growth * 100, 1) if eps_growth else None,
            "market_cap":     mc,
            "breakdown": {
                "rel_ret_3m":       s_3m,
                "rel_ret_12m":      s_12m,
                "hi52_ratio":       s_hi52,
                "rev_growth":       s_rev,
                "eps_growth":       s_eps,
                "roe":              s_roe,
                "operating_margin": s_op,
            },
        })

    return {"items": result, "total": len(result)}


@router.get("/check/{code}")
def momentum_check(code: str):
    """単一銘柄のモメンタムスコア詳細。momentum_scores テーブルから取得。"""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT ms.*, st.name, st.sector,
                   cm.ret_3m, cm.ret_12m, cm.rel_ret_3m, cm.rel_ret_12m,
                   cm.hi52_ratio, cm.revenue_growth_5y_cagr, cm.eps_growth_5y,
                   cm.current_market_cap
            FROM momentum_scores ms
            JOIN stocks st ON ms.code = st.code
            LEFT JOIN computed_metrics cm ON ms.code = cm.code
            WHERE ms.code = ?
            ORDER BY ms.scored_at DESC LIMIT 1
        """, (code,)).fetchone()

    if not row:
        return {"error": "not found"}

    with get_conn() as conn:
        desc = conn.execute(
            "SELECT ms.*, st.name, st.sector, "
            "cm.ret_3m, cm.ret_12m, cm.rel_ret_3m, cm.rel_ret_12m, "
            "cm.hi52_ratio, cm.revenue_growth_5y_cagr, cm.eps_growth_5y, cm.current_market_cap "
            "FROM momentum_scores ms JOIN stocks st ON ms.code = st.code "
            "LEFT JOIN computed_metrics cm ON ms.code = cm.code LIMIT 0"
        ).description
        div_row = conn.execute(
            "SELECT total_score FROM dividend_scores WHERE code=? ORDER BY scored_at DESC LIMIT 1",
            (code,)
        ).fetchone()

    cols = [d[0] for d in desc]
    data = dict(zip(cols, row))

    breakdown = {k.removeprefix("s_"): v for k, v in data.items()
                 if k.startswith("s_") and v is not None}

    return {
        "code":           data["code"],
        "name":           data["name"],
        "sector":         data["sector"],
        "momentum_score": data["total_score"],
        "scored_at":      data["scored_at"],
        "div_score":      div_row[0] if div_row else None,
        "market_cap":     data.get("current_market_cap"),
        "fields": {
            "ret_12m":    round(data["ret_12m"] * 100, 1) if data.get("ret_12m") is not None else None,
            "ret_3m":     round(data["ret_3m"] * 100, 1) if data.get("ret_3m") is not None else None,
            "hi52_ratio": round(data["hi52_ratio"] * 100) if data.get("hi52_ratio") is not None else None,
            "rev_growth": round(data["revenue_growth_5y_cagr"] * 100, 1) if data.get("revenue_growth_5y_cagr") else None,
            "eps_growth": round(data["eps_growth_5y"] * 100, 1) if data.get("eps_growth_5y") else None,
        },
        "breakdown":      breakdown,
    }
