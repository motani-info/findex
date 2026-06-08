from fastapi import APIRouter
from findex.api.db import get_conn

router = APIRouter(prefix="/api/stock", tags=["stock"])


@router.get("/search")
def search(q: str = "", limit: int = 20):
    if not q:
        return {"items": []}
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ds.code, st.name, st.sector, st.market, ds.total_score,
                   cm.div_yield, cm.current_market_cap AS market_cap
            FROM dividend_scores ds
            JOIN stocks st ON ds.code = st.code
            LEFT JOIN computed_metrics cm ON ds.code = cm.code
            WHERE (ds.code LIKE ? OR st.name LIKE ?)
              AND ds.scored_at = (SELECT MAX(scored_at) FROM dividend_scores WHERE code = ds.code)
            ORDER BY ds.total_score DESC
            LIMIT ?
        """, (f"%{q}%", f"%{q}%", limit)).fetchall()

    return {"items": [
        {
            "code":       r["code"],
            "name":       r["name"],
            "sector":     r["sector"],
            "market":     r["market"],
            "score":      r["total_score"],
            "div_yield":  round(r["div_yield"] * 100, 2) if r["div_yield"] else None,
            "market_cap": r["market_cap"],
        }
        for r in rows
    ]}


@router.get("/price-history/{code}")
def price_history(code: str):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT date, close FROM price_history
            WHERE code=? ORDER BY date ASC LIMIT 500
        """, (code,)).fetchall()
    return {"code": code, "history": [{"date": r["date"], "close": r["close"]} for r in rows]}


@router.get("/dividend-history/{code}")
def dividend_history(code: str):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT ex_date, amount FROM dividend_history
            WHERE code=? ORDER BY ex_date ASC
        """, (code,)).fetchall()
    return {"code": code, "history": [{"date": r["ex_date"], "amount": r["amount"]} for r in rows]}


@router.get("/sectors")
def sectors():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL ORDER BY sector
        """).fetchall()
    return {"sectors": [r["sector"] for r in rows]}


@router.get("/markets")
def markets():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT market FROM stocks WHERE market IS NOT NULL ORDER BY market
        """).fetchall()
    return {"markets": [r["market"] for r in rows]}
