"""銘柄マスター更新: JPX公式Excelから最新の上場銘柄一覧を取得してDBを同期する。

処理内容:
- JPX公式ExcelからDataFrameを取得
- 既存レコードはUPDATE（name/market/sector/updated_at）
- 新規銘柄はINSERT
- 廃止銘柄（JPXリストに存在しないコード）は is_active=0 フラグをセット
  ※ is_active カラムがなければ自動追加する
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from findex.db import get_db


def _ensure_is_active_column(conn: sqlite3.Connection) -> None:
    """is_active カラムが存在しなければ追加する（デフォルト 1）。"""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(stocks)").fetchall()]
    if "is_active" not in cols:
        try:
            conn.execute("ALTER TABLE stocks ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
            conn.commit()
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                raise RuntimeError(
                    "DBが別プロセスにロックされています。他の findex プロセスが終了してから再実行してください。"
                ) from e
            raise


def run_stocks_update(dry_run: bool = False) -> dict:
    """JPX銘柄マスターを取得してDBを同期する。

    Returns:
        inserted, updated, deactivated, elapsed_sec
    """
    from findex.fetcher.master import fetch_stock_master

    t0 = time.time()

    print("JPX上場銘柄マスターを取得中...")
    df = fetch_stock_master()
    print(f"  取得件数: {len(df)} 銘柄")

    conn = get_db()
    _ensure_is_active_column(conn)

    # 既存の全コードセットを取得
    existing = {
        row[0]: {"name": row[1], "market": row[2], "sector": row[3]}
        for row in conn.execute("SELECT code, name, market, sector FROM stocks").fetchall()
    }

    now = datetime.now().isoformat(timespec="seconds")
    jpx_codes = set()
    inserted = 0
    updated = 0

    for _, row in df.iterrows():
        code = str(row["code"]).strip()
        name = str(row.get("name", "") or "").strip()
        market = str(row.get("market", "") or "").strip()
        sector = str(row.get("sector", "") or "").strip()

        if not code or code == "nan":
            continue

        jpx_codes.add(code)

        if code not in existing:
            if not dry_run:
                conn.execute(
                    "INSERT OR IGNORE INTO stocks (code, name, market, sector, updated_at, is_active) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (code, name, market, sector, now),
                )
            inserted += 1
        else:
            ex = existing[code]
            if ex["name"] != name or ex["market"] != market or ex["sector"] != sector:
                if not dry_run:
                    conn.execute(
                        "UPDATE stocks SET name=?, market=?, sector=?, updated_at=?, is_active=1 WHERE code=?",
                        (name, market, sector, now, code),
                    )
                    updated += 1
                else:
                    updated += 1
            else:
                # 情報変化なしでも is_active を 1 に戻す（廃止→再上場対応）
                if not dry_run:
                    conn.execute(
                        "UPDATE stocks SET is_active=1, updated_at=? WHERE code=?",
                        (now, code),
                    )

    # 廃止銘柄: JPXリストに存在しないコードを is_active=0 にする
    deactivated_codes = set(existing.keys()) - jpx_codes
    deactivated = len(deactivated_codes)
    if deactivated_codes and not dry_run:
        conn.executemany(
            "UPDATE stocks SET is_active=0, updated_at=? WHERE code=?",
            [(now, code) for code in deactivated_codes],
        )

    if not dry_run:
        conn.commit()

    conn.close()

    elapsed = time.time() - t0
    return {
        "inserted": inserted,
        "updated": updated,
        "deactivated": deactivated,
        "total_jpx": len(jpx_codes),
        "elapsed_sec": elapsed,
    }
