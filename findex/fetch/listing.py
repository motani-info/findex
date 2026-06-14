"""上場日・設立日の取得（kabutan）。2000年問題の打ち切り判定に必須の独立シグナル。

docs/design/pre2000-data.md §3 第1層。容疑者band優先 → 最終的に全銘柄。
不変データなので初回1回でよい。礼儀スリープ1.5秒。

NOTE: 実パース（HTMLから「上場」「設立」を抽出）は未実装。骨格のみ。
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import FetchPolicy, RateLimitedFetcher, RateLimitError


@dataclass
class ListingInfo:
    code: str
    listing_date: str | None  # "YYYY-MM-DD"
    founded_date: str | None


class ListingFetcher(RateLimitedFetcher[ListingInfo]):
    name = "listing_kabutan"
    # スクレイピングなので逐次・礼儀スリープ。バッチは小さく。
    policy = FetchPolicy(
        batch_size=50,
        sleep_between_batches=0.0,
        sleep_between_items=1.5,
        max_retries=4,
    )

    URL = "https://kabutan.jp/stock/?code={code}"

    def fetch_one(self, code: str) -> ListingInfo:
        # TODO: requests + BeautifulSoup で「上場」「設立」フィールドを抽出。
        # 429/403 を検知したら RateLimitError を送出する。
        raise NotImplementedError("kabutan parser is not implemented yet (scaffold)")
