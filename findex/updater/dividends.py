"""Category C 半年更新: 配当履歴
t.dividends を再取得し stock_fundamentals の Category C フィールドを更新する。
所要時間: 約30分（全銘柄、sequential）
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from pathlib import Path

import yfinance as yf

from findex.db import (
    get_db, upsert_fundamentals, get_latest_raw_json,
    upsert_score_with_raw, get_or_create_rule_version,
    bulk_insert_dividend_history,
)
from findex.scorer.engine import load_rules, select_rules, score_one
from findex.fetcher.dividends import _calc_metrics

DEFAULT_RULES = Path(__file__).parent.parent.parent / "rules.yaml"
WORKERS = 2
BURST_DELAY = 1.0


def _fetch_dividends_one(code: str):
    """1銘柄の配当履歴を取得して指標計算まで行う。生データも返す。"""
    divs = yf.Ticker(f"{code}.T").dividends
    metrics = _calc_metrics(divs)
    # 生データ: [(code, ex_date, amount), ...]
    raw_records = []
    if not divs.empty:
        divs.index = divs.index.tz_localize(None)
        for dt, amt in divs.items():
            if amt > 0:
                raw_records.append((code, dt.strftime("%Y-%m-%d"), float(amt)))
    return metrics, raw_records


def run_dividend_update(
    rules_path: Path = DEFAULT_RULES,
    codes: list[str] | None = None,
    force_all: bool = False,
    ttl_days: int = 180,
) -> dict:
    """
    半年更新メイン処理。

    フロー:
      1. div_updated_at が ttl_days 以上前の銘柄を選定
      2. t.dividends で配当履歴を再取得
      3. stock_fundamentals の Category C を更新
      4. raw_json を更新 → rescore → SQLite upsert
    """
    t0   = time.time()
    conn = get_db()

    if codes:
        target = codes
    elif force_all:
        rows   = conn.execute("SELECT code FROM stock_fundamentals").fetchall()
        target = [r[0] for r in rows]
    else:
        cutoff = (datetime.now() - timedelta(days=ttl_days)).isoformat()
        rows   = conn.execute(
            "SELECT code FROM stock_fundamentals "
            "WHERE div_updated_at IS NULL OR div_updated_at < ?",
            (cutoff,),
        ).fetchall()
        target = [r[0] for r in rows]

    if not target:
        print("配当更新: 対象銘柄なし", flush=True)
        return {"updated": 0, "skipped": 0, "failed": 0, "elapsed_sec": 0}

    print(f"配当履歴更新対象: {len(target)}銘柄", flush=True)

    rules    = load_rules(rules_path)
    rule_ver = get_or_create_rule_version(conn, rules_path)
    today    = date.today().isoformat()
    now_iso  = datetime.now().isoformat(timespec="seconds")
    raw_map  = get_latest_raw_json(conn, target)

    updated = failed = 0
    total = len(target)

    for batch_start in range(0, total, WORKERS):
        batch = target[batch_start:batch_start + WORKERS]

        results: dict[str, tuple | None] = {}
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(_fetch_dividends_one, code): code for code in batch}
            for fut in as_completed(futures):
                code = futures[fut]
                try:
                    results[code] = fut.result()  # (metrics, raw_records)
                except Exception:
                    results[code] = None

        # dividend_history に生データを一括保存
        all_raw: list[tuple] = []
        for code in batch:
            res = results.get(code)
            if res:
                _, raw_records = res
                all_raw.extend(raw_records)
        if all_raw:
            bulk_insert_dividend_history(conn, all_raw)

        for code in batch:
            res = results.get(code)
            metrics = res[0] if res else None
            if metrics is None:
                failed += 1
                continue

            div_data = {
                "annual_div":                         metrics.get("annual_dividend_per_share"),
                "consecutive_no_cut_years":           metrics["consecutive_no_cut_years"],
                "consecutive_dividend_growth_years":  metrics["consecutive_dividend_growth_years"],
                "dividend_growth_5y_cagr":            metrics["dividend_growth_5y_cagr"],
                "dividend_growth_10y_cagr":           metrics["dividend_growth_10y_cagr"],
                "dividend_reliability":               metrics["dividend_reliability"],
                "dividend_cut_count_20y":             metrics["dividend_cut_count_20y"],
                "div_updated_at":                     now_iso,
            }
            upsert_fundamentals(conn, code, div_data)

            raw = dict(raw_map.get(code, {}))
            raw.update({k: v for k, v in div_data.items() if k != "div_updated_at"})

            try:
                active  = select_rules(rules, raw.get("market_cap"), raw.get("sector"))
                score_j = score_one(raw, active)
                upsert_score_with_raw(
                    conn, code, today, rule_ver,
                    score_j, raw,
                    div_updated_at=now_iso,
                )
                updated += 1
            except Exception:
                failed += 1

        done = min(batch_start + WORKERS, total)
        if done % 200 < WORKERS or done == total:
            conn.commit()
            elapsed = time.time() - t0
            eta = elapsed / done * (total - done) if done > 0 else 0
            print(f"  [{done}/{total}] 経過{elapsed/60:.1f}分 残{eta/60:.1f}分", flush=True)

        time.sleep(BURST_DELAY)

    conn.commit()
    conn.close()
    elapsed = time.time() - t0
    print(f"配当更新完了: updated={updated} failed={failed} elapsed={elapsed/60:.1f}分", flush=True)
    return {"updated": updated, "failed": failed, "elapsed_sec": elapsed}
