"""全市場スキャン（高速版）
Level 1: 銘柄内並列  - info確立後、financials/bs/dividendsを同時フェッチ
Level 2: 銘柄間並列  - multiprocessing.Pool でN銘柄を同時処理
Level 3: パイプライン - fetch→score→writeを重ねて実行（Queueで接続）
"""
import time
import multiprocessing as mp
from datetime import datetime
from pathlib import Path

import pandas as pd

from findex.fetcher.fetch_all import _all_cached, _fetch_one_all
from findex.cache import load_cache

WORKERS   = 4     # 並列プロセス数（CPUコア数 - 1 が目安）
DELAY     = 0.2   # ワーカーごとの待機
BATCH_SIZE = 50   # パイプラインのバッチサイズ
TTL_DAYS  = 7
SENTINEL  = None  # Queueの終了シグナル


# ─────────────────────────────────────────────
# Worker: フェッチ（Level 1+2）
# ─────────────────────────────────────────────
def _fetch_worker(code: str, refresh: bool) -> dict:
    """1銘柄をフェッチしてdictで返す（Poolのワーカー関数）"""
    if not refresh:
        hit = _all_cached(code)
        if hit:
            return {"code": code, **hit}
    try:
        data = _fetch_one_all(code)
        time.sleep(DELAY)
        return {"code": code, **data}
    except Exception:
        time.sleep(DELAY)
        return {"code": code}


def _fetch_worker_star(args):
    return _fetch_worker(*args)


# ─────────────────────────────────────────────
# Stage: フェッチャー（Level 2+3）
# ─────────────────────────────────────────────
def _fetcher_stage(codes: list[str], refresh: bool, out_q: mp.Queue, n_workers: int):
    """codes を n_workers 並列でフェッチし、BATCH_SIZE ごとに out_q へ送る"""
    args = [(c, refresh) for c in codes]
    batch = []
    with mp.Pool(processes=n_workers) as pool:
        for row in pool.imap_unordered(_fetch_worker_star, args, chunksize=1):
            batch.append(row)
            if len(batch) >= BATCH_SIZE:
                out_q.put(batch)
                batch = []
    if batch:
        out_q.put(batch)
    out_q.put(SENTINEL)  # 終了シグナル


# ─────────────────────────────────────────────
# Stage: スコアラー（Level 3）
# ─────────────────────────────────────────────
def _scorer_stage(master_df: pd.DataFrame, rules_path: str,
                  in_q: mp.Queue, out_q: mp.Queue):
    """バッチを受け取り、masterとmergeしてスコアリングして次へ渡す"""
    from findex.scorer.engine import load_rules, score
    rules = load_rules(rules_path)

    while True:
        batch = in_q.get()
        if batch is SENTINEL:
            out_q.put(SENTINEL)
            return
        df = master_df.merge(pd.DataFrame(batch), on='code', how='right')
        scored = score(df, rules)
        out_q.put(scored)


