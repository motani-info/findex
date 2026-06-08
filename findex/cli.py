"""findex CLI エントリーポイント"""
from pathlib import Path
import sys
import click

from findex.settings import Settings

DEFAULT_RULES = Path(__file__).parent.parent / "rules.yaml"


@click.group()
@click.pass_context
def cli(ctx):
    """Findex — 日本株スコアリング・ランキングツール"""
    ctx.ensure_object(dict)
    ctx.obj["settings"] = Settings.load()


# ══════════════════════════════════════════════════════════════════
#  findex dividend  — 配当品質スコア系コマンド
# ══════════════════════════════════════════════════════════════════

@cli.group()
@click.pass_context
def dividend(ctx):
    """配当品質スコアのランキング・銘柄確認"""
    ctx.ensure_object(dict)


@dividend.command("rank")
@click.option("--top",        default=30,   type=int,   help="表示する上位銘柄数")
@click.option("--market",     default=None, help="市場でフィルタ（例: プライム）")
@click.option("--sector",     default=None, help="業種でフィルタ（例: 電気機器）")
@click.option("--min-yield",  default=None, type=float, help="最低配当利回り（例: 0.03 = 3%）")
@click.option("--min-no-cut", default=None, type=int,   help="最低連続非減配年数")
@click.option("--min-cap",    default=None, type=float, help="最低時価総額（兆円、例: 0.5 = 5,000億円）")
@click.option("--max-cap",    default=None, type=float, help="最高時価総額（兆円、例: 1.0 = 1兆円）")
@click.option("--large-cap",  is_flag=True, default=False, help="大型株（時価総額5,000億円以上）")
@click.option("--mid-cap",    is_flag=True, default=False, help="中型株（時価総額1,000〜5,000億円）")
@click.option("--small-cap",  is_flag=True, default=False, help="小型株（時価総額1,000億円未満）")
@click.option("--max-per",    default=None, type=float, help="PER上限（例: 25 → 割高株を除外）")
@click.option("--max-pbr",    default=None, type=float, help="PBR上限（例: 3.0 → 割高株を除外）")
@click.option("--out",        default=None, help="CSV出力先パス")
@click.pass_context
def dividend_rank(ctx, top, market, sector, min_yield, min_no_cut, min_cap, max_cap,
                  large_cap, mid_cap, small_cap, max_per, max_pbr, out):
    """配当品質スコアのランキングを表示する（API不要・即時）。

    \b
    例:
      findex dividend rank                              # 総合TOP30
      findex dividend rank --large-cap                  # 大型株TOP30
      findex dividend rank --min-yield 0.03             # 利回り3%以上
      findex dividend rank --sector 電気機器 --top 20   # セクター絞り込み
      findex dividend rank --max-per 20 --max-pbr 2.0   # 割安フィルター
      findex dividend rank --out result.csv             # CSV出力
    """
    import sqlite3

    db_path = "/Users/motani/.findex/db/findex.db"
    conn = sqlite3.connect(db_path)

    if large_cap:
        min_cap = max(min_cap or 0, 0.5)
    if mid_cap:
        min_cap = max(min_cap or 0, 0.1)
        max_cap = min(max_cap or 999, 0.5)
    if small_cap:
        max_cap = min(max_cap or 999, 0.1)

    where_clauses = [
        "s.rowid IN (SELECT MAX(rowid) FROM scores GROUP BY code)",
        "s.total_score IS NOT NULL",
    ]
    if market:
        where_clauses.append(f"st.market = '{market}'")
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

    rows = conn.execute(f"""
        SELECT s.code, st.name, st.market, st.sector, s.total_score, s.scored_at,
               json_extract(s.raw_json, '$.div_yield') as div_yield,
               json_extract(s.raw_json, '$.per') as per,
               json_extract(s.raw_json, '$.pbr') as pbr,
               json_extract(s.raw_json, '$.roe') as roe,
               json_extract(s.raw_json, '$.consecutive_no_cut_years') as no_cut,
               json_extract(s.raw_json, '$.consecutive_dividend_growth_years') as div_growth,
               json_extract(s.raw_json, '$.equity_ratio') as eq_ratio,
               json_extract(s.raw_json, '$.market_cap') as market_cap
        FROM scores s
        JOIN stocks st ON s.code = st.code
        WHERE {" AND ".join(where_clauses)}
        ORDER BY s.total_score DESC
    """).fetchall()
    conn.close()

    filtered = []
    for r in rows:
        dy = r[6]
        nc = r[10]
        if min_yield is not None and (dy is None or dy < min_yield):
            continue
        if min_no_cut is not None and (nc is None or nc < min_no_cut):
            continue
        filtered.append(r)
    filtered = filtered[:top]

    if not filtered:
        click.echo("条件に合う銘柄が見つかりません。")
        return

    click.echo(f"\n{'Rank':>4}  {'CODE':>6}  {'会社名':<22}  {'Score':>5}  {'利回り':>6}  {'時価総額':>7}  {'PER':>5}  {'ROE':>5}  {'非減配':>4}  {'増配':>3}  {'自己資本':>5}")
    click.echo("-" * 110)
    for i, r in enumerate(filtered, 1):
        dy  = f"{r[6]*100:.1f}%"  if r[6]  is not None else "-"
        per = f"{r[7]:.1f}"       if r[7]  is not None else "-"
        roe = f"{r[9]*100:.1f}%"  if r[9]  is not None else "-"
        nc  = str(int(r[10]))     if r[10] is not None else "-"
        dg  = str(int(r[11]))     if r[11] is not None else "-"
        eq  = f"{r[12]*100:.0f}%" if r[12] is not None else "-"
        mc  = r[13]
        mc_str = (f"{mc/1e12:.1f}兆" if mc and mc >= 1e12
                  else f"{mc/1e9:.0f}B" if mc and mc >= 1e10
                  else f"{mc/1e8:.0f}億" if mc else "-")
        click.echo(f"{i:>4}  {r[0]:>6}  {str(r[1])[:22]:<22}  {r[4]:>5.1f}  {dy:>6}  {mc_str:>7}  {per:>5}  {roe:>5}  {nc:>4}  {dg:>3}  {eq:>5}")

    click.echo(f"\n合計 {len(filtered)} 件 / {len(rows)} 件中")

    if out:
        import csv
        headers = ["rank","code","name","market","sector","score","div_yield","per","pbr","roe",
                   "market_cap","consecutive_no_cut_years","consecutive_dividend_growth_years",
                   "equity_ratio","updated_at"]
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for i, r in enumerate(filtered, 1):
                w.writerow([i, r[0], r[1], r[2], r[3], r[4],
                            r[6], r[7], r[8], r[9], r[13], r[10], r[11], r[12],
                            r[5][:10] if r[5] else ""])
        click.echo(f"CSV保存: {out}")


