"""
スコアとリターンの相関分析

「TOP10がベンチマークを上回るか」ではなく、
「スコアが高い銘柄ほどリターンが高いか」を統計的に検証する。
"""
from __future__ import annotations

import sqlite3
from typing import Optional

import pandas as pd
import yfinance as yf


DB_PATH = "/Users/motani/.findex/db/findex.db"
BENCHMARK = "^N225"


def run_correlation_analysis(
    years: float = 3.0,
    min_score: float = 60.0,
    sample_n: int = 200,
    large_cap: bool = False,
    mid_cap: bool = False,
) -> None:
    """
    スコア上位N銘柄を取得し、スコアとリターンの相関を分析する。

    出力:
      - スコア四分位ごとの平均リターン（スコアが効いているか）
      - スコアとリターンのSpearman相関係数
      - ベンチマーク超過率（何%の銘柄が日経225を上回ったか）
    """
    import click

    conn = sqlite3.connect(DB_PATH)

    # フィルタ条件
    where_clauses = [
        "s.rowid IN (SELECT MAX(rowid) FROM scores GROUP BY code)",
        "s.total_score IS NOT NULL",
        f"s.total_score >= {min_score}",
    ]
    if large_cap:
        where_clauses.append("json_extract(s.raw_json, '$.market_cap') >= 500000000000")
    if mid_cap:
        where_clauses.append("json_extract(s.raw_json, '$.market_cap') >= 100000000000")
        where_clauses.append("json_extract(s.raw_json, '$.market_cap') < 500000000000")

    rows = conn.execute(f"""
        SELECT s.code, st.name, s.total_score
        FROM scores s
        JOIN stocks st ON s.code = st.code
        WHERE {" AND ".join(where_clauses)}
        ORDER BY s.total_score DESC
        LIMIT {sample_n}
    """).fetchall()
    conn.close()

    if not rows:
        click.echo("対象銘柄なし")
        return

    codes  = [r[0] for r in rows]
    scores = {r[0]: r[2] for r in rows}
    names  = {r[0]: r[1] for r in rows}

    click.echo(f"対象: {len(codes)}銘柄（スコア{min_score}点以上）× {years}年間の株価を取得中...")

    # 株価取得（バッチ）
    BATCH = 100
    price_map: dict[str, tuple[float, float]] = {}  # code → (entry, exit)
    tickers_all = [f"{c}.T" for c in codes] + [BENCHMARK]

    for i in range(0, len(tickers_all), BATCH):
        batch = tickers_all[i:i+BATCH]
        raw = yf.download(
            batch, period=f"{int(years)}y", interval="1mo",
            auto_adjust=True, progress=False, threads=False,
        )
        if raw.empty:
            continue
        close = raw["Close"] if "Close" in raw.columns else raw
        if isinstance(close, pd.Series):
            close = close.to_frame(name=batch[0])
        for ticker in batch:
            col = close.get(ticker)
            if col is None:
                continue
            col = col.dropna()
            if len(col) < 2:
                continue
            price_map[ticker] = (float(col.iloc[0]), float(col.iloc[-1]))

    # ベンチマークリターン
    bench_entry, bench_exit = price_map.get(BENCHMARK, (None, None))
    bench_ret = (bench_exit - bench_entry) / bench_entry * 100 if bench_entry else None

    # 各銘柄リターン計算
    results = []
    for code in codes:
        ticker = f"{code}.T"
        if ticker not in price_map:
            continue
        entry, exit_ = price_map[ticker]
        ret = (exit_ - entry) / entry * 100
        results.append({
            "code":   code,
            "name":   names[code],
            "score":  scores[code],
            "return": ret,
            "beat_bench": ret > bench_ret if bench_ret is not None else None,
        })

    df = pd.DataFrame(results)
    if df.empty:
        click.echo("リターンデータ取得失敗")
        return

    # ── 分析1: スコア四分位ごとの平均リターン ──────────────────
    df["quartile"] = pd.qcut(df["score"], q=4, labels=["Q1(低)", "Q2", "Q3", "Q4(高)"])
    q_summary = df.groupby("quartile", observed=True)["return"].agg(
        ["mean", "median", "count"]
    ).round(1)

    # ── 分析2: Spearman相関 ─────────────────────────────────────
    spearman_r = df[["score", "return"]].corr(method="spearman").iloc[0, 1]

    # ── 分析3: ベンチマーク超過率 ─────────────────────────────────
    beat_rate = df["beat_bench"].mean() if bench_ret is not None else None

    # ── 表示 ──────────────────────────────────────────────────────
    cat = "大型株" if large_cap else ("中型株" if mid_cap else "全銘柄")
    click.echo(f"\n{'━'*60}")
    click.echo(f" スコア×リターン相関分析: {cat} / {years:.0f}年 / {len(df)}銘柄")
    click.echo(f" 期間ベンチマーク（日経225）: {bench_ret:+.1f}%" if bench_ret else "")
    click.echo(f"{'━'*60}")

    click.echo(f"\n【スコア四分位別 平均リターン】")
    click.echo(f"  {'区分':<10}  {'平均':>7}  {'中央値':>7}  {'銘柄数':>5}")
    click.echo(f"  {'-'*35}")
    for q, row in q_summary.iterrows():
        marker = " ← 最高スコア帯" if str(q) == "Q4(高)" else ""
        click.echo(f"  {str(q):<10}  {row['mean']:>+6.1f}%  {row['median']:>+6.1f}%  {int(row['count']):>5}{marker}")

    click.echo(f"\n【スコアとリターンの相関】")
    click.echo(f"  Spearman ρ = {spearman_r:+.3f}", nl=False)
    if spearman_r > 0.2:
        click.echo("  ✅ 正の相関あり（スコアが効いている）")
    elif spearman_r > 0:
        click.echo("  ⚠️  弱い正の相関（改善余地あり）")
    else:
        click.echo("  ❌ 相関なし・負の相関（スコアが機能していない）")

    if beat_rate is not None:
        click.echo(f"\n【日経225超過率】")
        click.echo(f"  {len(df)}銘柄中 {df['beat_bench'].sum():.0f}銘柄が日経225を超過 ({beat_rate:.1%})")

    # ── TOP10 vs BOTTOM10 ────────────────────────────────────────
    top10  = df.nlargest(10,  "score")["return"].mean()
    bot10  = df.nsmallest(10, "score")["return"].mean()
    click.echo(f"\n【TOP10 vs BOTTOM10（スコア順）】")
    click.echo(f"  スコア上位10銘柄 平均リターン: {top10:+.1f}%")
    click.echo(f"  スコア下位10銘柄 平均リターン: {bot10:+.1f}%")
    click.echo(f"  差: {top10-bot10:+.1f}%")
    click.echo(f"{'━'*60}\n")

    # ── 上位・下位銘柄一覧 ───────────────────────────────────────
    click.echo("【スコア上位10銘柄のリターン】")
    for _, r in df.nlargest(10, "score").iterrows():
        b = "✅" if r["beat_bench"] else "❌"
        click.echo(f"  {r['code']}  {str(r['name'])[:18]:<18}  score={r['score']:.1f}  ret={r['return']:+.1f}% {b}")

    click.echo("\n【スコア下位10銘柄のリターン】")
    for _, r in df.nsmallest(10, "score").iterrows():
        b = "✅" if r["beat_bench"] else "❌"
        click.echo(f"  {r['code']}  {str(r['name'])[:18]:<18}  score={r['score']:.1f}  ret={r['return']:+.1f}% {b}")
