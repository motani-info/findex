"""上場日の取得 — 打ち切り判定の独立シグナル（地雷7・旧0%）。

主ソース=yfinance `firstTradeDate`。yfinance国内株のデータ床は **2000-2001年の年初**に
バンドで張り付く（実測: 2000-01-04 / 2001-01-01 / 2001-01-04）。古い銘柄はここに
張り付くため、これらの床日付は真の上場日ではない（=≤2001で不明）。
→ 床カットオフ(2001-01-04)以前 or 1月1日(休場日=不可能な取引日)の firstTradeDate は
  **listing_date を NULL** にし、kabutan補完（Playwright）の対象とする。
→ 非NULL = 確証ある真の上場日（床より後の実取引日）。NULL = ≤2001・真値不明（補完待ち）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

import yfinance as yf

from .base import FetchPolicy, RateLimitedFetcher

# yfinance国内株のデータ床バンド。これ以前の firstTradeDate は真の上場日でない（実測）
YF_FLOOR_CUTOFF = date(2001, 1, 4)


def _is_floor_artifact(d: date) -> bool:
    """firstTradeDate が yfinanceのデータ床アーティファクトか（真値でない）。"""
    if d <= YF_FLOOR_CUTOFF:
        return True
    if (d.month, d.day) == (1, 1):  # 元日は休場＝実取引日たり得ない床値
        return True
    return False


@dataclass
class ListingInfo:
    code: str
    listing_date: str | None        # 確証ある真の上場日（>床）。床/不明はNone
    first_trade_date: str | None     # yfinance生値（床判定の監査用）
    source: str


class ListingFetcher(RateLimitedFetcher[ListingInfo]):
    name = "listing_yfinance"
    policy = FetchPolicy(
        batch_size=100,
        sleep_between_batches=2.0,
        sleep_between_items=0.3,
        max_retries=4,
    )

    def fetch_one(self, code: str) -> ListingInfo:
        info = yf.Ticker(f"{code}.T").info
        ms = info.get("firstTradeDateMilliseconds")
        if ms is None:
            ep = info.get("firstTradeDateEpochUtc")
            ms = ep * 1000 if ep else None
        if ms is None:
            return ListingInfo(code, None, None, "yfinance")
        d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
        ftd = d.isoformat()
        listing = None if _is_floor_artifact(d) else ftd  # 床バンド=真値不明→NULL
        return ListingInfo(code, listing, ftd, "yfinance")

    def is_rate_limit(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return super().is_rate_limit(exc) or "too many requests" in msg


def update_listing(conn, codes: list[str], *, resume: bool = True) -> dict:
    """yfinanceで listing_date を取得し stocks にupsert（NULL床は据え置き）。"""
    from datetime import datetime as _dt

    now = _dt.now().isoformat(timespec="seconds")
    res = ListingFetcher().run(codes, resume=resume)
    true_dates = floor = 0
    for code, info in res.ok.items():
        if info.listing_date:
            conn.execute(
                "UPDATE stocks SET listing_date=?, updated_at=? WHERE code=?",
                (info.listing_date, now, code),
            )
            true_dates += 1
        else:
            # ≤2001床・真値不明（kabutan補完待ち）。誤値が残らぬよう明示的にNULLへ
            conn.execute(
                "UPDATE stocks SET listing_date=NULL, updated_at=? WHERE code=?",
                (now, code),
            )
            floor += 1
    conn.commit()
    return {
        "ok": len(res.ok),
        "failed": len(res.failed),
        "true_listing_dates": true_dates,
        "floor_unknown": floor,  # listing_date IS NULL のまま（補完対象）
        "failures": res.failed,
    }
