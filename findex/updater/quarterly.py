"""Category B 四半期更新: 財務諸表（決算発表銘柄のみ）
t.financials + t.balance_sheet を再取得し、
stock_fundamentals と raw_json の Category B フィールドを更新する。
所要時間: 約10〜20分（決算銘柄 ≒ 全体の1/4）
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd

from findex.db import (
    get_db, upsert_fundamentals, get_latest_raw_json,
    upsert_score_with_raw, get_or_create_rule_version,
)
from findex.scorer.engine import load_rules, select_rules, score_one
from findex.fetcher.fundamentals import (
    _safe, _equity_ratio, _debt_to_equity, _net_cash_per,
    _mix_coefficient, _calc_revenue_cagr, _calc_eps_cagr,
    _fcf_payout_coverage,
)
from findex.fetcher.roic import _calc_roic_wacc, _calc_retained_earnings_div_ratio

DEFAULT_RULES = Path(__file__).parent.parent.parent / "rules.yaml"
WORKERS = 2    # 銘柄間並列数（4以上で401多発のため2が上限）
BURST_DELAY = 1.0  # バースト後の待機（秒）


def _fetch_financials_one(code: str) -> dict | None:
    """1銘柄の Category B データを取得する。"""
    try:
        t    = yf.Ticker(f"{code}.T")
        info = t.info
        fin  = t.financials
        bs   = t.balance_sheet

        # EPS / BPS（スコア計算に使う基準値）
        eps = None
        for key in ("dilutedEPS", "trailingEps", "forwardEps"):
            v = info.get(key)
            if v and v > 0:
                eps = float(v)
                break
        bps = info.get("bookValue")

        shares = info.get("sharesOutstanding")

        # ネットキャッシュ（net_cash_per 計算用）
        from findex.fetcher.fundamentals import _bs_value
        current_assets    = _bs_value(bs, "Current Assets")
        total_liabilities = _bs_value(bs, "Total Liabilities Net Minority Interest", "Total Liabilities")
        net_cash = (current_assets - total_liabilities) if (current_assets and total_liabilities) else None

        return {
            "eps":             eps,
            "bps":             float(bps) if bps else None,
            "shares":          float(shares) if shares else None,
            "net_cash":        net_cash,
            "equity_ratio":    _equity_ratio(bs),
            "debt_to_equity":  _debt_to_equity(bs),
            "roe":             _safe(info, "returnOnEquity"),
            "operating_margin": _safe(info, "operatingMargins"),
            "eps_growth_5y":   _calc_eps_cagr(fin),
            "revenue_growth_5y_cagr": _calc_revenue_cagr(fin),
            "roic_minus_wacc": _calc_roic_wacc(info, fin, bs),
            "fcf_payout_coverage": _fcf_payout_coverage(info),
            "retained_earnings_div_ratio": _calc_retained_earnings_div_ratio(info, bs),
            "payout_ratio":    _safe(info, "payoutRatio"),
        }
    except Exception:
        return None


def run_quarterly_update(
    rules_path: Path = DEFAULT_RULES,
    codes: list[str] | None = None,
    force_all: bool = False,
    ttl_days: int = 90,
) -> dict:
    """
    四半期更新メイン処理。

    対象銘柄:
      - codes 指定がある場合はそれのみ
      - force_all=True なら全銘柄
      - デフォルトは fin_updated_at が ttl_days 以上前の銘柄

    フロー:
      1. 対象銘柄を選定
      2. t.financials + t.balance_sheet を取得
      3. stock_fundamentals を更新（Category B）
      4. raw_json の Category B を上書き → rescore → SQLite upsert
    """
    t0   = time.time()
    conn = get_db()

    # 対象銘柄の選定
    if codes:
        target = codes
    elif force_all:
        rows   = conn.execute("SELECT code FROM stock_fundamentals").fetchall()
        target = [r[0] for r in rows]
    else:
        cutoff = (datetime.now() - timedelta(days=ttl_days)).isoformat()
        rows   = conn.execute(
            "SELECT code FROM stock_fundamentals "
            "WHERE fin_updated_at IS NULL OR fin_updated_at < ?",
            (cutoff,),
        ).fetchall()
        target = [r[0] for r in rows]

    if not target:
        print("四半期更新: 対象銘柄なし", flush=True)
        return {"updated": 0, "skipped": 0, "failed": 0, "elapsed_sec": 0}

    print(f"四半期更新対象: {len(target)}銘柄", flush=True)

    rules    = load_rules(rules_path)
    rule_ver = get_or_create_rule_version(conn, rules_path)
    today    = date.today().isoformat()
    now_iso  = datetime.now().isoformat(timespec="seconds")
    raw_map  = get_latest_raw_json(conn, target)

    updated = skipped = failed = 0
    total = len(target)

    # 2銘柄ずつバースト取得 → BURST_DELAY 待機
    for batch_start in range(0, total, WORKERS):
        batch = target[batch_start:batch_start + WORKERS]

        results: dict[str, dict | None] = {}
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(_fetch_financials_one, code): code for code in batch}
            for fut in as_completed(futures):
                code = futures[fut]
                try:
                    results[code] = fut.result()
                except Exception:
                    results[code] = None

        for code in batch:
            data = results.get(code)
            if data is None:
                failed += 1
                continue

            upsert_fundamentals(conn, code, {**data, "fin_updated_at": now_iso})

            raw = dict(raw_map.get(code, {}))
            raw.update(data)
            try:
                active  = select_rules(rules, raw.get("market_cap"), raw.get("sector"))
                score_j = score_one(raw, active)
                upsert_score_with_raw(
                    conn, code, today, rule_ver,
                    score_j, raw,
                    fin_updated_at=now_iso,
                )
                updated += 1
            except Exception:
                failed += 1

        done = min(batch_start + WORKERS, total)
        if done % 100 < WORKERS or done == total:
            conn.commit()
            elapsed = time.time() - t0
            eta = elapsed / done * (total - done) if done > 0 else 0
            print(f"  [{done}/{total}] 経過{elapsed/60:.1f}分 残{eta/60:.1f}分", flush=True)

        time.sleep(BURST_DELAY)

    conn.commit()
    conn.close()
    elapsed = time.time() - t0
    print(f"四半期更新完了: updated={updated} failed={failed} elapsed={elapsed/60:.1f}分", flush=True)
    return {"updated": updated, "skipped": skipped, "failed": failed, "elapsed_sec": elapsed}
