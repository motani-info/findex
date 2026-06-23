#!/usr/bin/env python
"""financial_snapshots.disclosed_date を J-Quants だけで埋める軽量バックフィル（doc11是正の全件展開 step b）。

disclosed_date は分割補正の基準日（compute._split_adjustment_factor）。既存行は NULL なので、
**分割を持つ銘柄だけ**（factor に効くのはそこだけ）を対象に J-Quants fins/summary から開示日を補完する。
EDINET 深いBSは触らない＝`financials --all`（~9h）より桁違いに速い。

RateLimitedFetcher 経由＝backoff/resume/progress/サーキットブレーカー（鉄則）。`findex progress
disclosed_date_backfill` で監視可。実行: `uv run python scripts/backfill_disclosed_date.py [--all]`。
既定は stock_splits を持つ銘柄のみ。--all で全銘柄。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from findex import config  # noqa: E402
from findex.db import connect  # noqa: E402
from findex.fetch.base import FetchPolicy, RateLimitedFetcher  # noqa: E402
from findex.fetch.jquants import JQuantsClient, parse_fy_records  # noqa: E402


class DisclosedDateBackfill(RateLimitedFetcher[dict]):
    name = "disclosed_date_backfill"
    policy = FetchPolicy(batch_size=50, sleep_between_batches=2.0, sleep_between_items=0.2,
                         max_retries=4)

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.client = JQuantsClient()

    def fetch_one(self, code: str) -> dict:
        fins = parse_fy_records(self.client.fins_summary(code))
        n = 0
        for f in fins:
            if f.disclosed_date:
                cur = self.conn.execute(
                    "UPDATE financial_snapshots SET disclosed_date=? WHERE code=? AND fiscal_year=?",
                    (f.disclosed_date, code, f.fiscal_year),
                )
                n += cur.rowcount
        self.conn.commit()
        return {"updated": n}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="全銘柄（既定は分割保有銘柄のみ）")
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    conn = connect()
    if args.all:
        codes = [r[0] for r in conn.execute("SELECT code FROM stocks ORDER BY code")]
    else:
        codes = [r[0] for r in conn.execute("SELECT DISTINCT code FROM stock_splits ORDER BY code")]
    print(f"disclosed_date バックフィル対象: {len(codes)}銘柄"
          f"（{'全銘柄' if args.all else '分割保有のみ'}）")
    res = DisclosedDateBackfill(conn).run(codes, resume=not args.no_resume)
    updated = sum(r["updated"] for r in res.ok.values())
    print(f"完了: {res.summary} / disclosed_date 更新行={updated}")
    conn.close()


if __name__ == "__main__":
    main()
