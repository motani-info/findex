"""Phase 1 移行: 旧 findex.db（read-only）から再現困難なデータだけを v2 へ。

- dividend_annual の **events以外**（haitoukin バックフィル＝2000年以前。再取得不能）
- streak_overrides → result_overrides（汎用化。field別に展開）

price/financial/events配当は移行せず再取得（D7 §7・IMPLEMENTATION-PLAN Phase1）。
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime

from . import config


def _legacy_conn() -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{config.LEGACY_DB_PATH}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def migrate_dividend_annual(conn, codes: list[str] | None = None) -> int:
    """旧 dividend_annual の source!='events'（haitoukin等）を移行。confidence=present。"""
    now = datetime.now().isoformat(timespec="seconds")
    legacy = _legacy_conn()
    q = "SELECT code, fiscal_year, dps, source FROM dividend_annual WHERE source != 'events'"
    rows = legacy.execute(q).fetchall()
    legacy.close()
    if codes:
        cs = set(codes)
        rows = [r for r in rows if r["code"] in cs]
    n = 0
    for r in rows:
        conn.execute(
            """
            INSERT INTO dividend_annual (code, fiscal_year, dps, source, confidence, as_of, updated_at)
            VALUES (?,?,?,?, 'present', NULL, ?)
            ON CONFLICT(code, fiscal_year) DO NOTHING
            """,
            (r["code"], r["fiscal_year"], r["dps"], r["source"], now),
        )
        n += 1
    conn.commit()
    return n


def load_zai_overrides(conn, codes: list[str] | None = None) -> int:
    """golden_streaks_zai（zai公表の連続増配年数）を result_overrides に投入（D2.7）。

    旧 streak_overrides(12件) と同じzai記事が源で、その上位集合（19件）。**昇格のみ**の
    合成規則により、機械計算が一致する銘柄(KDDI等)には無影響。決算変更/分割アーティファクトで
    機械計算が壊れる銘柄(花王/ユニチャーム/三菱HC)を公表値で昇格させる。
    定義差（小林製薬=上場前から起算）は definition_note に残す。
    """
    now = datetime.now().isoformat(timespec="seconds")
    rows = list(csv.DictReader(config.GOLDEN_STREAKS.open(encoding="utf-8")))
    if codes:
        cs = set(codes)
        rows = [r for r in rows if r["code"].strip() in cs]
    notes = {"4967": "上場前から起算（定義差・zai）", "4452": "3月→12月決算変更2012で機械計算困難"}
    n = 0
    for r in rows:
        code = r["code"].strip()
        val = r.get("published_growth_years", "").strip()
        if not val:
            continue
        conn.execute(
            """INSERT INTO result_overrides
                 (code, field, value, as_of_fiscal_year, source, source_url,
                  definition_note, confidence, verified_at, verified_by)
               VALUES (?, 'consecutive_dividend_growth_years', ?, 2025, 'zai', ?, ?, 'single', ?, 'golden_zai')
               ON CONFLICT(code, field) DO UPDATE SET
                 value=excluded.value, source='zai', source_url=excluded.source_url,
                 definition_note=COALESCE(excluded.definition_note, result_overrides.definition_note),
                 verified_at=excluded.verified_at""",
            (code, float(val), r.get("source", "").strip(), notes.get(code), now),
        )
        n += 1
    conn.commit()
    return n


def migrate_overrides(conn, codes: list[str] | None = None) -> int:
    """旧 streak_overrides → result_overrides（field別に展開）。

    growth_years → consecutive_dividend_growth_years
    nocut_years  → consecutive_no_cut_years（NULLは展開しない）
    """
    now = datetime.now().isoformat(timespec="seconds")
    legacy = _legacy_conn()
    rows = legacy.execute("SELECT * FROM streak_overrides").fetchall()
    legacy.close()
    if codes:
        cs = set(codes)
        rows = [r for r in rows if r["code"] in cs]

    field_map = {
        "growth_years": "consecutive_dividend_growth_years",
        "nocut_years": "consecutive_no_cut_years",
    }
    n = 0
    for r in rows:
        for legacy_col, field in field_map.items():
            val = r[legacy_col]
            if val is None:
                continue
            conn.execute(
                """
                INSERT INTO result_overrides
                  (code, field, value, as_of_fiscal_year, source, source_url,
                   definition_note, confidence, verified_at, verified_by)
                VALUES (?,?,?,?, 'zai', ?, NULL, 'single', ?, 'migrate')
                ON CONFLICT(code, field) DO NOTHING
                """,
                (r["code"], field, float(val), r["as_of_fiscal_year"],
                 r["source_url"], r["verified_at"] or now),
            )
            n += 1
    conn.commit()
    return n
