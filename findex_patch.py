"""既存キャッシュに新フィールドをパッチしつつ、multiprocessingで高速化。
プロセス分離でyfinanceセッションが独立 → 401エラーを回避しながら並列取得。

新フィールド:
  fundamentals: fcf_payout_coverage, revenue_growth_5y_cagr, eps_growth_5y(再計算)
  dividends:    dividend_reliability, dividend_cut_count_20y, dividend_growth_10y_cagr
"""
import time
import multiprocessing as mp
from datetime import datetime
from pathlib import Path

import yfinance as yf

from findex.cache import load_cache, save_cache
from findex.fetcher.dividends import _calc_metrics
from findex.fetcher.fundamentals import (
    _fcf_payout_coverage, _calc_revenue_cagr, _calc_eps_cagr,
)

DELAY    = 0.3   # ワーカーごとの待機（プロセス分離のため0.3sで十分）
WORKERS  = 2     # 並列プロセス数（4×0.3s = 実効0.075s/銘柄）
TTL_DAYS = 7

NEW_FUND_FIELDS = {"fcf_payout_coverage", "revenue_growth_5y_cagr", "eps_growth_5y"}
NEW_DIV_FIELDS  = {"dividend_reliability", "dividend_cut_count_20y", "dividend_growth_10y_cagr"}


def _needs_patch(code: str) -> tuple[bool, bool]:
    f = load_cache("fundamentals", code, ttl_days=TTL_DAYS)
    d = load_cache("dividends",    code, ttl_days=TTL_DAYS)
    return (
        f is None or not NEW_FUND_FIELDS.issubset(f.keys()),
        d is None or not NEW_DIV_FIELDS.issubset(d.keys()),
    )


def _worker(args):
    """各プロセスで実行: 1銘柄をパッチする"""
    code, fund_patch, div_patch = args
    if not fund_patch and not div_patch:
        return code, True

    try:
        t = yf.Ticker(f"{code}.T")

        if fund_patch:
            info       = t.info
            financials = t.financials
            existing   = load_cache("fundamentals", code, ttl_days=TTL_DAYS) or {}
            existing.update({
                "fcf_payout_coverage":    _fcf_payout_coverage(info),
                "revenue_growth_5y_cagr": _calc_revenue_cagr(financials),
                "eps_growth_5y":          _calc_eps_cagr(financials),
            })
            save_cache("fundamentals", code, existing)

        if div_patch:
            metrics  = _calc_metrics(t.dividends)
            existing = load_cache("dividends", code, ttl_days=TTL_DAYS) or {}
            existing.update({
                "dividend_reliability":             metrics["dividend_reliability"],
                "dividend_cut_count_20y":           metrics["dividend_cut_count_20y"],
                "dividend_growth_10y_cagr":         metrics["dividend_growth_10y_cagr"],
                "dividend_growth_5y_cagr":          metrics["dividend_growth_5y_cagr"],
                "consecutive_no_cut_years":         metrics["consecutive_no_cut_years"],
                "consecutive_dividend_growth_years": metrics["consecutive_dividend_growth_years"],
            })
            save_cache("dividends", code, existing)

        time.sleep(DELAY)
        return code, True
    except Exception:
        time.sleep(DELAY)
        return code, False


def main():
    t0 = time.time()
    today = datetime.now().strftime("%Y%m%d")

    from findex.fetcher.master import fetch_stock_master
    master = fetch_stock_master()
    master = master[~master['market'].str.contains('ETF|ETN|REIT|インフラ', na=False)]
    codes  = master['code'].tolist()
    total  = len(codes)

    needs = [(c, *_needs_patch(c)) for c in codes]
    patch_list = [(c, f, d) for c, f, d in needs if f or d]
    n_patch = len(patch_list)
    print(f"全銘柄: {total}件  パッチ対象: {n_patch}件  スキップ: {total-n_patch}件", flush=True)
    eta_min = n_patch * DELAY / WORKERS / 60
    print(f"並列: {WORKERS}プロセス  推定時間: {eta_min:.0f}〜{eta_min*1.5:.0f}分", flush=True)

    # multiprocessing Pool
    done = 0
    failed = 0
    with mp.Pool(processes=WORKERS) as pool:
        for code, ok in pool.imap_unordered(_worker, patch_list, chunksize=1):
            done += 1
            if not ok:
                failed += 1
            if done % 200 == 0 or done == n_patch:
                elapsed = time.time() - t0
                eta = elapsed / done * (n_patch - done) if done < n_patch else 0
                print(
                    f"  [{done}/{n_patch}] {done/n_patch*100:.0f}%"
                    f"  経過{elapsed/60:.1f}分  残{eta/60:.1f}分"
                    f"  失敗{failed}件",
                    flush=True,
                )

    print(f"\nパッチ完了: {(time.time()-t0)/60:.1f}分  失敗: {failed}件", flush=True)

    # 全件スコアリング
    print("スコアリング中...", flush=True)
    from findex.fetcher.fetch_all import fetch_all
    from findex.scorer.engine import load_rules, score
    from findex.output.display import save_csv

    all_data = fetch_all(codes, delay=0, refresh=False)
    df       = master.merge(all_data, on='code', how='left')
    rules    = load_rules(Path('rules.yaml'))
    ranked   = score(df, rules)

    outpath = f'findex_all_{today}.csv'
    save_csv(ranked, outpath)
    save_csv(ranked, '/tmp/findex_all.csv')

    elapsed = time.time() - t0
    zero    = (ranked.total_score == 0).sum()
    print(f"\n=== 完了 ===")
    print(f"処理時間: {elapsed:.0f}秒 ({elapsed/60:.1f}分) | 対象: {total}件 | スコア0: {zero}件")
    print(f"スコア分布: min={ranked.total_score.min():.1f}  mean={ranked.total_score.mean():.1f}  max={ranked.total_score.max():.1f}")
    print()
    print("=== TOP 20 ===")
    print(ranked[['code','name','sector','total_score']].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
