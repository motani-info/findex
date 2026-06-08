"""raw_financials 取得: yfinance の生データをそのまま保存する（計算しない）"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

from findex.db import get_db, upsert_raw_financials
from findex.fetcher.fundamentals import _bs_value

WORKERS = 2
BURST_DELAY = 1.0


def _fetch_raw_one(code: str) -> dict | None:
    """1銘柄の生財務データを取得する。計算は一切しない。"""
    try:
        t = yf.Ticker(f"{code}.T")
        info = t.info
        fin = t.financials
        bs = t.balance_sheet

        # EPS（複数キーを優先順にトライ）
        eps = None
        for key in ("dilutedEPS", "trailingEps", "forwardEps"):
            v = info.get(key)
            if v and v > 0:
                eps = float(v)
                break

        # financials から CAGR計算用の始点・終点を取得
        diluted_eps_latest = diluted_eps_5y_ago = None
        diluted_eps_periods = 0
        try:
            eps_series = fin.loc["Diluted EPS"].dropna()
            if len(eps_series) >= 2:
                n = min(len(eps_series), 5)
                diluted_eps_latest = float(eps_series.iloc[0])
                diluted_eps_5y_ago = float(eps_series.iloc[n - 1])
                diluted_eps_periods = n
        except Exception:
            pass

        total_revenue_latest = total_revenue_5y_ago = None
        total_revenue_periods = 0
        try:
            rev_series = fin.loc["Total Revenue"].dropna()
            if len(rev_series) >= 2:
                n = min(len(rev_series), 5)
                total_revenue_latest = float(rev_series.iloc[0])
                total_revenue_5y_ago = float(rev_series.iloc[n - 1])
                total_revenue_periods = n
        except Exception:
            pass

        return {
            "eps": eps,
            "bps": float(info["bookValue"]) if info.get("bookValue") else None,
            "shares_outstanding": float(info["sharesOutstanding"]) if info.get("sharesOutstanding") else None,
            "roe": info.get("returnOnEquity"),
            "operating_margins": info.get("operatingMargins"),
            "payout_ratio": info.get("payoutRatio"),
            "free_cashflow": info.get("freeCashflow"),
            "operating_cashflow": info.get("operatingCashflow"),
            "capital_expenditures": info.get("capitalExpenditures"),
            "dividend_rate": info.get("dividendRate"),
            "market_cap": info.get("marketCap"),
            "beta": info.get("beta"),
            "total_assets": _bs_value(bs, "Total Assets"),
            "stockholders_equity": _bs_value(bs, "Stockholders Equity", "Common Stock Equity"),
            "current_assets": _bs_value(bs, "Current Assets"),
            "total_liabilities": _bs_value(bs, "Total Liabilities Net Minority Interest", "Total Liabilities"),
            "long_term_debt": _bs_value(bs, "Long Term Debt", "Long Term Debt And Capital Lease Obligation"),
            "short_term_debt": _bs_value(bs, "Current Debt", "Current Debt And Capital Lease Obligation", "Short Term Debt"),
            "retained_earnings": _bs_value(bs, "Retained Earnings"),
            "diluted_eps_latest": diluted_eps_latest,
            "total_revenue_latest": total_revenue_latest,
            "diluted_eps_5y_ago": diluted_eps_5y_ago,
            "total_revenue_5y_ago": total_revenue_5y_ago,
            "diluted_eps_periods": diluted_eps_periods,
            "total_revenue_periods": total_revenue_periods,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        }
    except Exception:
        return None


def run_fetch_raw(
    codes: list[str] | None = None,
    force_all: bool = False,
    ttl_days: int = 90,
) -> dict:
    """raw_financials 取得メイン処理。"""
    t0 = time.time()
    conn = get_db()

    if codes:
        target = codes
    elif force_all:
        rows = conn.execute("SELECT code FROM stocks").fetchall()
        target = [r[0] for r in rows]
    else:
        cutoff = (datetime.now() - timedelta(days=ttl_days)).isoformat()
        # fetched_at が古い or 未取得の銘柄
        rows = conn.execute(
            "SELECT s.code FROM stocks s LEFT JOIN raw_financials rf ON s.code = rf.code "
            "WHERE rf.fetched_at IS NULL OR rf.fetched_at < ?",
            (cutoff,),
        ).fetchall()
        target = [r[0] for r in rows]

    if not target:
        print("fetch --quarterly: 対象銘柄なし", flush=True)
        return {"updated": 0, "skipped": 0, "failed": 0, "elapsed_sec": 0}

    print(f"raw_financials取得対象: {len(target)}銘柄", flush=True)

    updated = failed = 0
    total = len(target)

    for batch_start in range(0, total, WORKERS):
        batch = target[batch_start:batch_start + WORKERS]
        results: dict[str, dict | None] = {}

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(_fetch_raw_one, code): code for code in batch}
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
            upsert_raw_financials(conn, code, data)
            updated += 1

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
    print(f"raw_financials取得完了: updated={updated} failed={failed} elapsed={elapsed/60:.1f}分", flush=True)
    return {"updated": updated, "skipped": 0, "failed": failed, "elapsed_sec": elapsed}
