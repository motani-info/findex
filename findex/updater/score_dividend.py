"""dividend_scores 計算: computed_metrics → scorer/engine → dividend_scores"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from findex.db import (
    get_db, get_computed_metrics, get_or_create_rule_version,
    upsert_dividend_score,
)
from findex.scorer.engine import load_rules, select_rules, score_one

DEFAULT_RULES = Path(__file__).parent.parent.parent / "rules.yaml"


def run_score_dividend(
    rules_path: Path = DEFAULT_RULES,
    codes: list[str] | None = None,
) -> dict:
    """配当スコアリングメイン処理。"""
    t0 = time.time()
    conn = get_db()

    cm_df = get_computed_metrics(conn, codes)
    if cm_df.empty:
        print("score --dividend: computed_metrics が空", flush=True)
        return {"scored": 0, "skipped": 0, "elapsed_sec": 0}

    rules = load_rules(rules_path)
    rule_ver = get_or_create_rule_version(conn, rules_path)
    today = date.today().isoformat()

    # stocks テーブルから market_cap と sector を取得（ルール選択用）
    stock_rows = conn.execute("SELECT code, market, sector FROM stocks").fetchall()
    stock_map = {r[0]: {"market": r[1], "sector": r[2]} for r in stock_rows}

    scored = skipped = 0
    for _, row in cm_df.iterrows():
        code = row["code"]
        stock_info = stock_map.get(code, {})

        # computed_metrics → scorer への入力辞書を構築
        raw_input = {}
        for col in cm_df.columns:
            if col != "code" and row[col] is not None:
                raw_input[col] = row[col]
        # market_cap for rule selection
        raw_input.setdefault("market_cap", row.get("current_market_cap"))
        raw_input["sector"] = stock_info.get("sector")

        active_rules = select_rules(
            rules, raw_input.get("market_cap"), raw_input.get("sector")
        )
        score_result = score_one(raw_input, active_rules)
        total = score_result["total"]

        # breakdown: 個別スコアをカラム名にマッピング
        breakdown = {}
        for field, val in score_result["raw"].items():
            breakdown[field] = val

        upsert_dividend_score(conn, code, today, rule_ver, total, breakdown)
        scored += 1

        if scored % 500 == 0:
            conn.commit()
            print(f"  [{scored}/{len(cm_df)}]", flush=True)

    conn.commit()
    conn.close()
    elapsed = time.time() - t0
    print(f"配当スコアリング完了: scored={scored} elapsed={elapsed:.1f}s", flush=True)
    return {"scored": scored, "skipped": skipped, "elapsed_sec": elapsed}
