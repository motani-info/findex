"""株価取得（yfinance）。日次更新の主役。

yfinance は2並列が上限・バッチ間スリープ必須（地雷9）。実DLは未実装、骨格のみ。
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import FetchPolicy, RateLimitedFetcher


@dataclass
class PricePoint:
    code: str
    date: str
    close: float
    volume: int | None


class PriceFetcher(RateLimitedFetcher[list[PricePoint]]):
    name = "prices_yfinance"
    policy = FetchPolicy(batch_size=200, sleep_between_batches=10.0, max_retries=5)

    def fetch_one(self, code: str) -> list[PricePoint]:
        # TODO: yf.Ticker(f"{code}.T").history(...) で終値を取得。
        # 本番は yf.download() で銘柄をまとめて取得し、ここはフォールバック経路にする想定。
        raise NotImplementedError("yfinance price fetch is not implemented yet (scaffold)")