@dividend.command("check")
@click.argument("code")
@click.pass_context
def dividend_check(ctx, code):
    """指定した銘柄の配当スコア詳細を表示する（DBから即時表示）。

    \b
    例:
      findex dividend check 8316
      findex dividend check 6584
    """
    import sqlite3
    import json

    db_path = "/Users/motani/.findex/db/findex.db"
    conn = sqlite3.connect(db_path)

    row = conn.execute("""
        SELECT st.name, st.sector, s.total_score, s.scored_at, s.raw_json
        FROM scores s
        JOIN stocks st ON s.code = st.code
        WHERE s.code = ? AND s.rowid IN (SELECT MAX(rowid) FROM scores GROUP BY code)
    """, (code,)).fetchone()

    # 各指標スコアも取得
    score_row = conn.execute("""
        SELECT * FROM scores
        WHERE code = ? AND rowid IN (SELECT MAX(rowid) FROM scores GROUP BY code)
    """, (code,)).fetchone()
    col_names = [d[0] for d in conn.execute(
        "SELECT * FROM scores WHERE code=? LIMIT 1", (code,)).description or []]
    conn.close()

    if not row:
        click.echo(f"{code}: DBにデータがありません。`findex update` を実行してください。")
        return

    name, sector, total_score, scored_at, raw_json = row
    raw = json.loads(raw_json) if raw_json else {}

    click.echo(f"\n{'━'*60}")
    click.echo(f" {code}  {name}  [{sector}]")
    click.echo(f" 総合スコア: {total_score:.2f}点  （更新: {scored_at[:10] if scored_at else '-'}）")
    click.echo(f"{'━'*60}")

    # 主要指標
    def fmt(v, fmt_str=".2f", suffix=""):
        return f"{v:{fmt_str}}{suffix}" if v is not None else "-"

    click.echo(f"\n【バリュエーション】")
    click.echo(f"  PER:          {fmt(raw.get('per'), '.1f', '倍')}")
    click.echo(f"  PBR:          {fmt(raw.get('pbr'), '.2f', '倍')}")
    click.echo(f"  PER×PBR:      {fmt(raw.get('mix_coefficient'), '.1f')}")
    click.echo(f"  ネットキャッシュ調整PER: {fmt(raw.get('net_cash_per'), '.1f', '倍')}")

    click.echo(f"\n【配当】")
    click.echo(f"  配当利回り:        {fmt(raw.get('div_yield') and raw['div_yield']*100, '.2f', '%')}")
    click.echo(f"  連続非減配:        {fmt(raw.get('consecutive_no_cut_years'), '.0f', '年')}")
    click.echo(f"  連続増配:          {fmt(raw.get('consecutive_dividend_growth_years'), '.0f', '年')}")
    click.echo(f"  5年配当CAGR:       {fmt(raw.get('dividend_growth_5y_cagr') and raw['dividend_growth_5y_cagr']*100, '.1f', '%')}")
    click.echo(f"  10年配当CAGR:      {fmt(raw.get('dividend_growth_10y_cagr') and raw['dividend_growth_10y_cagr']*100, '.1f', '%')}")
    click.echo(f"  配当性向:          {fmt(raw.get('payout_ratio') and raw['payout_ratio']*100, '.1f', '%')}")
    click.echo(f"  配当信頼性:        {fmt(raw.get('dividend_reliability'), '.2f')}")
    click.echo(f"  20年減配回数:      {fmt(raw.get('dividend_cut_count_20y'), '.0f', '回')}")

    click.echo(f"\n【財務健全性】")
    click.echo(f"  自己資本比率:      {fmt(raw.get('equity_ratio') and raw['equity_ratio']*100, '.1f', '%')}")
    click.echo(f"  D/Eレシオ:         {fmt(raw.get('debt_to_equity'), '.2f', '倍')}")
    click.echo(f"  ROE:               {fmt(raw.get('roe') and raw['roe']*100, '.1f', '%')}")
    click.echo(f"  営業利益率:        {fmt(raw.get('operating_margin') and raw['operating_margin']*100, '.1f', '%')}")
    click.echo(f"  ROIC-WACC:         {fmt(raw.get('roic_minus_wacc') and raw['roic_minus_wacc']*100, '.1f', 'pp')}")
    click.echo(f"  FCFペイアウト:     {fmt(raw.get('fcf_payout_coverage'), '.2f')}")

    click.echo(f"\n【成長性】")
    click.echo(f"  売上5年CAGR:       {fmt(raw.get('revenue_growth_5y_cagr') and raw['revenue_growth_5y_cagr']*100, '.1f', '%')}")
    click.echo(f"  EPS5年成長:        {fmt(raw.get('eps_growth_5y') and raw['eps_growth_5y']*100, '.1f', '%')}")

    mc = raw.get('market_cap')
    mc_str = (f"{mc/1e12:.1f}兆円" if mc and mc >= 1e12
              else f"{mc/1e9:.0f}億円" if mc and mc >= 1e8 else "-")
    click.echo(f"\n【規模】")
    click.echo(f"  時価総額:          {mc_str}")
    click.echo(f"{'━'*60}\n")


