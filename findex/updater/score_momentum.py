"""momentum_scores 計算: computed_metrics → momentum_scores"""
from __future__ import annotations

import time
from datetime import date

from findex.db import get_db, get_computed_metrics, upsert_momentum_score
from findex.momentum import MOMENTUM_RULES, MAX_WEIGHTED, _score_one


# フィールドマッピング: computed_metrics列名 → momentum_scoreカラム名
FIELD_TO_COL = {
    "rel_ret_3m": "rel_ret_3m",
    "rel_ret_12m": "rel_ret_12m",
    "hi52_ratio": "hi52_ratio",
    "revenue_growth_5y_cagr": "rev_growth",
    "eps_growth_5y": "eps_growth",
    "roe": "roe",  # stock_fundamentals経由
    "operating_margin": "operating_margin",  # 同上
    "vol_ratio": "vol_ratio",
}

# computed_metrics → momentum field名マッピング
CM_TO_MOMENTUM = {
    "rel_ret_3m": "rel_ret_3m",
    "rel_ret_12m": "rel_ret_12m",
    "hi52_ratio": "hi52_ratio",
    "revenue_growth_5y_cagr": "rev_growth",
    "eps_growth_5y": "eps_growth",
}


def run_score_momentum(codes: list[str] | None = None) -> dict:
    """モメンタムスコアリングメイン処理。"""
    t0 = time.time()
    conn = get_db()

    cm_df = get_computed_metrics(conn, codes)
    if cm_df.empty:
        print("score --momentum: computed_metrics が空", flush=True)
        return {"scored": 0, "skipped": 0, "elapsed_sec": 0}

    today = date.today().isoformat()
    scored = skipped = 0

    for _, row in cm_df.iterrows():
        code = row["code"]

        # computed_metrics → momentum input fields（全て computed_metrics から取得）
        fields = {
            "rel_ret_3m":      row.get("rel_ret_3m"),
            "rel_ret_12m":     row.get("rel_ret_12m"),
            "hi52_ratio":      row.get("hi52_ratio"),
            "rev_growth":      row.get("revenue_growth_5y_cagr"),
            "eps_growth":      row.get("eps_growth_5y"),
            "roe":             row.get("roe"),
            "operating_margin": row.get("operating_margin"),
            "vol_ratio":       None,
        }

        # スコア計算
        weighted_sum = 0.0
        breakdown = {}
        for rule in MOMENTUM_RULES:
            s = _score_one(fields.get(rule["field"]), rule)
            weighted_sum += s * rule["weight"]
            breakdown[rule["field"]] = round(s, 2)

        total = round(weighted_sum / MAX_WEIGHTED * 100, 2)
        upsert_momentum_score(conn, code, today, total, breakdown)
        scored += 1

        if scored % 500 == 0:
            conn.commit()
            print(f"  [{scored}/{len(cm_df)}]", flush=True)

    conn.commit()
    conn.close()
    elapsed = time.time() - t0
    print(f"モメンタムスコアリング完了: scored={scored} elapsed={elapsed:.1f}s", flush=True)
    return {"scored": scored, "skipped": skipped, "elapsed_sec": elapsed}
