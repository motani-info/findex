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


# ── Yahoo!ファイナンス(日本)プロフィール: 真の上場年月日＋設立年月日 ──────────
# yfinanceの firstTradeDate は国内株で2000-2001床に張り付き古い銘柄の真値を欠く。
# Yahoo!JPプロフィールは「上場年月日」を一次に近い形で持つ（花王=1949年5月＝年月のみ等も）。
# これを真値ソースとし、yfinance床NULLを置き換える。設立年月日も founded_date に補完。
_YAHOO_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.9",
}
_JP_DATE_RE = r"([0-9]{4})年([0-9]{1,2})月(?:([0-9]{1,2})日)?"


def parse_jp_date(s: str | None) -> str | None:
    """『1994年10月27日』『1949年5月』→ ISO日付。日が無ければ01日（古い上場は年月のみ）。"""
    if not s:
        return None
    import re

    m = re.search(_JP_DATE_RE, s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
    return f"{y:04d}-{mo:02d}-{d:02d}"


@dataclass
class YahooListingInfo:
    code: str
    listing_date: str | None        # 真の上場日（年月のみは01日）
    founded_date: str | None        # 設立年月日
    source: str


class YahooListingFetcher(RateLimitedFetcher[YahooListingInfo]):
    name = "listing_yahoo"
    policy = FetchPolicy(batch_size=50, sleep_between_batches=3.0, sleep_between_items=0.8, max_retries=4)

    def fetch_one(self, code: str) -> YahooListingInfo:
        import re

        import requests
        from bs4 import BeautifulSoup

        url = f"https://finance.yahoo.co.jp/quote/{code}.T/profile"
        r = requests.get(url, headers=_YAHOO_UA, timeout=20)
        r.raise_for_status()
        text = BeautifulSoup(r.text, "html.parser").get_text("|", strip=True)

        def grab(label: str) -> str | None:
            m = re.search(rf"{label}[|]?\s*{_JP_DATE_RE}", text)
            return parse_jp_date(m.group(0)) if m else None

        return YahooListingInfo(code, grab("上場年月日"), grab("設立年月日"), "yahoo_profile")

    def is_rate_limit(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return super().is_rate_limit(exc) or "429" in msg or "too many" in msg

    def is_complete(self, code: str, result: "YahooListingInfo") -> bool:
        """完全性ゲート(F1): 上場日・設立日とも取れなければ done を刻まない。

        実会社のプロフィールは上場年月日か設立年月日を必ず持つ。両方 None は
        ソフトブロック/ページ構造変化/JS化などのパース失敗の可能性が高い→再取得対象に
        残す（HTTP200の空応答を黙って done 扱いする silent-drop を防ぐ）。恒久的に
        両方Nullなら verify が未充足として surface する。"""
        return bool(result.listing_date or result.founded_date)


def update_listing_yahoo(conn, codes: list[str], *, resume: bool = True) -> dict:
    """Yahoo!JPプロフィールで真の上場日＋設立日を取得し stocks に格納（yfinance床を置換）。"""
    now = datetime.now().isoformat(timespec="seconds")
    res = YahooListingFetcher().run(codes, resume=resume)
    listing_set = founded_set = corrected = both_null = 0
    for code, info in res.ok.items():
        old = conn.execute("SELECT listing_date FROM stocks WHERE code=?", (code,)).fetchone()
        old_ld = old[0] if old else None
        if info.listing_date:
            conn.execute(
                "UPDATE stocks SET listing_date=?, updated_at=? WHERE code=?",
                (info.listing_date, now, code),
            )
            listing_set += 1
            if old_ld and old_ld[:7] != info.listing_date[:7]:
                corrected += 1  # yfinance床/旧値と年月が違う＝訂正
        if info.founded_date:
            conn.execute(
                "UPDATE stocks SET founded_date=?, updated_at=? WHERE code=?",
                (info.founded_date, now, code),
            )
            founded_set += 1
        if not info.listing_date and not info.founded_date:
            both_null += 1
    conn.commit()
    return {
        "ok": len(res.ok), "failed": len(res.failed),
        "listing_set": listing_set, "founded_set": founded_set,
        "corrected_from_old": corrected, "both_null": both_null,
        "failures": res.failed,
    }


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