# ══════════════════════════════════════════════════════════════════
#  findex momentum  — モメンタムスコア系コマンド
# ══════════════════════════════════════════════════════════════════

@cli.group()
@click.pass_context
def momentum(ctx):
    """株価モメンタム・業績加速のランキング・銘柄確認・検証"""
    ctx.ensure_object(dict)


@momentum.command("rank")
@click.option("--top",           default=30,   type=int,   help="表示件数")
@click.option("--market",        default=None, help="市場フィルタ（例: プライム）")
@click.option("--sector",        default=None, help="業種フィルタ（例: 情報・通信業）")
@click.option("--min-div-score", default=None, type=float, help="配当スコア下限（例: 70）")
@click.option("--large-cap",     is_flag=True, default=False, help="大型株（5,000億円以上）")
@click.option("--mid-cap",       is_flag=True, default=False, help="中型株（1,000〜5,000億円）")
@click.option("--small-cap",     is_flag=True, default=False, help="小型株（1,000億円未満）")
@click.option("--out",           default=None, help="CSV出力先")
@click.pass_context
def momentum_rank(ctx, top, market, sector, min_div_score, large_cap, mid_cap, small_cap, out):
    """株価モメンタム・業績加速でランキングする（配当スコアとは独立した評価軸）。

    \b
    例:
      findex momentum rank                          # 全銘柄モメンタムTOP30
      findex momentum rank --large-cap              # 大型株モメンタムTOP30
      findex momentum rank --sector 情報・通信業    # IT株に絞る
      findex momentum rank --min-div-score 70       # 配当優良株のモメンタム上位
      findex momentum rank --top 50 --out mom.csv
    """
    from findex.momentum import run_momentum
    run_momentum(
        top=top, market=market, sector=sector,
        min_div_score=min_div_score,
        large_cap=large_cap, mid_cap=mid_cap, small_cap=small_cap,
        out=out,
    )


