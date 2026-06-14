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


# 取得系コマンド共通のオプション
def subset_options(f):
    f = click.option("--codes", default=None, help="カンマ区切りの銘柄（例: 7203,9433）")(f)
    f = click.option("--cohort", is_flag=True, help="検証コホート（約30社）のみ対象にする")(f)
    return f


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


@main.command("rank")
@click.option("--top", default=30, help="表示件数")
@click.option("--market", default=None)
@click.option("--sector", default=None)
@click.option("--min-yield", type=float, default=None)
@click.option("--min-no-cut", type=int, default=None)
@click.option("--out", type=click.Path(), default=None, help="CSV出力先")
def rank_cmd(top, market, sector, min_yield, min_no_cut, out) -> None:
    """スコアランキングを表示する。"""
    console.print("[dim]評価層は骨格段階です（score.* を実装中）。[/dim]")


@main.command("check")
@click.argument("codes", nargs=-1, required=True)
def check_cmd(codes) -> None:
    """個別銘柄の詳細を確認する。"""
    console.print(f"[dim]check {', '.join(codes)} — 骨格段階[/dim]")


@main.command("post")
@click.argument("theme")
@click.option("--dry-run", is_flag=True, help="品質ゲート＋生成のみ（投稿しない）")
def post_cmd(theme, dry_run) -> None:
    """X投稿（Playwright）。品質ゲートを通らなければ拒否。"""
    console.print(f"[dim]post {theme} dry_run={dry_run} — 骨格段階（post.* を実装中）[/dim]")


if __name__ == "__main__":
    main()