# ─────────────────────────────────────────────
# Stage: ライター（Level 3）
# ─────────────────────────────────────────────
def _writer_stage(in_q: mp.Queue, total: int, result_list: list):
    """スコア済みバッチを受け取り、集積する（ファイル書き込みはmainで）"""
    done = 0
    t0 = time.time()
    while True:
        batch_df = in_q.get()
        if batch_df is None:
            return
        result_list.append(batch_df)
        done += len(batch_df)
        elapsed = time.time() - t0
        eta = elapsed / done * (total - done) if done < total else 0
        print(
            f"  [{done}/{total}] {done/total*100:.0f}%"
            f"  経過{elapsed/60:.1f}分  残{eta/60:.1f}分",
            flush=True,
        )


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="キャッシュを無視して再取得")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--source", choices=["yfinance", "jquants"], default="yfinance",
                        help="データソース (default: yfinance)")
    args = parser.parse_args()

    t0    = time.time()
    today = datetime.now().strftime("%Y%m%d")

    from findex.fetcher.master import fetch_stock_master
    master = fetch_stock_master()
    master = master[~master['market'].str.contains('ETF|ETN|REIT|インフラ', na=False)]
    codes  = master['code'].tolist()
    total  = len(codes)

    # ── J-Quants モード ──────────────────────────────────────────
    if args.source == "jquants":
        from findex.settings import Settings
        from findex.fetcher.jquants import fetch_all_jquants
        from findex.scorer.engine import load_rules, score
        from findex.output.display import save_csv

        client   = Settings.load().get_jquants_client()
        all_data = fetch_all_jquants(codes, client, refresh=args.refresh)
        df       = master.merge(all_data, on='code', how='left')
        rules    = load_rules(Path('rules.yaml'))
        ranked   = score(df, rules)

        outpath = f'findex_all_{today}.csv'
        save_csv(ranked, outpath)
        save_csv(ranked, '/tmp/findex_all.csv')

        elapsed = time.time() - t0
        zero    = (ranked.total_score == 0).sum()
        print(f"\n=== 完了（J-Quants）===")
        print(f"処理時間: {elapsed:.0f}秒 ({elapsed/60:.1f}分) | {total}件 | スコア0: {zero}件")
        print(f"スコア分布: min={ranked.total_score.min():.1f}  mean={ranked.total_score.mean():.1f}  max={ranked.total_score.max():.1f}")
        print()
        print("=== TOP 20 ===")
        print(ranked[['code','name','sector','total_score']].head(20).to_string(index=False))
        return

    # ── yfinance モード（パイプライン）───────────────────────────
    cached = sum(1 for c in codes if not args.refresh and _all_cached(c) is not None)
    print(f"全銘柄: {total}件  キャッシュ済: {cached}件  新規取得: {total-cached}件", flush=True)
    eta = (total - cached) * DELAY / args.workers / 60
    print(f"並列: {args.workers}プロセス × Level1並列  推定: {eta:.0f}〜{eta*1.5:.0f}分", flush=True)

    # Queueを準備（Levelの間のバッファ）
    fetch_q = mp.Queue(maxsize=8)
    score_q = mp.Queue(maxsize=8)

    # パイプラインの各ステージをプロセスで起動
    fetcher = mp.Process(
        target=_fetcher_stage,
        args=(codes, args.refresh, fetch_q, args.workers),
        daemon=True,
    )
    scorer = mp.Process(
        target=_scorer_stage,
        args=(master, str(Path('rules.yaml').resolve()), fetch_q, score_q),
        daemon=True,
    )
    fetcher.start()
    scorer.start()

    # ライターはメインプロセスで実行（結果を直接収集）
    parts = []
    done  = 0
    while True:
        batch_df = score_q.get()
        if batch_df is None:
            break
        parts.append(batch_df)
        done += len(batch_df)
        elapsed = time.time() - t0
        eta_r = elapsed / done * (total - done) if done < total else 0
        print(
            f"  [{done}/{total}] {done/total*100:.0f}%"
            f"  経過{elapsed/60:.1f}分  残{eta_r/60:.1f}分",
            flush=True,
        )

    fetcher.join()
    scorer.join()

    # 全バッチを結合してソート
    from findex.output.display import save_csv
    ranked = pd.concat(parts, ignore_index=True).sort_values("total_score", ascending=False).reset_index(drop=True)

    outpath = f'findex_all_{today}.csv'
    save_csv(ranked, outpath)
    save_csv(ranked, '/tmp/findex_all.csv')

    elapsed = time.time() - t0
    zero    = (ranked.total_score == 0).sum()
    print(f"\n=== 完了 ===")
    print(f"処理時間: {elapsed:.0f}秒 ({elapsed/60:.1f}分) | {total}件 | スコア0: {zero}件")
    print(f"スコア分布: min={ranked.total_score.min():.1f}  mean={ranked.total_score.mean():.1f}  max={ranked.total_score.max():.1f}")
    print()
    print("=== TOP 20 ===")
    print(ranked[['code','name','sector','total_score']].head(20).to_string(index=False))


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)  # macOS/Windowsで安全なspawnモード
    main()