@momentum.command("check")
@click.argument("code")
@click.pass_context
def momentum_check(ctx, code):
    """指定した銘柄のモメンタムスコア詳細を表示する。

    \b
    例:
      findex momentum check 8316
      findex momentum check 3687
    """
    import sqlite3
    import time
    import pandas as pd
    import yfinance as yf
    from findex.momentum import MOMENTUM_RULES, MAX_WEIGHTED, _score_one, _calc_momentum_score

    db_path = "/Users/motani/.findex/db/findex.db"
    conn = sqlite3.connect(db_path)

    # 銘柄名・配当スコア取得
    row = conn.execute("""
        SELECT st.name, st.sector, s.total_score,
               json_extract(s.raw_json, '$.revenue_growth_5y_cagr') as rev_growth,
               json_extract(s.raw_json, '$.eps_growth_5y') as eps_growth,
               json_extract(s.raw_json, '$.market_cap') as market_cap
        FROM scores s JOIN stocks st ON s.code = st.code
        WHERE s.code = ? AND s.rowid IN (SELECT MAX(rowid) FROM scores GROUP BY code)
    """, (code,)).fetchone()
    conn.close()

    if not row:
        click.echo(f"{code}: DBにデータがありません。")
        return

    name, sector, div_score, rev_growth, eps_growth, market_cap = row

    # 株価データ取得（price_history or yfinance）
    conn = sqlite3.connect(db_path)
    from datetime import date, timedelta
    today_str = date.today().isoformat()
    d3m  = (date.today() - timedelta(days=91)).isoformat()
    d12m = (date.today() - timedelta(days=366)).isoformat()

    ph_rows = conn.execute("""
        SELECT date, close FROM price_history
        WHERE code=? ORDER BY date DESC LIMIT 400
    """, (code,)).fetchall()
    conn.close()

    if len(ph_rows) >= 10:
        df_p = pd.DataFrame(ph_rows, columns=["date", "close"]).set_index("date").sort_index()
        latest = float(df_p["close"].iloc[-1])
        past3  = df_p[df_p.index <= d3m]
        past12 = df_p[df_p.index <= d12m]
        ret_3m   = (latest / float(past3["close"].iloc[-1]) - 1)  if not past3.empty  else None
        ret_12m  = (latest / float(past12["close"].iloc[-1]) - 1) if not past12.empty else None
        hi52_range = df_p[df_p.index >= d12m]["close"]
        hi52_ratio = (latest / float(hi52_range.max())) if not hi52_range.empty else None
        source = "price_history"
    else:
        click.echo(f"  yfinanceから株価を取得中...")
        col = yf.download(f"{code}.T", period="13mo", interval="1mo",
                          auto_adjust=True, progress=False, threads=False)
        if col.empty:
            click.echo("株価データを取得できませんでした。")
            return
        close_col = col["Close"]
        # マルチカラムの場合はflattenする
        if hasattr(close_col, "columns"):
            close_col = close_col.iloc[:, 0]
        prices = close_col.dropna()
        latest = float(prices.iloc[-1])
        ret_3m   = (latest / float(prices.iloc[-4]) - 1) if len(prices) >= 4 else None
        ret_12m  = (latest / float(prices.iloc[0])  - 1)
        hi52_ratio = latest / float(prices.max())
        source = "yfinance"

    fields = {
        "ret_12m":    ret_12m,
        "ret_3m":     ret_3m,
        "hi52_ratio": hi52_ratio,
        "rev_growth": rev_growth,
        "eps_growth": eps_growth,
        "vol_ratio":  None,
    }
    score_detail = _calc_momentum_score(fields)

    mc = market_cap
    mc_str = (f"{mc/1e12:.1f}兆円" if mc and mc >= 1e12
              else f"{mc/1e9:.0f}億円" if mc and mc >= 1e8 else "-")

    click.echo(f"\n{'━'*60}")
    click.echo(f" {code}  {name}  [{sector}]")
    click.echo(f" モメンタムスコア: {score_detail['total']:.1f}点  配当スコア: {div_score:.1f}点")
    click.echo(f" 時価総額: {mc_str}  （データ: {source}）")
    click.echo(f"{'━'*60}")
    click.echo(f"\n{'指標':<16}  {'実値':>10}  {'スコア':>6}")
    click.echo(f"  {'─'*36}")

    labels = {
        "12ヶ月リターン": (ret_12m,    lambda v: f"{v*100:+.1f}%"),
        "3ヶ月リターン":  (ret_3m,     lambda v: f"{v*100:+.1f}%"),
        "52週高値比率":   (hi52_ratio, lambda v: f"{v*100:.0f}%"),
        "売上成長率":     (rev_growth, lambda v: f"{v*100:+.1f}%"),
        "EPS成長率":      (eps_growth, lambda v: f"{v*100:+.1f}%"),
        "出来高増加率":   (None,       lambda v: "-"),
    }
    for name_j, (val, fmt_fn) in labels.items():
        val_str   = fmt_fn(val) if val is not None else "-"
        score_val = score_detail.get(name_j, 0.0)
        click.echo(f"  {name_j:<14}  {val_str:>10}  {score_val:>5.1f}点")

    click.echo(f"{'━'*60}\n")


