"""現在発行済株数の取得（yfinance fast_info.shares → share_count）。

findexは報告財務×分割補正で株数を導出するが、重複split・期末直前分割・増減資で壊れる
（T1是正で判明＝Yahoo発行済と最大3.5x乖離）。yfinance/Yahooは現在発行済株数を直接持つので
これを権威ある真値として保持し、現在断面の mcap/PER/PBR の基準に使う（分割の日付演算に依存しない）。

全銘柄取得はレート制限の最大ハードル（鉄則）。RateLimitedFetcher 経由で
backoff/resume/progress/サーキットブレーカーに乗せる（単発 requests を直書きしない）。
fast_info は info より軽い呼び出し。
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import yfinance as yf

from .base import FetchPolicy, RateLimitedFetcher

log = logging.getLogger(__name__)


class SharesFetcher(RateLimitedFetcher[dict]):
    name = "shares_yfinance"
    policy = FetchPolicy(batch_size=100, sleep_between_batches=2.0, sleep_between_items=0.2,
                         max_retries=4)

    def __init__(self, conn):
        self.conn = conn

    def fetch_one(self, code: str) -> dict:
        shares = None
        try:
            fi = yf.Ticker(f"{code}.T").fast_info
            shares = fi.shares if fi is not None else None
        except Exception:
            shares = None
        # 取得不能/空は「データなし」の正常結果として扱い、既存行は上書きしない（空で消さない）。
        if not shares or shares <= 0:
            return {"rows": 0, "skipped_empty": True}
        now = datetime.now().isoformat(timespec="seconds")
        today = date.today().isoformat()
        self.conn.execute(
            "INSERT INTO share_count (code, shares, source, as_of, collected_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(code) DO UPDATE SET shares=excluded.shares, source=excluded.source, "
            "as_of=excluded.as_of, collected_at=excluded.collected_at",
            (code, int(shares), "yfinance", today, now),
        )
        self.conn.commit()
        return {"rows": 1}

    def is_rate_limit(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return super().is_rate_limit(exc) or "too many requests" in msg


def build_shares(conn, codes: list[str], *, resume: bool = True) -> dict:
    """share_count を resume 安全に構築（per-stock upsert→commit→checkpoint）。"""
    res = SharesFetcher(conn).run(codes, resume=resume)
    total = sum(r["rows"] for r in res.ok.values())
    return {"ok": len(res.ok), "failed": len(res.failed), "skipped": len(res.skipped),
            "shares_rows": total, "fetch_summary": res.summary}
