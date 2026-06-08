"""バックテストエンジン

現在のスコアでTOP-N銘柄を選択し、過去X年の株価でリターンを計算する。
制限: 「現在のスコアで選んだ銘柄の過去リターン」を検証する形式。
      厳密なバックテスト（過去時点のスコアで選択）ではない。
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf


DB_PATH = "/Users/motani/.findex/db/findex.db"
BENCHMARK = "^N225"  # 日経225


def _get_top_stocks(
    top: int,
    market: Optional[str],
    sector: Optional[str],
    min_yield: Optional[float],
    min_no_cut: Optional[int],
    min_cap: Optional[float],
    max_cap: Optional[float],
    max_per: Optional[float] = None,
    max_pbr: Optional[float] = None,
) -> list[dict]:
    """現在のスコアTOP-N銘柄を取得する（findex rank と同じロジック）"""
    conn = sqlite3.connect(DB_PATH)

    where_clauses = [
        "s.rowid IN (SELECT MAX(rowid) FROM scores GROUP BY code)",
        "s.total_score IS NOT NULL",
    ]
    if market:
        where_clauses.append(f"st.market LIKE '%{market}%'")
    if sector:
        where_clauses.append(f"st.sector LIKE '%{sector}%'")
    if min_cap is not None:
        where_clauses.append(f"json_extract(s.raw_json, '$.market_cap') >= {int(min_cap * 1e12)}")
    if max_cap is not None:
        where_clauses.append(f"json_extract(s.raw_json, '$.market_cap') < {int(max_cap * 1e12)}")
    if max_per is not None:
        where_clauses.append(f"json_extract(s.raw_json, '$.per') IS NOT NULL")
        where_clauses.append(f"json_extract(s.raw_json, '$.per') <= {max_per}")
    if max_pbr is not None:
        where_clauses.append(f"json_extract(s.raw_json, '$.pbr') IS NOT NULL")
        where_clauses.append(f"json_extract(s.raw_json, '$.pbr') <= {max_pbr}")

    where_sql = " AND ".join(where_clauses)

    rows = conn.execute(f"""
        SELECT s.code, st.name, s.total_score,
               json_extract(s.raw_json, '$.div_yield') as div_yield,
               json_extract(s.raw_json, '$.consecutive_no_cut_years') as no_cut,
               json_extract(s.raw_json, '$.market_cap') as market_cap,
               json_extract(s.raw_json, '$.per') as per
        FROM scores s
        JOIN stocks st ON s.code = st.code
        WHERE {where_sql}
        ORDER BY s.total_score DESC
    """).fetchall()
    conn.close()

    # Python側フィルタ
    filtered = []
    for r in rows:
        dy = r[3]
        nc = r[4]
        if min_yield is not None and (dy is None or dy < min_yield):
            continue
        if min_no_cut is not None and (nc is None or nc < min_no_cut):
            continue
        filtered.append({
            "code": r[0],
            "name": r[1],
            "score": r[2],
            "div_yield": dy,
            "no_cut": nc,
            "market_cap": r[5],
            "per": r[6],
        })

    return filtered[:top]


def _fetch_prices(tickers: list[str], years: float) -> pd.DataFrame:
    """yfinance で過去 years 年分の月次終値を取得する"""
    period = f"{int(years * 12)}mo" if years < 1 else f"{int(years)}y"
    raw = yf.download(
        tickers,
        period=period,
        interval="1mo",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        return pd.DataFrame()
    close = raw["Close"] if "Close" in raw.columns else raw
    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])
    return close


def run_backtest(
    top: int = 10,
    years: float = 3.0,
    market: Optional[str] = None,
    sector: Optional[str] = None,
    min_yield: Optional[float] = None,
    min_no_cut: Optional[int] = None,
    min_cap: Optional[float] = None,
    max_cap: Optional[float] = None,
    large_cap: bool = False,
    mid_cap: bool = False,
    small_cap: bool = False,
    max_per: Optional[float] = None,
    max_pbr: Optional[float] = None,
    out: Optional[str] = None,
) -> None:
    """バックテストを実行して結果を表示する"""
    import click

    # フラグ → min_cap / max_cap 変換
    if large_cap:
        min_cap = max(min_cap or 0, 0.5)
    if mid_cap:
        min_cap = max(min_cap or 0, 0.1)
        max_cap = min(max_cap or 999, 0.5)
    if small_cap:
        max_cap = min(max_cap or 999, 0.1)

    # ── Step 1: 対象銘柄を取得 ────────────────────────────────────
    click.echo(f"スコアTOP{top}を取得中...")
    stocks = _get_top_stocks(top, market, sector, min_yield, min_no_cut, min_cap, max_cap,
                             max_per=max_per, max_pbr=max_pbr)
    if not stocks:
        click.echo("条件に合う銘柄が見つかりません。")
        return

    click.echo(f"{len(stocks)}銘柄 × {years}年間の株価を取得中（日経225含む）...")

    # ── Step 2: 株価取得 ──────────────────────────────────────────
    codes  = [s["code"] for s in stocks]
    tickers_jp = [f"{c}.T" for c in codes]
    all_tickers = tickers_jp + [BENCHMARK]

    prices = _fetch_prices(all_tickers, years)
    if prices.empty:
        click.echo("株価データを取得できませんでした。")
        return

    # ── Step 3: リターン計算 ──────────────────────────────────────
    entry_date_str = prices.index[0].strftime("%Y-%m-%d")
    exit_date_str  = prices.index[-1].strftime("%Y-%m-%d")

    results = []
    for s in stocks:
        ticker = f"{s['code']}.T"
        if ticker not in prices.columns:
            continue
        col = prices[ticker].dropna()
        if len(col) < 2:
            continue
        p_entry = float(col.iloc[0])
        p_exit  = float(col.iloc[-1])
        ret_pct = (p_exit - p_entry) / p_entry * 100

        # 年率換算
        ann_ret = ((p_exit / p_entry) ** (1 / years) - 1) * 100 if p_entry > 0 else None

        results.append({
            **s,
            "entry_price": p_entry,
            "exit_price":  p_exit,
            "return_pct":  ret_pct,
            "ann_return":  ann_ret,
        })

    # ベンチマーク（日経225）リターン
    bench_ret = None
    bench_ann = None
    if BENCHMARK in prices.columns:
        bc = prices[BENCHMARK].dropna()
        if len(bc) >= 2:
            b_entry = float(bc.iloc[0])
            b_exit  = float(bc.iloc[-1])
            bench_ret = (b_exit - b_entry) / b_entry * 100
            bench_ann = ((b_exit / b_entry) ** (1 / years) - 1) * 100

    # ポートフォリオ平均（均等配分）
    if results:
        port_ret = sum(r["return_pct"] for r in results) / len(results)
        port_ann = sum(r["ann_return"] for r in results if r["ann_return"] is not None) / len(results)
        alpha = port_ret - bench_ret if bench_ret is not None else None
    else:
        port_ret = port_ann = alpha = None

    # ── Step 4: 表示 ──────────────────────────────────────────────
    # フィルタ条件の説明文
    filter_parts = []
    if large_cap:     filter_parts.append("大型株")
    if mid_cap:       filter_parts.append("中型株")
    if small_cap:     filter_parts.append("小型株")
    if market:        filter_parts.append(market)
    if sector:        filter_parts.append(sector)
    if min_yield:     filter_parts.append(f"利回り{min_yield*100:.0f}%以上")
    if min_no_cut:    filter_parts.append(f"非減配{min_no_cut}年以上")
    if max_per:       filter_parts.append(f"PER{max_per:.0f}倍以下")
    if max_pbr:       filter_parts.append(f"PBR{max_pbr:.1f}倍以下")
    filter_desc = " × ".join(filter_parts) if filter_parts else "全銘柄"

    click.echo(f"\n{'━'*72}")
    click.echo(f" バックテスト: {filter_desc} TOP{top} ／ 保有期間 {years:.1f}年")
    click.echo(f" 期間: {entry_date_str} → {exit_date_str}  ベンチマーク: 日経225")
    click.echo(f"{'━'*72}")
    click.echo(
        f"{'Rank':>4}  {'CODE':>6}  {'会社名':<20}  "
        f"{'Score':>5}  {'始値':>7}  {'終値':>7}  "
        f"{'リターン':>8}  {'年率':>6}"
    )
    click.echo("-" * 72)

    for i, r in enumerate(sorted(results, key=lambda x: x["return_pct"], reverse=True), 1):
        ann_str = f"{r['ann_return']:+.1f}%" if r['ann_return'] is not None else "-"
        click.echo(
            f"{i:>4}  {r['code']:>6}  {str(r['name'])[:20]:<20}  "
            f"{r['score']:>5.1f}  "
            f"¥{r['entry_price']:>6,.0f}  ¥{r['exit_price']:>6,.0f}  "
            f"{r['return_pct']:>+7.1f}%  {ann_str:>6}"
        )

    click.echo("-" * 72)
    if port_ret is not None:
        click.echo(f"  ポートフォリオ合計リターン（均等配分）: {port_ret:+.1f}%  年率: {port_ann:+.1f}%")
    if bench_ret is not None:
        click.echo(f"  日経225リターン:                       {bench_ret:+.1f}%  年率: {bench_ann:+.1f}%")
    if alpha is not None:
        symbol = "✅" if alpha > 0 else "❌"
        click.echo(f"  超過リターン（α）:                     {alpha:+.1f}%  {symbol}")
    click.echo(f"{'━'*72}\n")

    # ── Step 5: CSV出力 ───────────────────────────────────────────
    if out and results:
        import csv
        headers = ["rank","code","name","score","entry_price","exit_price",
                   "return_pct","ann_return_pct","div_yield","no_cut_years","market_cap"]
        sorted_results = sorted(results, key=lambda x: x["return_pct"], reverse=True)
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for i, r in enumerate(sorted_results, 1):
                mc = r["market_cap"]
                mc_str = f"{mc/1e12:.2f}兆" if mc and mc >= 1e12 else (f"{mc/1e8:.0f}億" if mc else "-")
                w.writerow([
                    i, r["code"], r["name"], r["score"],
                    r["entry_price"], r["exit_price"],
                    round(r["return_pct"], 2),
                    round(r["ann_return"], 2) if r["ann_return"] else None,
                    round(r["div_yield"] * 100, 2) if r["div_yield"] else None,
                    r["no_cut"],
                    mc_str,
                ])
        click.echo(f"CSV保存: {out}")