@momentum.command("backtest")
@click.option("--sample",   default=200, type=int,   help="サンプル銘柄数")
@click.option("--lookback", default=12,  type=int,   help="基準日（何ヶ月前）")
@click.option("--forward",  default=12,  type=int,   help="事後リターン期間（ヶ月）")
@click.option("--market",   default=None,             help="市場フィルタ")
@click.option("--sector",   default=None,             help="セクターフィルタ")
@click.option("--out",      default=None,             help="CSV出力先")
@click.pass_context
def momentum_backtest(ctx, sample, lookback, forward, market, sector, out):
    """モメンタムスコアの回帰検証（過去スコア vs 事後リターンの相関）。

    \b
    例:
      findex momentum backtest
      findex momentum backtest --sample 300
      findex momentum backtest --lookback 6 --forward 6
    """
    from findex.backtest_momentum import run_momentum_backtest
    run_momentum_backtest(
        sample_n=sample,
        lookback_months=lookback,
        forward_months=forward,
        market=market,
        sector=sector,
        out=out,
    )


# ══════════════════════════════════════════════════════════════════
#  findex pipeline  — 新データパイプライン一括実行
# ══════════════════════════════════════════════════════════════════

@cli.command()
@click.option("--codes", default=None, help="カンマ区切りで銘柄指定")
@click.option("--rules", default=str(DEFAULT_RULES), help="ルール定義YAMLパス")
@click.option("--skip-fetch", is_flag=True, default=False, help="fetch をスキップ（compute + score のみ）")
@click.pass_context
def pipeline(ctx, codes, rules, skip_fetch):
    """fetch → compute → score を順序制御付きで一括実行する。

    \b
    例:
      findex pipeline                       # 全銘柄フルパイプライン
      findex pipeline --codes 7203,9433     # 指定銘柄のみ
      findex pipeline --skip-fetch          # fetch済みデータで再計算のみ
    """
    from pathlib import Path as P
    import time

    code_list = [c.strip() for c in codes.split(",")] if codes else None
    rules_path = P(rules)
    t0 = time.time()

    # Step 1: fetch
    if not skip_fetch:
        click.echo("━━━ Step 1/3: fetch quarterly ━━━")
        from findex.updater.fetch_raw import run_fetch_raw
        r1 = run_fetch_raw(codes=code_list, force_all=bool(code_list))
        click.echo(f"  → updated={r1['updated']} failed={r1['failed']}")
    else:
        click.echo("━━━ Step 1/3: fetch (skipped) ━━━")

    # Step 2: compute
    click.echo("━━━ Step 2/3: compute ━━━")
    from findex.updater.compute import run_compute
    r2 = run_compute(codes=code_list)
    click.echo(f"  → updated={r2['updated']}")

    # Step 3: score
    click.echo("━━━ Step 3/3: score ━━━")
    from findex.updater.score_dividend import run_score_dividend
    from findex.updater.score_momentum import run_score_momentum
    r3d = run_score_dividend(rules_path=rules_path, codes=code_list)
    r3m = run_score_momentum(codes=code_list)
    click.echo(f"  → dividend={r3d['scored']} momentum={r3m['scored']}")

    elapsed = time.time() - t0
    click.echo(f"\n✅ pipeline 完了 ({elapsed:.1f}s)")


# ══════════════════════════════════════════════════════════════════
#  findex fetch  — 生データ取得（新データパイプライン）
# ══════════════════════════════════════════════════════════════════

@cli.group()
@click.pass_context
def fetch(ctx):
    """生データを取得して raw テーブルに保存する（計算しない）"""
    ctx.ensure_object(dict)


@fetch.command("quarterly")
@click.option("--codes", default=None, help="カンマ区切りで銘柄指定（例: 7203,9433）")
@click.option("--force-all", is_flag=True, default=False, help="TTL無視で全銘柄を強制取得")
@click.option("--ttl", default=90, type=int, help="再取得までの日数（デフォルト: 90）")
@click.pass_context
def fetch_quarterly(ctx, codes, force_all, ttl):
    """yfinance から財務データを取得して raw_financials に保存する。

    \b
    例:
      findex fetch quarterly                    # TTL切れ銘柄のみ
      findex fetch quarterly --force-all        # 全銘柄強制
      findex fetch quarterly --codes 7203,9433  # 指定銘柄のみ
    """
    from findex.updater.fetch_raw import run_fetch_raw
    code_list = [c.strip() for c in codes.split(",")] if codes else None
    result = run_fetch_raw(codes=code_list, force_all=force_all, ttl_days=ttl)
    click.echo(
        f"完了: updated={result['updated']} "
        f"failed={result['failed']} "
        f"elapsed={result['elapsed_sec']:.1f}s"
    )


