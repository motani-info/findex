"""findex CLI（click）。--codes / --cohort で取得対象を絞れる（レート制限対策）。

コマンドは骨格。レイヤ実装が進むにつれ中身を埋める。
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from . import __version__, config
from .cohort import load_cohort
from .db import backup_db, init_db

console = Console()


def _resolve_codes(codes: str | None, cohort: bool) -> list[str] | None:
    """--codes / --cohort から対象銘柄を決める。どちらも無ければ None（=全銘柄）。"""
    if cohort:
        from .cohort import cohort_codes

        return cohort_codes()
    if codes:
        return [c.strip() for c in codes.split(",") if c.strip()]
    return None


def _resolve_target(codes: str | None, cohort: bool, all_codes: bool) -> list[str] | None:
    """--codes / --cohort / --all から対象を決める。--all は stocks 全件（重い・明示用）。"""
    if all_codes:
        from .db import connect

        c = connect()
        try:
            t = [r[0] for r in c.execute("SELECT code FROM stocks ORDER BY code").fetchall()]
        finally:
            c.close()
        console.print(f"[yellow]全銘柄モード[/yellow]: {len(t)}社（resume可・完全性ゲートで未取得は再取得対象に残る）")
        return t
    return _resolve_codes(codes, cohort)


# 取得系コマンド共通のオプション
def subset_options(f):
    f = click.option("--codes", default=None, help="カンマ区切りの銘柄（例: 7203,9433）")(f)
    f = click.option("--cohort", is_flag=True, help="検証コホート（約30社）のみ対象にする")(f)
    return f


def all_option(f):
    return click.option("--all", "all_codes", is_flag=True,
                        help="全銘柄（stocks 全件）を対象にする（重いので明示）")(f)


@click.group()
@click.version_option(__version__, prog_name="findex")
def main() -> None:
    """日本株スコアリング・ランキングツール（v2）。"""


@main.command("initdb")
def initdb_cmd() -> None:
    """新スキーマでDBを初期化する（冪等）。"""
    backup = backup_db()
    if backup:
        console.print(f"[dim]backup: {backup}[/dim]")
    init_db()
    console.print(f"[green]✓[/green] initialized {config.DB_PATH}")


@main.command("cohort")
def cohort_cmd() -> None:
    """検証コホート（約30社）を表示する。"""
    rows = load_cohort()
    table = Table(title=f"検証コホート（{len(rows)}社）")
    for col in ("code", "name", "category", "expected", "behavior"):
        table.add_column(col, overflow="fold")
    for c in rows:
        table.add_row(
            c.code,
            c.name,
            c.category,
            str(c.expected_growth_years or "—"),
            c.expected_behavior,
        )
    console.print(table)


@main.command("master")
@subset_options
def master_cmd(codes, cohort) -> None:
    """stocks をJPX一覧＋EDINETコードリストから構築（Phase1）。"""
    from .db import connect
    from .fetch.master import build_stocks

    target = _resolve_codes(codes, cohort)
    conn = connect()
    try:
        stats = build_stocks(conn, target)
    finally:
        conn.close()
    console.print(
        f"[green]✓[/green] master: universe={stats['universe']} "
        f"new={stats['inserted']} upd={stats['updated']} "
        f"(EDINET会計メタ {stats['edinet_meta_codes']}件)"
    )


@main.command("listing")
@subset_options
@click.option("--all", "all_codes", is_flag=True, help="全銘柄（stocks 全件）を対象にする（重いスクレイプを明示）")
@click.option("--no-resume", is_flag=True, help="チェックポイントを無視して最初から")
@click.option("--source", type=click.Choice(["yfinance", "yahoo"]), default="yahoo",
              help="上場日ソース（yahoo=真値・設立日も補完／yfinance=床判定）")
def listing_cmd(codes, cohort, all_codes, no_resume, source) -> None:
    """上場日(listing_date)を取得（打ち切り判定の鍵）。既定=Yahoo!JP真値。"""
    from .db import connect
    from .fetch.listing import update_listing, update_listing_yahoo

    conn = connect()
    if all_codes:
        target = [r[0] for r in conn.execute("SELECT code FROM stocks ORDER BY code").fetchall()]
        console.print(f"[yellow]全銘柄モード[/yellow]: {len(target)}社（resume可・完全性ゲートで未取得は再取得対象に残る）")
    else:
        target = _resolve_codes(codes, cohort)
    if not target:
        conn.close()
        console.print("[red]--codes / --cohort / --all のいずれかを指定してください（全銘柄は重いので明示）[/red]")
        return
    try:
        if source == "yahoo":
            s = update_listing_yahoo(conn, target, resume=not no_resume)
            console.print(
                f"[green]✓[/green] listing(Yahoo): 上場日={s['listing_set']} 設立日={s['founded_set']} "
                f"旧値訂正={s['corrected_from_old']} 両方不明={s['both_null']} failed={s['failed']}"
            )
        else:
            s = update_listing(conn, target, resume=not no_resume)
            console.print(
                f"[green]✓[/green] listing(yfinance): 真の上場日={s['true_listing_dates']} "
                f"床(≤2000・補完待ち)={s['floor_unknown']} 既存温存={s['preserved_existing']} "
                f"failed={s['failed']}"
            )
    finally:
        conn.close()


@main.command("prices")
@subset_options
@all_option
@click.option("--no-resume", is_flag=True, help="チェックポイントを無視して最初から")
@click.option("--benchmark", is_flag=True, help="市場ベンチマーク(日経225)のみ取得（beta用）")
def prices_cmd(codes, cohort, all_codes, no_resume, benchmark) -> None:
    """株価履歴を2000年遡及で取得（yfinance分割調整Close）（Phase2-d）。"""
    from .db import connect
    from .fetch.prices import build_prices, fetch_benchmark

    conn = connect()
    if benchmark:
        try:
            b = fetch_benchmark(conn)
            console.print(f"[green]✓[/green] benchmark N225: 行={b['rows']:,} [{b['first']}〜{b['last']}]")
        finally:
            conn.close()
        return

    target = _resolve_target(codes, cohort, all_codes)
    if not target:
        conn.close()
        console.print("[red]--codes / --cohort / --all のいずれかを指定してください（全銘柄は重い）[/red]")
        return
    try:
        stats = build_prices(conn, target, resume=not no_resume)
    finally:
        conn.close()
    console.print(
        f"[green]✓[/green] prices: ok={stats['ok']} failed={stats['failed']} "
        f"行={stats['rows']:,} 外れ値={stats['outliers']}"
    )


@main.command("dividends")
@subset_options
@all_option
@click.option("--no-resume", is_flag=True, help="チェックポイントを無視して最初から")
def dividends_cmd(codes, cohort, all_codes, no_resume) -> None:
    """配当イベント再取得→dividend_annual(events)＋能動洗浄（Phase2-e）。"""
    from .db import connect
    from .fetch.dividends import build_dividends

    target = _resolve_target(codes, cohort, all_codes)
    if not target:
        console.print("[red]--codes / --cohort / --all のいずれかを指定してください（全銘柄は重い）[/red]")
        return
    conn = connect()
    try:
        stats = build_dividends(conn, target, resume=not no_resume)
    finally:
        conn.close()
    console.print(
        f"[green]✓[/green] dividends: ok={stats['ok']} 無配={stats['no_dividend']} "
        f"events={stats['events']:,} annual={stats['annual_rows']} "
        f"洗浄フラグ(review)={stats['review_flags']} failed={stats['failed']}"
    )


@main.command("financials")
@subset_options
@all_option
@click.option("--no-resume", is_flag=True, help="チェックポイントを無視して最初から")
def financials_cmd(codes, cohort, all_codes, no_resume) -> None:
    """financial_snapshots を構築（J-Quants基礎＋EDINET深いBS）（Phase2-c）。"""
    from .db import connect
    from .fetch.financials import build_financials

    target = _resolve_target(codes, cohort, all_codes)
    if not target:
        console.print("[red]--codes / --cohort / --all のいずれかを指定してください（全銘柄は重い）[/red]")
        return
    conn = connect()
    try:
        stats = build_financials(conn, target, resume=not no_resume)
    finally:
        conn.close()
    console.print(
        f"[green]✓[/green] financials: J-Quants[{stats['jq']}] EDINET[{stats['edinet']}] "
        f"行={stats['snapshot_rows']} 深いBS付={stats['rows_with_deep']} "
        f"会計基準設定={stats['accounting_standard_set']}"
    )


@main.command("derive")
@subset_options
@click.option("--what", default="all",
              help="導出対象（all/streaks/dividends/financials/prices/beta/roic/grades）")
def derive_cmd(codes, cohort, what) -> None:
    """導出層: 前段テーブル→computed_metrics（Phase3）。"""
    from .db import connect
    from .derive.compute import (
        build_beta,
        build_dividend_metrics,
        build_financial_metrics,
        build_grades,
        build_price_metrics,
        build_roic,
        build_streaks,
    )

    target = _resolve_codes(codes, cohort)
    if not target:
        console.print("[red]--codes か --cohort を指定してください[/red]")
        return
    conn = connect()
    try:
        if what in ("all", "streaks"):
            s = build_streaks(conn, target)
            console.print(
                f"[green]✓[/green] streaks: rows={s['rows']} 打ち切り(N+)={s['censored']} "
                f"override昇格={s['overridden']}"
            )
        if what in ("all", "dividends"):
            d = build_dividend_metrics(conn, target)
            console.print(f"[green]✓[/green] dividends: rows={d['rows']} 増配の質={d['quality_dist']}")
        if what in ("all", "financials"):
            f = build_financial_metrics(conn, target)
            oc = f["ok_counts"]
            console.print(
                f"[green]✓[/green] financials: rows={f['rows']} "
                f"ROE={oc['roe']} 自己資本比率={oc['equity_ratio']} 営業益率={oc['operating_margin']} "
                f"EPS成長={oc['eps_growth_5y']} 売上CAGR={oc['revenue_growth_5y_cagr']} "
                f"DOE={oc['doe']} FCFカバ={oc['fcf_payout_coverage']}"
            )
        if what in ("all", "prices"):
            p = build_price_metrics(conn, target)
            oc = p["ok_counts"]
            console.print(
                f"[green]✓[/green] prices: rows={p['rows']} "
                f"PER={oc['per']} PBR={oc['pbr']} 時価総額={oc['current_market_cap']} "
                f"配当利回り={oc['div_yield']} ミックス={oc['mix_coefficient']} ネットキャッシュPER={oc['net_cash_per']}"
            )
        if what in ("all", "beta"):
            b = build_beta(conn, target)
            console.print(
                f"[green]✓[/green] beta: rows={b['rows']} "
                f"中央値={b['median']} 範囲=[{b['min']}, {b['max']}]"
            )
        if what in ("all", "roic"):
            r = build_roic(conn, target)
            console.print(f"[green]✓[/green] roic: rows={r['rows']} ROIC−WACC算出={r['ok']}")
        if what in ("all", "grades"):
            g = build_grades(conn, target)
            id_ = g["identity"]
            for claim, d in g["dist"].items():
                console.print(f"[green]✓[/green] {claim}: {d}")
            console.print(
                f"[green]✓[/green] identity_ok: 一致={id_['ok']} 不一致={id_['mismatch']} "
                f"判定不能={id_['na']}（rows={g['rows']}）"
            )
    finally:
        conn.close()


@main.command("rebuild-dividends")
@subset_options
def rebuild_dividends_cmd(codes, cohort) -> None:
    """保存済みevents から dividend_annual を再構築＋haitoukin接合洗浄（再取得なし）。"""
    from .db import connect
    from .fetch.dividends import rebuild_and_cleanse

    target = _resolve_codes(codes, cohort)
    if not target:
        console.print("[red]--codes か --cohort を指定してください[/red]")
        return
    conn = connect()
    try:
        stats = rebuild_and_cleanse(conn, target)
    finally:
        conn.close()
    console.print(f"[green]✓[/green] rebuild: annual={stats['annual_rows']} review={stats['review_flags']}")


@main.command("migrate")
@subset_options
def migrate_cmd(codes, cohort) -> None:
    """旧DBから再現困難なデータを移行（haitoukin配当・override）（Phase1）。"""
    from .db import connect
    from .migrate import migrate_dividend_annual, migrate_overrides

    target = _resolve_codes(codes, cohort)
    conn = connect()
    try:
        n_div = migrate_dividend_annual(conn, target)
        n_ovr = migrate_overrides(conn, target)
    finally:
        conn.close()
    console.print(f"[green]✓[/green] migrate: dividend_annual(non-events)={n_div} overrides={n_ovr}")


@main.command("update")
@subset_options
@click.option("--quarterly", is_flag=True, help="四半期: 財務諸表を更新")
@click.option("--dividends", is_flag=True, help="半年: 配当履歴を更新")
@click.option("--no-resume", is_flag=True, help="チェックポイントを無視して最初から")
def update_cmd(codes, cohort, quarterly, dividends, no_resume) -> None:
    """データ取得・更新（株価/財務/配当）。"""
    target = _resolve_codes(codes, cohort)
    scope = f"{len(target)}銘柄" if target else "全銘柄"
    kind = "四半期(財務)" if quarterly else "半年(配当)" if dividends else "日次(株価)"
    console.print(f"[yellow]update[/yellow] {kind} / 対象: {scope} / resume={not no_resume}")
    console.print("[dim]取得層は骨格段階です（fetch.* を実装中）。[/dim]")


@main.command("score")
@subset_options
@click.option("--top", default=30, help="表示件数")
def score_cmd(codes, cohort, top) -> None:
    """評価層: computed_metrics を v4 ルールで採点→dividend_scores（Phase4）。"""
    from .db import connect
    from .score.engine import build_scores

    target = _resolve_codes(codes, cohort)
    if not target:
        console.print("[red]--codes か --cohort を指定してください[/red]")
        return
    names = {c.code: c.name for c in load_cohort()}
    conn = connect()
    try:
        res = build_scores(conn, target)
    finally:
        conn.close()
    table = Table(title=f"v4スコア（{res['version_tag']} / {res['rows']}社）")
    for col in ("#", "code", "name", "score", "配当", "バリュ", "財務", "資本", "指標数"):
        table.add_column(col, overflow="fold")
    for i, r in enumerate(res["ranking"][:top], 1):
        table.add_row(
            str(i), r["code"], names.get(r["code"], "")[:12], f"{r['total']:.1f}",
            r["grade_dividend"] or "—", r["grade_valuation"] or "—",
            r["grade_health"] or "—", r["grade_capital"] or "—", str(r["n_scored"]),
        )
    console.print(table)
    console.print(
        f"[dim]rule_version_id={res['rule_version_id']} scored_at={res['scored_at']}[/dim]"
    )


@main.command("backtest")
@subset_options
@click.option("--what", default="outcomes", help="バックテスト対象（outcomes/...）")
def backtest_cmd(codes, cohort, what) -> None:
    """バックテスト（D8）: PIT入力→前方アウトカム→メトリクス（Phase5.5）。"""
    from .db import connect

    target = _resolve_codes(codes, cohort)
    if not target:
        console.print("[red]--codes か --cohort を指定してください[/red]")
        return
    conn = connect()
    try:
        if what in ("all", "outcomes"):
            from .backtest.outcomes import build_outcomes

            o = build_outcomes(conn, target)
            console.print(
                f"[green]✓[/green] outcomes: rows={o['rows']} "
                f"as_of={o['grid'][0]}〜{o['grid'][1]} horizons={o['horizons']} "
                f"減配[無={o['cut_dist'][0]}/有={o['cut_dist'][1]}]"
            )
        if what in ("all", "pit"):
            from .backtest.pit import build_pit_scores

            p = build_pit_scores(conn, target)
            console.print(
                f"[green]✓[/green] pit: run_id={p['run_id']} PITスコア={p['scores']} "
                f"as_of点={p['as_of_points']}"
            )
    finally:
        conn.close()


@main.command("rank")
@click.option("--top", default=30, help="表示件数")
@click.option("--market", default=None)
@click.option("--sector", default=None)
@click.option("--min-yield", type=float, default=None)
@click.option("--min-no-cut", type=int, default=None)
@click.option("--out", type=click.Path(), default=None, help="CSV出力先")
def rank_cmd(top, market, sector, min_yield, min_no_cut, out) -> None:
    """保存済みスコアからランキングを表示する。"""
    console.print("[dim]rank は dividend_scores の表示専用（score で採点後に使用）。実装中。[/dim]")


@main.command("check")
@click.argument("codes", nargs=-1, required=True)
def check_cmd(codes) -> None:
    """個別銘柄の詳細を確認する。"""
    console.print(f"[dim]check {', '.join(codes)} — 骨格段階[/dim]")


@main.command("report")
@subset_options
@click.option("--out", type=click.Path(), default=None, help="出力HTMLパス（既定: docs/html/report.html）")
def report_cmd(codes, cohort, out) -> None:
    """検証済みデータから閲覧可能なHTMLレポートを生成（MVP出力・品質ゲート遵守）。"""
    from pathlib import Path

    from .db import connect
    from .post.report import write_report

    target = _resolve_codes(codes, cohort)
    if not target:
        console.print("[red]--codes か --cohort を指定してください[/red]")
        return
    conn = connect()
    try:
        res = write_report(conn, target, Path(out) if out else None)
    finally:
        conn.close()
    console.print(
        f"[green]✓[/green] report: {res['stocks']}社 → {res['path']} ({res['bytes']:,} bytes)"
    )
    console.print(f"[dim]open {res['path']}[/dim]")


@main.command("progress")
@click.argument("name", required=False)
def progress_cmd(name) -> None:
    """背景実行中の取得進捗を表示（{name}.progress.json を読む・AI不要で確認できる）。"""
    import json as _json
    from datetime import datetime as _dt

    d = config.CHECKPOINT_DIR
    files = sorted(d.glob(f"{name}.progress.json" if name else "*.progress.json"))
    if not files:
        console.print(f"[dim]進捗ファイルなし（{d}）[/dim]")
        return
    for f in files:
        try:
            p = _json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            console.print(f"[red]{f.name} 読込失敗: {e}[/red]")
            continue
        # 最終更新からの経過（停止判定の補助）
        try:
            age = (_dt.now() - _dt.fromisoformat(p["updated_at"])).total_seconds()
            age_s = f"{int(age)}秒前" if age < 120 else f"{int(age / 60)}分前"
        except Exception:
            age = None
            age_s = "?"
        # running=True でも更新が古ければプロセス死亡（kill -9 等で finally 未実行）の疑い
        if p.get("running") and (age is None or age > 120):
            state = "[red]応答なし(停止疑い)[/red]"
        elif p.get("running"):
            state = "[green]実行中[/green]"
        else:
            state = "[yellow]停止[/yellow]"
        eta = p.get("eta_sec")
        eta_s = (f"{eta // 60}分{eta % 60}秒" if eta else "—") if eta is not None else "?"
        console.print(
            f"[bold]{p['name']}[/bold] {state}  "
            f"{p['done_overall']}/{p['total']} ({p['percent']}%)  "
            f"ok={p['ok']} failed={p['failed']} 再開skip={p['skipped_resume']}  "
            f"{p['rate_per_min']}件/分 ETA{eta_s}  更新{age_s}"
        )
        if p.get("last_error"):
            console.print(f"   [dim]最新エラー: {p['last_error']}[/dim]")


@main.command("verify")
@subset_options
@click.option("--all", "all_codes", is_flag=True, help="全銘柄（stocks 全件）を検収対象にする")
def verify_cmd(codes, cohort, all_codes) -> None:
    """洗替の検収（読み取り専用）。カバレッジ・golden整合・seam穴・review率・status分布。"""
    from .db import connect
    from .verify import run_verify

    conn = connect()
    try:
        if all_codes:
            target = None  # None = 全universe
        else:
            target = _resolve_codes(codes, cohort)
            if not target:
                console.print("[red]--codes / --cohort / --all のいずれかを指定してください[/red]")
                return
        rep = run_verify(conn, target)
    finally:
        conn.close()

    cov = rep["coverage"]
    t = cov["total"]
    tbl = Table(title=f"カバレッジ（{t}社）", show_header=True)
    tbl.add_column("層"); tbl.add_column("揃った社数", justify="right"); tbl.add_column("率", justify="right")
    for k in ("listing_date", "price_history", "financial_snapshots", "dividend_annual", "computed_metrics"):
        n = cov[k]
        tbl.add_row(k, str(n), f"{n / t * 100:.1f}%" if t else "—")
    console.print(tbl)

    g = rep["golden"]
    mark = "[green]✓[/green]" if rep["golden_ok"] else "[red]✗[/red]"
    console.print(f"{mark} golden整合: 検査{g['checked']} 一致{g['matched']} 不整合{len(g['mismatches'])}")
    for mm in g["mismatches"][:10]:
        console.print(f"   [red]✗[/red] {mm['code']}: 公表{mm['published']} > 導出{mm['derived']}")

    sm = rep["seam"]
    console.print(
        f"配当seam穴: 配当あり{sm['codes_with_dividends']}社 / 歯抜けあり{sm['codes_with_gaps']}社 "
        f"（FY2000接合穴{sm['fy2000_seam']}社） 多い欠落年={sm['top_gap_years']}"
    )
    rv = rep["review"]
    console.print(f"review隔離: {rv['codes_with_review']}社 / {rv['review_rows']}行（単年アーティファクト）")
    console.print(f"status分布: {rep['status_dist']}")


@main.command("post")
@click.argument("theme")
@subset_options
@click.option("--top", type=int, default=10, help="ランキング上位N（既定10）")
@click.option("--publish", is_flag=True, help="実際にXへ投稿する（既定はdraftのみ）")
def post_cmd(theme, codes, cohort, top, publish) -> None:
    """X投稿（Playwright・画像主役型）。既定はdraft生成のみ・--publishで実投稿。

    品質ゲート（status=ok / N+表示 / 出典 / グレード併示 / 140字）を通らなければ拒否。
    """
    from pathlib import Path

    from .db import connect
    from .post.image import render_html_to_png
    from .post.themes import THEMES

    builder = THEMES.get(theme)
    if builder is None:
        console.print(f"[red]未知のテーマ: {theme}[/red] （利用可能: {', '.join(THEMES)}）")
        return
    target = _resolve_codes(codes, cohort)
    if not target:
        console.print("[red]--codes か --cohort を指定してください[/red]")
        return

    conn = connect()
    try:
        post = builder(conn, target, top_n=top)
    finally:
        conn.close()

    gates = post["gates"]
    console.print(f"[bold]theme[/bold]: {post['theme']} ・ 対象 {len(target)}社 → 該当 {gates['eligible_count']}社")
    console.print(f"[bold]本文[/bold]（{gates['body_weighted_len']}/140字）:\n{post['body']}")
    console.print("[bold]品質ゲート[/bold]: " + "  ".join(
        f"{'[green]✓[/green]' if v else '[red]✗[/red]'}{k}" if isinstance(v, bool) else f"{k}={v}"
        for k, v in gates.items()
    ))

    if not gates["passed"]:
        console.print("[red]✗ 品質ゲート不通過 — 投稿しません（沈黙は許容・誤発信は不可）[/red]")
        return

    img_path = config.PROJECT_ROOT / "docs" / "html" / f"post_{theme}.png"
    render_html_to_png(post["image_html"], img_path)
    console.print(f"[green]✓[/green] 画像生成: {img_path}")

    if not publish:
        console.print("[yellow]draft（投稿せず）[/yellow] — 内容を確認し、問題なければ [bold]--publish[/bold] で投稿します。")
        console.print(f"[dim]使用claim {len(post['claims'])}件（事後監査用・status/source付き）[/dim]")
        return

    from .post.poster import post_to_x
    ok = post_to_x(post["body"], images=[Path(img_path)])
    console.print("[green]✓ 投稿完了[/green]" if ok else "[red]✗ 投稿失敗[/red]")


if __name__ == "__main__":
    main()
