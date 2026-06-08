"""J-Quants API フェッチャー
全銘柄の財務・配当・株価データを一括取得する（yfinanceの代替）。
"""
from .fetch import fetch_all_jquants
from .client import JQuantsClient

__all__ = ["fetch_all_jquants", "JQuantsClient"]