# ══════════════════════════════════════════════════════════════════
#  findex compute  — 算出指標計算（新データパイプライン）
# ══════════════════════════════════════════════════════════════════

@cli.command()
@click.option("--codes", default=None, help="カンマ区切りで銘柄指定")
@click.pass_context
def compute(ctx, codes):
    """raw_financials + price_history + dividend_history → computed_metrics を計算する。

    \b
    例:
      findex compute                  # 全銘柄
      findex compute --codes 7203     # 指定銘柄のみ
    """
    from findex.updater.compute import run_compute
    code_list = [c.strip() for c in codes.split(",")] if codes else None
    result = run_compute(codes=code_list)
    click.echo(
        f"完了: updated={result['updated']} "
        f"skipped={result['skipped']} "
        f"elapsed={result['elapsed_sec']:.1f}s"
    )


# ══════════════════════════════════════════════════════════════════
#  findex score  — スコアリング（新データパイプライン）
# ══════════════════════════════════════════════════════════════════

@cli.group()
@click.pass_context
def score(ctx):
    """computed_metrics からスコアを計算して保存する"""
    ctx.ensure_object(dict)


@score.command("dividend")
@click.option("--codes", default=None, help="カンマ区切りで銘柄指定")
@click.option("--rules", default=str(DEFAULT_RULES), help="ルール定義YAMLパス")
@click.pass_context
def score_dividend(ctx, codes, rules):
    """配当スコアを計算して dividend_scores に保存する。

    \b
    例:
      findex score dividend
      findex score dividend --codes 7203,9433
    """
    from findex.updater.score_dividend import run_score_dividend
    from pathlib import Path as P
    code_list = [c.strip() for c in codes.split(",")] if codes else None
    result = run_score_dividend(rules_path=P(rules), codes=code_list)
    click.echo(
        f"完了: scored={result['scored']} "
        f"skipped={result['skipped']} "
        f"elapsed={result['elapsed_sec']:.1f}s"
    )


@score.command("momentum")
@click.option("--codes", default=None, help="カンマ区切りで銘柄指定")
@click.pass_context
def score_momentum(ctx, codes):
    """モメンタムスコアを計算して momentum_scores に保存する。

    \b
    例:
      findex score momentum
      findex score momentum --codes 7203,9433
    """
    from findex.updater.score_momentum import run_score_momentum
    code_list = [c.strip() for c in codes.split(",")] if codes else None
    result = run_score_momentum(codes=code_list)
    click.echo(
        f"完了: scored={result['scored']} "
        f"skipped={result['skipped']} "
        f"elapsed={result['elapsed_sec']:.1f}s"
    )


# ══════════════════════════════════════════════════════════════════
#  その他トップレベルコマンド
# ══════════════════════════════════════════════════════════════════

