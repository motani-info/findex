"""配当スコアリングバッチ: stock_fundamentals → dividend_scores テーブル書き込み

既存の daily update で計算済みの raw_json を入力として、
dividend_scores テーブルに個別スコアをカラム展開して保存する。

将来的には computed_metrics テーブルが入力元になる。
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from findex.db import (
    get_db, get_fundamentals, get_or_create_rule_version,
    upsert_dividend_score, bulk_insert_price_history,
)
from findex.scorer.engine import load_rules, select_rules, score_one
from findex.updater.daily import _calc_price_fields, _safe_val

DEFAULT_RULES = Path(__file__).parent.parent.parent / "rules.yaml"


def run_dividend_scoring(
    rules_path: Path = DEFAULT_RULES,
    codes: list[str] | None = None,
    scored_at: str | None = None,
) -> dict:
    """
    配当スコアリングバッチ。

    stock_fundamentals + 最新price_history → score_one() → dividend_scores upsert

    Returns:
        {"scored": int, "skipped": int, "failed": int, "elapsed_sec": float}
    """
    t0 = time.time()
    conn = get_db()
    rules = load_rules(rules_path)
    rule_ver = get_or_create_rule_version(conn, rules_path)
    today = scored_at or date.today().isoformat()

    # 対象銘柄
    fund_df = get_fundamentals(conn, codes)
    if fund_df.empty:
        print("対象銘柄なし（stock_fundamentals が空）", flush=True)
        conn.close()
        return {"scored": 0, "skipped": 0, "failed": 0, "elapsed_sec": 0}

    # 最新株価を取得（price_history から各銘柄の直近値）
    all_codes = fund_df["code"].tolist()
    placeholders = ",".join(["?"] * len(all_codes))
    price_rows = conn.execute(f"""
        SELECT code, close FROM price_history
        WHERE (code, date) IN (
            SELECT code, MAX(date) FROM price_history
            WHERE code IN ({placeholders})
            GROUP BY code
        )
    """, all_codes).fetchall()
    price_map = {r[0]: r[1] for r in price_rows}

    scored = skipped = failed = 0

    for _, row in fund_df.iterrows():
        code = str(row["code"])
        fund = row.to_dict()
        close = price_map.get(code)

        # 価格由来指標を計算
        raw: dict = {}
        if close:
            raw.update(_calc_price_fields(close, fund))

        # stock_fundamentals から指標を補完
        for col in [
            "equity_ratio", "debt_to_equity", "roe", "operating_margin",
            "eps_growth_5y", "revenue_growth_5y_cagr", "roic_minus_wacc",
            "fcf_payout_coverage", "retained_earnings_div_ratio", "payout_ratio",
            "consecutive_no_cut_years", "consecutive_dividend_growth_years",
            "dividend_growth_5y_cagr", "dividend_growth_10y_cagr",
            "dividend_reliability", "annual_div", "market_cap",
        ]:
            v = fund.get(col)
            if v is not None:
                raw.setdefault(col, v)

        # sector情報を取得
        sector_row = conn.execute(
            "SELECT sector FROM stocks WHERE code = ?", (code,)
        ).fetchone()
        sector = sector_row[0] if sector_row else None

        try:
            active = select_rules(rules, raw.get("market_cap"), sector)
            score_j = score_one(raw, active)
            upsert_dividend_score(
                conn, code, today, rule_ver,
                score_j["total"],
                score_j["raw"],  # {field_name: 0〜10}
            )
            scored += 1
        except Exception:
            failed += 1

    conn.commit()
    conn.close()

    elapsed = time.time() - t0
    print(
        f"配当スコアリング完了: scored={scored} skipped={skipped} "
        f"failed={failed} elapsed={elapsed:.1f}s",
        flush=True,
    )
    return {"scored": scored, "skipped": skipped, "failed": failed, "elapsed_sec": elapsed}
