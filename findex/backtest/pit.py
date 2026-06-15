"""PIT（Point-in-Time）スコア再現（D8 §1.1・§4）。

「2015年時点のスコア」は2015年時点で入手可能なデータだけで再現する（look-ahead排除）。
設計の一方向フローを保つため、**評価層（derive→score）の本体は同一**を使い、入力だけを
as_of でフィルタした in-memory DB に差し替えて回す。結果を backtest_scores に格納。

PIT フィルタ:
  price_history.date <= as_of（N225ベンチマーク含む）／financial_snapshots.fiscal_year <= y
  dividend_annual.fiscal_year <= y／result_overrides.as_of_fiscal_year <= y（後年公表値を使わない）
  beta は as_of 時点の株価で再回帰（compute_beta(as_of=...)）。
※ stocks（上場日/業種/会計基準）は時点不変の事実としてそのまま使う。
※ 生存バイアス: 廃止株は無料データに無く本ユニバースは現役のみ＝検証は生存者標本（PROGRESS §6）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from ..db.database import SCHEMA_PATH
from ..derive.compute import (
    build_beta,
    build_dividend_metrics,
    build_financial_metrics,
    build_grades,
    build_price_metrics,
    build_roic,
    build_streaks,
)
from ..score.engine import build_scores
from .outcomes import DEFAULT_HORIZONS, as_of_grid  # noqa: F401 (grid再利用)

_BENCHMARK = "N225"


def _copy(mem, main, table, cols, where, params=()):
    rows = main.execute(f"SELECT {','.join(cols)} FROM {table} {where}", params).fetchall()
    if rows:
        ph = ",".join("?" * len(cols))
        mem.executemany(
            f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})",
            [tuple(r) for r in rows],
        )


def _table_cols(conn, table) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def build_pit_db(main, codes: list[str], as_of: str) -> sqlite3.Connection:
    """as_of でフィルタした in-memory DB を作る（評価層の入力ビュー）。"""
    y = int(as_of[:4])
    mem = sqlite3.connect(":memory:")
    mem.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    targets = list(codes)
    ph = ",".join("?" * len(targets))

    sc = _table_cols(main, "stocks")
    _copy(mem, main, "stocks", sc, f"WHERE code IN ({ph})", targets)

    da = _table_cols(main, "dividend_annual")
    _copy(mem, main, "dividend_annual", da,
          f"WHERE code IN ({ph}) AND fiscal_year <= ?", (*targets, y))

    fs = _table_cols(main, "financial_snapshots")
    _copy(mem, main, "financial_snapshots", fs,
          f"WHERE code IN ({ph}) AND fiscal_year <= ?", (*targets, y))
    mem.execute("UPDATE financial_snapshots SET beta=NULL")  # PIT再回帰のため消す

    ph_px = ",".join("?" * (len(targets) + 1))  # +N225
    pc = _table_cols(main, "price_history")
    _copy(mem, main, "price_history", pc,
          f"WHERE code IN ({ph_px}) AND date <= ?", (*targets, _BENCHMARK, as_of))

    ro = _table_cols(main, "result_overrides")
    _copy(mem, main, "result_overrides", ro,
          f"WHERE code IN ({ph}) AND as_of_fiscal_year <= ?", (*targets, y))

    mem.commit()
    return mem


def _derive_and_score_pit(mem, codes: list[str], as_of: str) -> None:
    build_streaks(mem, codes)
    build_dividend_metrics(mem, codes)
    build_financial_metrics(mem, codes)
    build_price_metrics(mem, codes)
    build_beta(mem, codes, as_of=as_of)
    build_roic(mem, codes)
    build_grades(mem, codes)
    build_scores(mem, codes)


def build_pit_scores(conn, codes: list[str], *, grid: list[str] | None = None) -> dict:
    """各 as_of で PIT 入力→derive→score を回し backtest_scores に格納。"""
    grid = grid or as_of_grid()
    now = datetime.now().isoformat(timespec="seconds")
    # rule_version（現行rules.yaml）を記録
    from ..score.engine import _ensure_rule_version, load_rules
    rule_version_id = _ensure_rule_version(conn, load_rules().get("version_tag", "v4"))
    cur = conn.execute(
        "INSERT INTO backtest_runs (rule_version_id, as_of_grid, universe_def, params_json, created_at) "
        "VALUES (?,?,?,?,?)",
        (rule_version_id, f"{grid[0]}..{grid[-1]}", "cohort_survivors",
         json.dumps({"codes": len(codes), "note": "survivorship-limited (PROGRESS §6)"}), now),
    )
    run_id = cur.lastrowid

    n_scores = 0
    per_asof = []
    for as_of in grid:
        mem = build_pit_db(conn, codes, as_of)
        try:
            _derive_and_score_pit(mem, codes, as_of)
            rows = mem.execute(
                "SELECT code, total_score, score_json, grade_dividend, grade_valuation, "
                "grade_health, grade_capital FROM dividend_scores"
            ).fetchall()
        finally:
            mem.close()
        for (code, total, sj, gd, gv, gh, gc) in rows:
            conn.execute(
                "INSERT INTO backtest_scores (run_id, code, as_of_date, total_score, score_json, "
                "grade_dividend, grade_valuation, grade_health, grade_capital) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(run_id, code, as_of_date) DO UPDATE SET total_score=excluded.total_score, "
                "score_json=excluded.score_json, grade_dividend=excluded.grade_dividend, "
                "grade_valuation=excluded.grade_valuation, grade_health=excluded.grade_health, "
                "grade_capital=excluded.grade_capital",
                (run_id, code, as_of, total, sj, gd, gv, gh, gc),
            )
            n_scores += 1
        per_asof.append((as_of, len(rows)))
    conn.commit()
    return {"run_id": run_id, "rule_version_id": rule_version_id, "scores": n_scores,
            "as_of_points": len(grid), "per_asof": per_asof}
