"""導出層: 前段テーブル → computed_metrics（唯一の出口）。

Phase3-a はストリーク（連続増配/非減配・打ち切り・override昇格・N+）を担当。
- 機械計算は dividend_annual の **confidence!='review'**（単位整合が取れた系列）から。
- result_overrides（zai公表）は**昇格のみ**（機械<公表のとき）。promote時はN+解除。
- 由来(machine/override/censored)と status を JSON で computed_metrics に残す。
合成順序: 機械計算 → result_override（昇格） → N+ フォールバック（[charter]）。
"""
from __future__ import annotations

import json
from datetime import datetime

from .. import config
from .streaks import StreakOverride, compute_streaks


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