@cli.command()
@click.option("--quarterly",  is_flag=True, default=False, help="Category B: 財務諸表更新（四半期）")
@click.option("--dividends",  is_flag=True, default=False, help="Category C: 配当履歴更新（半年）")
@click.option("--backfill",   is_flag=True, default=False, help="過去株価履歴を一括取得してDBに保存（初回・年1回）")
@click.option("--stocks",     is_flag=True, default=False, help="銘柄マスター更新（JPX公式から新規上場・廃止を同期）")
@click.option("--period",     default="2y", help="--backfill 時の取得期間（例: 1y, 2y, 5y）デフォルト: 2y")
@click.option("--force-all",  is_flag=True, default=False, help="TTL無視で全銘柄を強制更新")
@click.option("--codes",      default=None, help="カンマ区切りで銘柄を指定（例: 7203,9433）")
@click.option("--rules",      default=str(DEFAULT_RULES), help="ルール定義YAMLパス")
@click.option("--dry-run",    is_flag=True, default=False, help="DBへの書き込みを行わない")
@click.pass_context
def update(ctx, quarterly, dividends, backfill, stocks, period, force_all, codes, rules, dry_run):
    """データを更新してスコアを再計算する。

    \b
    デフォルト（オプションなし）: Category A 毎日更新
      - yf.download() で全銘柄終値を一括取得（1〜2分）

    \b
    --quarterly: Category B 四半期更新
      - 財務諸表・BS を再取得（fin_updated_at が90日以上前の銘柄）

    \b
    --dividends: Category C 半年更新
      - 配当履歴を再取得（div_updated_at が180日以上前の銘柄）

    \b
    --backfill: 過去株価履歴の一括取得（初回または年1回）
      - yf.download() で全銘柄の日次終値を過去2年分取得してDBに保存
      - 所要時間: 約10〜20分（全銘柄）
      - 例: findex update --backfill --period 2y

    \b
    --stocks: 銘柄マスター更新
      - JPX公式Excelから最新の上場銘柄一覧を取得してDBを同期
      - 新規上場銘柄をINSERT、廃止銘柄を is_active=0 にセット
      - 例: findex update --stocks
    """
    from pathlib import Path as P

    code_list = [c.strip() for c in codes.split(",")] if codes else None
    rules_path = P(rules)

    if stocks:
        click.echo("銘柄マスター更新を開始（JPX公式Excelから取得）...")
        from findex.updater.stocks import run_stocks_update
        result = run_stocks_update(dry_run=dry_run)
        click.echo(
            f"完了: inserted={result['inserted']} "
            f"updated={result['updated']} "
            f"deactivated={result['deactivated']} "
            f"total_jpx={result['total_jpx']} "
            f"elapsed={result['elapsed_sec']:.1f}s"
        )
        return
    elif backfill:
        click.echo(f"過去株価履歴取得を開始（period={period}）...")
        from findex.updater.daily import run_backfill
        result = run_backfill(period=period, codes=code_list, dry_run=dry_run)
        click.echo(
            f"完了: inserted={result['inserted']} "
            f"skipped={result.get('skipped', 0)} "
            f"failed={result['failed']} "
            f"elapsed={result['elapsed_sec']:.1f}s"
        )
        return
    elif quarterly:
        click.echo("Category B 四半期更新を開始...")
        from findex.updater.quarterly import run_quarterly_update
        result = run_quarterly_update(rules_path, code_list, force_all)
    elif dividends:
        click.echo("Category C 配当履歴更新を開始...")
        from findex.updater.dividends import run_dividend_update
        result = run_dividend_update(rules_path, code_list, force_all)
    else:
        click.echo("Category A 毎日更新を開始...")
        from findex.updater.daily import run_daily_update
        result = run_daily_update(rules_path, code_list, dry_run=dry_run)

    click.echo(
        f"完了: updated={result['updated']} "
        f"skipped={result.get('skipped', 0)} "
        f"failed={result['failed']} "
        f"elapsed={result['elapsed_sec']:.1f}s"
    )


@cli.command()
@click.option("--top",        default=10,   type=int,   help="検証するTOP銘柄数")
@click.option("--years",      default=3.0,  type=float, help="保有期間（年、例: 3.0）")
@click.option("--market",     default=None, help="市場でフィルタ（例: プライム）")
@click.option("--sector",     default=None, help="業種でフィルタ（例: 電気機器）")
@click.option("--min-yield",  default=None, type=float, help="最低配当利回り（例: 0.03 = 3%）")
@click.option("--min-no-cut", default=None, type=int,   help="最低連続非減配年数")
@click.option("--min-cap",    default=None, type=float, help="最低時価総額（兆円）")
@click.option("--max-cap",    default=None, type=float, help="最高時価総額（兆円）")
@click.option("--large-cap",  is_flag=True, default=False, help="大型株（5,000億円以上）")
@click.option("--mid-cap",    is_flag=True, default=False, help="中型株（1,000〜5,000億円）")
@click.option("--small-cap",  is_flag=True, default=False, help="小型株（1,000億円未満）")
@click.option("--max-per",    default=None, type=float, help="PER上限（例: 25）")
@click.option("--max-pbr",    default=None, type=float, help="PBR上限（例: 3.0）")
@click.option("--out",        default=None, help="CSV出力先パス")
@click.pass_context
def backtest(ctx, top, years, market, sector, min_yield, min_no_cut,
             min_cap, max_cap, large_cap, mid_cap, small_cap, max_per, max_pbr, out):
    """配当スコアTOP-N銘柄を過去X年保有した場合のリターンを検証する。

    \b
    例:
      findex backtest --min-yield 0.03 --large-cap --years 3
      findex backtest --sector 電気機器 --years 2
    """
    from findex.backtest import run_backtest
    run_backtest(
        top=top, years=years,
        market=market, sector=sector,
        min_yield=min_yield, min_no_cut=min_no_cut,
        min_cap=min_cap, max_cap=max_cap,
        large_cap=large_cap, mid_cap=mid_cap, small_cap=small_cap,
        max_per=max_per, max_pbr=max_pbr,
        out=out,
    )


@cli.command()
@click.pass_context
def setup(ctx):
    """APIキーを対話式に設定する（~/.findex/config.toml に保存）"""
    settings = ctx.obj["settings"]

    click.echo("Findex セットアップ")
    click.echo("APIキーを入力してください（Enterでスキップ）\n")

    edinet = click.prompt("EDINET API Key",
                          default=settings.edinet_api_key or "", show_default=False)
    jquants = click.prompt("J-Quants API Key",
                           default=settings.jquants_api_key or "", show_default=False)

    settings.edinet_api_key  = edinet  or settings.edinet_api_key
    settings.jquants_api_key = jquants or settings.jquants_api_key
    settings.save()

    click.echo(f"\n設定を保存しました: ~/.findex/config.toml")


