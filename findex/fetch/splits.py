"""株式分割イベント取得（yfinance .splits）。

close_adj（分割調整済み）とfinancial_snapshots EPS/BPS（報告値＝未調整）の
基準ズレを derive 層で補正するための分割情報を収集する。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

import yfinance as yf

log = logging.getLogger(__name__)


def fetch_splits_for_codes(conn, codes: list[str], sleep: float = 0.1) -> int:
    """指定銘柄の分割イベントを取得し stock_splits に UPSERT。戻り値は挿入行数。"""
    inserted = 0
    now = datetime.now().isoformat(timespec="seconds")
    for i, code in enumerate(codes):
        try:
            ticker = yf.Ticker(f"{code}.T")
            splits = ticker.splits
            if splits.empty:
                continue
            for dt, ratio in splits.items():
                if ratio <= 0:
                    continue  # データ異常のみ除外
                # 逆分割（株式併合・ratio<1.0）も算入する（doc11是正）。除外すると株数/1株指標が
                # 併合前基準で残り、PER/PBR/時価総額が桁違いに過大化する（例: 1491中外鉱業20:1併合）。
                split_date = dt.strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT OR REPLACE INTO stock_splits (code, date, ratio, source, collected_at) "
                    "VALUES (?, ?, ?, 'yfinance', ?)",
                    (code, split_date, float(ratio), now),
                )
                inserted += 1
        except Exception as e:
            log.warning("splits %s: %s", code, e)
        if sleep and i % 50 == 49:
            time.sleep(sleep)
    conn.commit()
    return inserted
