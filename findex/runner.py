"""バッチ実行ロジック: fetcherを束ねてスコアリング・DB保存を行う"""
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from findex.fetcher.dividends import fetch_dividends
from findex.fetcher.fundamentals import fetch_fundamentals
from findex.fetcher.roic import fetch_roic
from findex.fetcher.fetch_all import fetch_all
from findex.scorer.engine import load_rules, score
from findex.settings import Settings


@dataclass
class RunResult:
    scores: pd.DataFrame
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)   # code → エラーメッセージ
    skipped: list[str] = field(default_factory=list)

    @property
    def fail_rate(self) -> float:
        total = len(self.succeeded) + len(self.failed) + len(self.skipped)
        return len(self.failed) / total if total else 0.0

    def summary(self) -> str:
        return (
            f"完了: 成功={len(self.succeeded)} "
            f"失敗={len(self.failed)} "
            f"スキップ={len(self.skipped)}"
        )


def run_batch(
    master: pd.DataFrame,
    rules_path: Path,
    settings: Settings,
    delay: float = 0.5,
    no_dividends: bool = False,
    no_edinet: bool = False,
    refresh: bool = False,
) -> RunResult:
    """銘柄マスターを受け取り、全指標を取得してスコアリングする。

    Args:
        master:       fetch_stock_master() の返り値
        rules_path:   rules.yaml のパス
        settings:     Settings（APIキー等）
        delay:        API呼び出し間隔（秒）
        no_dividends: 配当履歴取得をスキップ
        no_edinet:    EDINET取得をスキップ
        refresh:      キャッシュを無視して再取得

    Returns:
        RunResult（scores DataFrame + 成功/失敗/スキップリスト）
    """
    codes = master["code"].tolist()

    # ── データ取得 ──────────────────────────────────────────────
    # 1銘柄1回のAPI呼び出しで全指標を一括取得
    all_data = fetch_all(codes, delay=delay, refresh=refresh)
    df = master.merge(all_data, on="code", how="left")

    if not no_edinet:
        try:
            from findex.fetcher.edinet import fetch_edinet
            edinet_df = fetch_edinet(codes, settings=settings, delay=delay)
            df = df.merge(edinet_df, on="code", how="left")
        except Exception:
            pass  # EDINET未実装の場合はスキップ

    # ── スコアリング ─────────────────────────────────────────────
    rules = load_rules(rules_path)
    ranked = score(df, rules)

    # succeeded / failed / skipped の判定
    succeeded = ranked[ranked["total_score"] > 0]["code"].tolist()
    failed: dict[str, str] = {}
    skipped: list[str] = []

    return RunResult(scores=ranked, succeeded=succeeded,
                     failed=failed, skipped=skipped)


def save_to_db(result: RunResult, rules_path: Path, mode: str = "run",
               subset: str | None = None) -> None:
    """RunResult を SQLite に保存する。"""
    from datetime import date
    import findex.db as db

    conn = db.get_db()

    # stocks テーブルに銘柄マスターを先に upsert（FK制約のため）
    master_cols = [c for c in result.scores.columns
                   if c in ("code", "name", "market", "sector")]
    db.upsert_stocks(conn, result.scores[master_cols])

    rule_version_id = db.get_or_create_rule_version(conn, rules_path)
    run_id = db.start_run(conn, mode=mode, subset=subset)
    scored_at = date.today().isoformat()

    for _, row in result.scores.iterrows():
        code = str(row["code"])
        if db.score_exists(conn, code, scored_at, rule_version_id):
            result.skipped.append(code)
            continue

        score_json_str = row.get("_score_json")
        if score_json_str:
            import json
            score_json = json.loads(score_json_str)
        else:
            score_json = {"total": row.get("total_score", 0)}

        raw_fields = [
            "payout_ratio", "eps_growth_5y", "equity_ratio",
            "roe", "operating_margin", "div_yield", "net_cash_per", "mix_coefficient",
            "consecutive_no_cut_years", "consecutive_dividend_growth_years",
            "dividend_growth_10y_cagr", "dividend_reliability",
            "fcf_payout_coverage", "revenue_growth_5y_cagr",
            "roic_minus_wacc", "retained_earnings_div_ratio",
            "per", "pbr", "market_cap",
        ]
        raw_json = {f: row.get(f) for f in raw_fields if row.get(f) is not None}

        db.insert_score(conn, code, scored_at, rule_version_id, score_json, raw_json)

    conn.commit()
    db.finish_run(conn, run_id,
                  succeeded=len(result.succeeded),
                  failed=len(result.failed),
                  skipped=len(result.skipped),
                  exit_code=0)
    conn.close()