@cli.command()
@click.option("--port", default=8080, type=int, help="ポート番号")
@click.option("--reload", is_flag=True, default=False, help="ホットリロード（開発用）")
def serve(port, reload):
    """ローカルGUIサーバーを起動する。

    \b
    例:
      findex serve              # http://localhost:8080
      findex serve --port 3000
      findex serve --reload     # 開発モード（コード変更を自動反映）
    """
    import uvicorn
    click.echo(f"Findex GUI: http://localhost:{port}")
    uvicorn.run(
        "findex.api.main:app",
        host="127.0.0.1",
        port=port,
        reload=reload,
    )


def main():
    cli()


# ══════════════════════════════════════════════════════════════════
#  findex score  — スコアリングバッチ（新テーブルへ書き込み）
# ══════════════════════════════════════════════════════════════════

@cli.group()
@click.pass_context
def score(ctx):
    """スコアリングバッチ（dividend_scores / momentum_scores テーブルへ書き込み）"""
    ctx.ensure_object(dict)


@score.command("dividend")
@click.option("--codes", default=None, help="対象銘柄（カンマ区切り）")
def score_dividend(codes):
    """配当スコアを dividend_scores テーブルに書き込む"""
    from findex.updater.score_dividend import run_score_dividend
    code_list = codes.split(",") if codes else None
    run_score_dividend(codes=code_list)


@score.command("momentum")
@click.option("--codes", default=None, help="対象銘柄（カンマ区切り）")
def score_momentum(codes):
    """モメンタムスコアを momentum_scores テーブルに書き込む"""
    from findex.updater.score_momentum import run_score_momentum
    code_list = codes.split(",") if codes else None
    run_score_momentum(codes=code_list)


# ══════════════════════════════════════════════════════════════════
#  findex post  — 増配ラボ SNS投稿テキスト生成（21テーマ）
# ══════════════════════════════════════════════════════════════════

@cli.group("post", invoke_without_command=True)
@click.pass_context
def post(ctx):
    """増配ラボ SNS投稿テキストを生成・投稿。

    \b
    例:
      findex post login                       # 初回：XにログインしてCookie保存
      findex post list                        # 全21テーマを一覧表示
      findex post no-cut                      # テキスト生成してクリップボードにコピー
      findex post no-cut --publish            # Xに自動投稿
      findex post no-cut --publish --dry-run  # ブラウザ確認のみ（投稿しない）
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@post.command("login")
def post_login():
    """XにログインしてセッションをX保存する（初回セットアップ）。"""
    from findex.x_poster import save_login
    save_login()


@post.command("list")
def post_list():
    """全21テーマのテーマ名一覧を表示する。"""
    from findex import poster

    categories: dict[str, list] = {}
    for slug, (_, label, cat) in poster.THEMES.items():
        categories.setdefault(cat, []).append((slug, label))

    click.echo("\n📋 増配ラボ 投稿テーマ一覧\n")
    for cat, items in categories.items():
        click.echo(f"  ▸ {cat}")
        for slug, label in items:
            click.echo(f"      {slug:<25}  {label}")
        click.echo()
    click.echo("使い方: findex post <テーマ名> [--publish] [--dry-run]\n")


# ── 21テーマを個別サブコマンドとして動的登録 ──
def _register_theme_commands():
    from findex import poster

    def _make_cmd(slug: str):
        _, label, cat = poster.THEMES[slug]

        @click.command(slug, help=f"{label}  [{cat}]")
        @click.option("--publish", is_flag=True, default=False, help="Xに自動投稿する")
        @click.option("--dry-run", is_flag=True, default=False, help="ブラウザ確認のみ（投稿しない）")
        def _cmd(publish, dry_run):
            import subprocess
            texts = poster.generate_by_theme(slug)
            click.echo(f"\n{label}  [{cat}]\n{'─' * 50}")
            for i, text in enumerate(texts, 1):
                click.echo(f"\n【投稿{i}】")
                click.echo(text)
            click.echo()

            # クリップボードには投稿1（フック）をコピー
            try:
                subprocess.run("pbcopy", input=texts[0].encode(), check=True)
                click.echo("📋 投稿1をクリップボードにコピーしました")
            except Exception:
                pass

            if publish or dry_run:
                from findex.x_poster import post_to_x
                mode = "DRY RUN" if dry_run else "投稿"
                click.echo(f"\n🐦 Xに{mode}します（スレッド形式）...")
                ok = post_to_x(texts, dry_run=dry_run)
                if not ok:
                    raise SystemExit(1)

        return _cmd

    for slug in poster.THEMES:
        post.add_command(_make_cmd(slug))


_register_theme_commands()
