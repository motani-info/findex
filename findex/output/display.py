"""ランキング結果の表示・出力"""
from pathlib import Path
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()


def _fmt(v, fmt=".1f", fallback="-"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return fallback
    try:
        return format(v, fmt)
    except (TypeError, ValueError):
        return str(v)


def show_ranking(df: pd.DataFrame, top_n: int = 50) -> None:
    table = Table(title=f"Findex ランキング（上位 {top_n} 銘柄）", show_lines=False)
    table.add_column("順位", style="bold yellow", justify="right")
    table.add_column("コード", style="cyan")
    table.add_column("銘柄名")
    table.add_column("市場")
    table.add_column("業種")
    table.add_column("スコア", style="bold green", justify="right")
    table.add_column("ROE%", justify="right")
    table.add_column("利回り%", justify="right")
    table.add_column("配当性向%", justify="right")
    table.add_column("営業利益率%", justify="right")

    for i, row in df.head(top_n).iterrows():
        roe = row.get("roe")
        roe_str = _fmt(roe * 100 if roe is not None and not pd.isna(roe) else None)
        div = row.get("div_yield")
        div_str = _fmt(div * 100 if div is not None and not pd.isna(div) else None)
        pr = row.get("payout_ratio")
        pr_str = _fmt(pr * 100 if pr is not None and not pd.isna(pr) else None)
        om = row.get("operating_margin")
        om_str = _fmt(om * 100 if om is not None and not pd.isna(om) else None)

        table.add_row(
            str(i + 1),
            str(row.get("code", "")),
            str(row.get("name", "")),
            str(row.get("market", "")),
            str(row.get("sector", "")),
            f"{row.get('total_score', 0):.1f}",
            roe_str,
            div_str,
            pr_str,
            om_str,
        )

    console.print(table)


def save_csv(df: pd.DataFrame, path: str | Path) -> None:
    exclude = {c for c in df.columns if c.startswith("_score_") or c == "raw_score"}
    out_cols = [c for c in df.columns if c not in exclude]
    df[out_cols].to_csv(path, index=False, encoding="utf-8-sig")
    console.print(f"[green]保存しました:[/green] {path}")
