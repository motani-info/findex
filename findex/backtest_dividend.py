"""
配当ベースのバックテスト

株価リターンではなく「配当収入・配当成長・減配有無」で評価する。
高スコア銘柄が実際に優れた配当実績を示しているかを検証。

主要指標:
  - コスト利回り  : 購入時株価に対する実際の受取配当率
  - 配当成長率   : 保有期間中の配当増減
  - 減配有無     : 保有期間中に1度でも減配したか
"""
from __future__ import annotations

import sqlite3
from typing import Optional

import pandas as pd
import yfinance as yf


DB_PATH = "/Users/motani/.findex/db/findex.db"


def run_dividend_backtest(
    years: float = 3.0,
    sample_n: int = 200,
    min_score: float = 60.0,
    large_cap: bool = False,
    mid_cap: bool = False,
) -> None:
    import click

    conn = sqlite3.connect(DB_PATH)

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

    codes = [r[0] for r in rows]
    scores = {r[0]: r[2] for r in rows}
    names  = {r[0]: r[1] for r in rows}

    click.echo(f"対象: {len(codes)}銘柄 × {years}年間の配当データを取得中...")

    from datetime import date
    from dateutil.relativedelta import relativedelta
    cutoff = pd.Timestamp(date.today()) - pd.DateOffset(years=years)

    # 株価（entry price）を取得
    import time
    BATCH = 100
    price_map: dict[str, float] = {}
    tickers_all = [f"{c}.T" for c in codes]

    for i in range(0, len(tickers_all), BATCH):
        batch = tickers_all[i:i+BATCH]
        raw = yf.download(
            batch, period=f"{int(years)+1}y", interval="1mo",
            auto_adjust=False, progress=False, threads=False,
        )
        if raw.empty:
            continue
        close = raw["Close"] if "Close" in raw.columns else raw
        if isinstance(close, pd.Series):
            close = close.to_frame(name=batch[0])
        # cutoff付近の最初の価格をentry priceとして使用
        after_cutoff = close[close.index >= cutoff]
        if after_cutoff.empty:
            continue
        entry_row = after_cutoff.iloc[0]
        for ticker, price in entry_row.items():
            if pd.notna(price) and float(price) > 0:
                code = str(ticker).replace(".T", "")
                price_map[code] = float(price)
        time.sleep(2)

    click.echo(f"株価取得完了: {len(price_map)}件")

    # 配当データを個別取得
    results = []
    for i, code in enumerate(codes):
        if code not in price_map:
            continue
        entry_price = price_map[code]

        try:
            divs = yf.Ticker(f"{code}.T").dividends
            if divs.empty:
                results.append({
                    "code": code, "name": names[code], "score": scores[code],
                    "entry_price": entry_price,
                    "total_div": 0, "yield_on_cost": 0,
                    "div_growth": None, "had_cut": False, "paid_div": False,
                })
                continue

            divs.index = divs.index.tz_localize(None)
            recent = divs[divs.index >= cutoff]

            if recent.empty:
                total_div = 0.0
                had_cut = False
                div_growth = None
                paid_div = False
            else:
                total_div = float(recent.sum())
                paid_div = True

                # 年次集計して増減を確認
                def fy(d): return d.year if d.month >= 4 else d.year - 1
                annual = recent.groupby(recent.index.map(fy)).sum()

                if len(annual) >= 2:
                    had_cut = any(
                        annual.iloc[i] < annual.iloc[i-1]
                        for i in range(1, len(annual))
                    )
                    # 最終年/最初年のCAGR
                    v0, vn = float(annual.iloc[0]), float(annual.iloc[-1])
                    n = len(annual) - 1
                    div_growth = ((vn / v0) ** (1/n) - 1) if v0 > 0 and n > 0 else None
                else:
                    had_cut = False
                    div_growth = None

            yield_on_cost = total_div / entry_price if entry_price > 0 else 0

            results.append({
                "code": code, "name": names[code], "score": scores[code],
                "entry_price": entry_price,
                "total_div": total_div,
                "yield_on_cost": yield_on_cost,
                "div_growth": div_growth,
                "had_cut": had_cut,
                "paid_div": paid_div,
            })
        except Exception:
            continue

        if (i+1) % 20 == 0:
            click.echo(f"  {i+1}/{len(codes)}件処理済み...")
            time.sleep(1)

    df = pd.DataFrame(results)
    if df.empty:
        click.echo("データなし")
        return

    # ── スコア四分位ごとの配当分析 ──────────────────────────────
    df["quartile"] = pd.qcut(df["score"], q=4, labels=["Q1(低)", "Q2", "Q3", "Q4(高)"])

    cat = "大型株" if large_cap else ("中型株" if mid_cap else "全銘柄")
    import click as c
    c.echo(f"\n{'━'*65}")
    c.echo(f" 配当バックテスト: {cat} / {years:.0f}年 / {len(df)}銘柄")
    c.echo(f"{'━'*65}")

    c.echo(f"\n【スコア四分位別 配当指標】")
    c.echo(f"  {'区分':<10}  {'コスト利回り':>10}  {'配当成長(年率)':>13}  {'減配率':>7}  {'配当銘柄%':>9}")
    c.echo(f"  {'-'*55}")

    for q in ["Q1(低)", "Q2", "Q3", "Q4(高)"]:
        g = df[df["quartile"] == q]
        yoc    = g["yield_on_cost"].mean() * 100
        growth = g["div_growth"].dropna().mean() * 100 if g["div_growth"].notna().any() else float('nan')
        cut_r  = g["had_cut"].mean() * 100
        paid_r = g["paid_div"].mean() * 100
        marker = " ← 最高スコア帯" if q == "Q4(高)" else ""
        growth_str = f"{growth:+.1f}%" if not pd.isna(growth) else "  N/A"
        c.echo(f"  {q:<10}  {yoc:>9.1f}%  {growth_str:>13}  {cut_r:>6.1f}%  {paid_r:>8.1f}%{marker}")

    # Spearman相関（scipy不要の手計算）
    def spearman(a: pd.Series, b: pd.Series) -> float:
        df_tmp = pd.DataFrame({"a": a, "b": b}).dropna()
        if len(df_tmp) < 5:
            return float('nan')
        return df_tmp["a"].rank().corr(df_tmp["b"].rank())

    rho_yoc = spearman(df["score"], df["yield_on_cost"])
    rho_g   = spearman(df["score"], df["div_growth"])

    c.echo(f"\n【スコアと配当指標の相関（Spearman ρ）】")
    c.echo(f"  コスト利回りとの相関  ρ = {rho_yoc:+.3f}", nl=False)
    c.echo(f"  {'✅ 正の相関' if rho_yoc > 0.1 else ('⚠️ 弱い' if rho_yoc > 0 else '❌ 負')}")
    if not pd.isna(rho_g):
        c.echo(f"  配当成長率との相関    ρ = {rho_g:+.3f}", nl=False)
        c.echo(f"  {'✅ 正の相関' if rho_g > 0.1 else ('⚠️ 弱い' if rho_g > 0 else '❌ 負')}")

    # 減配有無
    total_cut  = df["had_cut"].sum()
    total_paid = df["paid_div"].sum()
    c.echo(f"\n【配当健全性サマリ】")
    c.echo(f"  配当支払い銘柄: {total_paid:.0f}/{len(df)}社 ({total_paid/len(df):.1%})")
    c.echo(f"  保有期間中に減配: {total_cut:.0f}社 ({total_cut/len(df):.1%})")

    # TOP10 vs BOTTOM10
    top10 = df.nlargest(10, "score")
    bot10 = df.nsmallest(10, "score")
    c.echo(f"\n【TOP10 vs BOTTOM10（スコア順）の配当比較】")
    c.echo(f"  スコア上位10 コスト利回り平均: {top10['yield_on_cost'].mean()*100:.2f}%  減配: {top10['had_cut'].sum():.0f}社")
    c.echo(f"  スコア下位10 コスト利回り平均: {bot10['yield_on_cost'].mean()*100:.2f}%  減配: {bot10['had_cut'].sum():.0f}社")
    c.echo(f"{'━'*65}\n")
