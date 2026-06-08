"""モメンタムスコアリングバッチ: price_history + stock_fundamentals → momentum_scores テーブル書き込み

既存の momentum.py のスコア計算ロジックを使い、
momentum_scores テーブルに永続化する。yfinance呼び出しなし（DB完結）。
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from itertools import groupby

import pandas as pd

from findex.db import get_db, upsert_momentum_score
from findex.momentum import _calc_momentum_score

DB_PATH = None  # get_db() を使うのでパス不要


def run_momentum_scoring(
    codes: list[str] | None = None,
    scored_at: str | None = None,
) -> dict:
    """
    モメンタムスコアリングバッチ。

    price_history + stock_fundamentals → _calc_momentum_score() → momentum_scores upsert

    Returns:
        {"scored": int, "skipped": int, "failed": int, "elapsed_sec": float}
    """
    t0 = time.time()
    conn = get_db()
    today = scored_at or date.today().isoformat()
    d3m = (date.today() - timedelta(days=91)).isoformat()
    d12m = (date.today() - timedelta(days=366)).isoformat()

    # 対象銘柄
    if codes:
        placeholders = ",".join(["?"] * len(codes))
        target_rows = conn.execute(
            f"SELECT code FROM stocks WHERE code IN ({placeholders})", codes
        ).fetchall()
    else:
        target_rows = conn.execute("SELECT code FROM stocks").fetchall()
    all_codes = [r[0] for r in target_rows]

    if not all_codes:
        print("対象銘柄なし", flush=True)
        conn.close()
        return {"scored": 0, "skipped": 0, "failed": 0, "elapsed_sec": 0}

    # TOPIX基準リターン（1306）
    topix_rows = conn.execute(
        "SELECT date, close FROM price_history WHERE code='1306' ORDER BY date"
    ).fetchall()
    topix_ret_3m = topix_ret_12m = None
    if len(topix_rows) >= 2:
        df_t = pd.DataFrame(topix_rows, columns=["date", "close"]).set_index("date")
        t_latest = float(df_t["close"].iloc[-1])
        t_past3 = df_t[df_t.index <= d3m]
        t_past12 = df_t[df_t.index <= d12m]
        if not t_past3.empty:
            topix_ret_3m = t_latest / float(t_past3["close"].iloc[-1]) - 1
        if not t_past12.empty:
            topix_ret_12m = t_latest / float(t_past12["close"].iloc[-1]) - 1

    # price_history 一括取得
    placeholders = ",".join(["?"] * len(all_codes))
    ph_rows = conn.execute(
        f"SELECT code, date, close FROM price_history WHERE code IN ({placeholders}) ORDER BY code, date",
        all_codes,
    ).fetchall()

    # 銘柄ごとの価格指標を計算
    price_data: dict[str, dict] = {}
    for code, group in groupby(ph_rows, key=lambda r: r[0]):
        records = list(group)
        if len(records) < 10:
            continue
        df_p = pd.DataFrame(records, columns=["code", "date", "close"]).set_index("date")
        latest = float(df_p["close"].iloc[-1])
        past3 = df_p[df_p.index <= d3m]
        past12 = df_p[df_p.index <= d12m]
        hi_range = df_p[df_p.index >= d12m]["close"]

        ret_3m = (latest / float(past3["close"].iloc[-1]) - 1) if not past3.empty else None
        ret_12m = (latest / float(past12["close"].iloc[-1]) - 1) if not past12.empty else None
        hi52 = float(hi_range.max()) if not hi_range.empty else None

        price_data[code] = {
            "ret_3m": ret_3m,
            "ret_12m": ret_12m,
            "rel_ret_3m": (ret_3m - topix_ret_3m) if ret_3m is not None and topix_ret_3m is not None else ret_3m,
            "rel_ret_12m": (ret_12m - topix_ret_12m) if ret_12m is not None and topix_ret_12m is not None else ret_12m,
            "hi52_ratio": (latest / hi52) if hi52 else None,
        }

    # 業績データ
    fund_rows = conn.execute(
        f"SELECT code, revenue_growth_5y_cagr, eps_growth_5y, roe, operating_margin "
        f"FROM stock_fundamentals WHERE code IN ({placeholders})",
        all_codes,
    ).fetchall()
    fund_map = {r[0]: {"rev_growth": r[1], "eps_growth": r[2], "roe": r[3], "operating_margin": r[4]}
                for r in fund_rows}

    # スコアリング
    scored = skipped = failed = 0
    for code in all_codes:
        if code not in price_data:
            skipped += 1
            continue
        pd_ = price_data[code]
        fund = fund_map.get(code, {})
        fields = {**pd_, **fund, "vol_ratio": None}

        try:
            score_detail = _calc_momentum_score(fields)
            breakdown = {k: v for k, v in score_detail.items() if k != "total"}
            # フィールド名を正規化（日本語名→field名へマッピング）
            field_map = {
                "3M相対リターン": "rel_ret_3m",
                "52週高値比率": "hi52_ratio",
                "12M相対リターン": "rel_ret_12m",
                "売上成長率": "rev_growth",
                "EPS成長率": "eps_growth",
                "ROE": "roe",
                "営業利益率": "operating_margin",
                "出来高増加率": "vol_ratio",
            }
            normalized = {field_map.get(k, k): v for k, v in breakdown.items()}
            upsert_momentum_score(conn, code, today, score_detail["total"], normalized)
            scored += 1
        except Exception:
            failed += 1

    conn.commit()
    conn.close()

    elapsed = time.time() - t0
    print(
        f"モメンタムスコアリング完了: scored={scored} skipped={skipped} "
        f"failed={failed} elapsed={elapsed:.1f}s",
        flush=True,
    )
    return {"scored": scored, "skipped": skipped, "failed": failed, "elapsed_sec": elapsed}
