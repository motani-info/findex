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


@cli.command()
@click.option("--rules",         default=str(DEFAULT_RULES), help="ルール定義YAMLパス")
@click.option("--top",           default=50,   help="表示する上位銘柄数")
@click.option("--out",           default=None, help="CSV出力先パス")
@click.option("--market",        default=None, help="市場でフィルタ（例: プライム）")
@click.option("--sector",        default=None, help="業種でフィルタ（例: 電気機器）")
@click.option("--limit",         default=None, type=int, help="取得銘柄数の上限（テスト用）")
@click.option("--delay",         default=0.5,  type=float, help="API呼び出し間隔（秒）")
@click.option("--workers",       default=1,    type=int,   help="並列取得数（最大5）")
@click.option("--no-etf",        is_flag=True, default=False, help="ETF・ETN・REITを除外")
@click.option("--no-dividends",  is_flag=True, default=False, help="配当履歴取得をスキップ")
@click.option("--no-edinet",     is_flag=True, default=False, help="EDINET取得をスキップ")
@click.option("--refresh",       is_flag=True, default=False, help="キャッシュを無視して再取得")
@click.option("--save-db",       is_flag=True, default=False, help="結果をDBに保存")
@click.pass_context
def run(ctx, rules, top, out, market, sector, limit, delay, workers,
        no_etf, no_dividends, no_edinet, refresh, save_db):
    """全銘柄を採点してランキングを表示する"""
    from findex.fetcher.master import fetch_stock_master
    from findex.runner import run_batch, save_to_db
    from findex.output.display import show_ranking, save_csv

    settings = ctx.obj["settings"]
    settings._workers = workers

    click.echo("銘柄マスターを取得中...")
    master = fetch_stock_master()

    if no_etf:
        master = master[~master["market"].str.contains("ETF|ETN|REIT|インフラ", na=False)]
    if market:
        master = master[master["market"].str.contains(market, na=False)]
    if sector:
        master = master[master["sector"].str.contains(sector, na=False)]
    if limit:
        master = master.head(limit)

    click.echo(f"{len(master)} 銘柄を処理します")

    click.echo("財務データを取得中...")
    result = run_batch(
        master=master,
        rules_path=Path(rules),
        settings=settings,
        delay=delay,
        no_dividends=no_dividends,
        no_edinet=no_edinet,
        refresh=refresh,
    )

    show_ranking(result.scores, top_n=top)
    click.echo(result.summary())

    if out:
        save_csv(result.scores, out)
        click.echo(f"CSV保存: {out}")

    if save_db:
        save_to_db(result, Path(rules), mode="run")
        click.echo("DBに保存しました")

    # 失敗率が20%超の場合は異常終了
    if result.fail_rate > 0.20:
        click.echo(f"[警告] 失敗率 {result.fail_rate:.1%} が閾値を超えました", err=True)
        sys.exit(1)


@cli.command()
@click.argument("codes", nargs=-1, required=True)
@click.option("--rules", default=str(DEFAULT_RULES), help="ルール定義YAMLパス")
@click.option("--delay", default=0.5, type=float, help="API呼び出し間隔（秒）")
@click.pass_context
def check(ctx, codes, rules, delay):
    """指定した銘柄コードのスコアを確認する"""
    import pandas as pd
    from findex.fetcher.fundamentals import fetch_fundamentals
    from findex.fetcher.dividends import fetch_dividends
    from findex.fetcher.roic import fetch_roic
    from findex.scorer.engine import load_rules, score

    codes = list(codes)
    click.echo(f"{codes} のデータを取得中...")

    fundamentals = fetch_fundamentals(codes, delay=delay)
    dividends    = fetch_dividends(codes, delay=delay)
    roic_df      = fetch_roic(codes, delay=delay)

    df = fundamentals.merge(dividends, on="code", how="left")
    df = df.merge(roic_df, on="code", how="left")

    rule_list = load_rules(rules)
    ranked = score(df, rule_list)

    score_cols = sorted([c for c in ranked.columns if c.startswith("_score_")
                         and c != "_score_json"])
    click.echo(ranked[["code", "total_score"] + score_cols].to_string(index=False))


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


def main():
    cli()
