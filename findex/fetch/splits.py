"""株式分割イベント取得（yfinance .splits → stock_splits）。

close_adj（分割調整済み）と financial_snapshots EPS/BPS/株数（報告値）の基準ズレを
derive 層（doc11是正）で補正するための分割情報を収集する。逆分割（株式併合・ratio<1.0）も
収集する（除外すると株数/1株指標が併合前基準で残り PER/PBR/時価総額が桁違いに過大化する）。

全銘柄取得はレート制限の最大ハードル（鉄則）。RateLimitedFetcher 経由で
backoff/resume/progress/サーキットブレーカーに乗せる（単発 requests を直書きしない）。
"""
from __future__ import annotations

import logging
from datetime import datetime

import yfinance as yf

from .base import FetchPolicy, RateLimitedFetcher

log = logging.getLogger(__name__)


class SplitsFetcher(RateLimitedFetcher[dict]):
    name = "splits_yfinance"
    # yfinance .splits は軽い呼び出しだが全件はブロックされ得る＝保守レート＋backoff。
    policy = FetchPolicy(batch_size=100, sleep_between_batches=2.0, sleep_between_items=0.2,
                         max_retries=4)

    def __init__(self, conn):
        self.conn = conn

    def fetch_one(self, code: str) -> dict:
        splits = yf.Ticker(f"{code}.T").splits
        now = datetime.now().isoformat(timespec="seconds")
        # yfinance は分割データ無しで None / 空Series を返し得るが、これは「分割なし」と
        # 「一過性の空応答（レート制限/瞬断）」を区別できない。全件スキャン中の散発的な空応答で
        # 洗替（DELETE→INSERT）が走ると、実在する分割を持つ銘柄の既存行を消し去り doc11補正が
        # 無効化される（過去事故）。分割は歴史的に追記のみ＝消えることはないので、
        # 空応答では既存行に一切触れずスキップする（誤記録の是正はデータありの応答時のみ）。
        if splits is None or len(splits) == 0:
            return {"rows": 0, "skipped_empty": True}
        rows = []
        for dt, ratio in splits.items():
            r = float(ratio)
            if r <= 0:
                continue  # データ異常のみ除外（逆分割 ratio<1.0 は算入する）
            rows.append((code, dt.strftime("%Y-%m-%d"), r, "yfinance", now))
        if not rows:
            return {"rows": 0, "skipped_empty": True}
        # 実データ取得時のみ code 単位で洗替（削除→挿入）＝逆分割の取りこぼしや古い誤記録を是正。
        self.conn.execute("DELETE FROM stock_splits WHERE code=?", (code,))
        self.conn.executemany(
            "INSERT INTO stock_splits (code, date, ratio, source, collected_at) "
            "VALUES (?,?,?,?,?)",
            rows,
        )
        self.conn.commit()
        return {"rows": len(rows)}

    def is_rate_limit(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return super().is_rate_limit(exc) or "too many requests" in msg


def build_splits(conn, codes: list[str], *, resume: bool = True) -> dict:
    """stock_splits を resume 安全に構築（per-stock 洗替→commit→checkpoint）。"""
    res = SplitsFetcher(conn).run(codes, resume=resume)
    total = sum(r["rows"] for r in res.ok.values())
    return {"ok": len(res.ok), "failed": len(res.failed), "skipped": len(res.skipped),
            "splits_rows": total, "fetch_summary": res.summary}


def fetch_splits_for_codes(conn, codes: list[str], sleep: float = 0.1) -> int:
    """少数銘柄の即時取得（--codes 向け・常に最新へ洗替＝resume無視）。戻り値は挿入行数。"""
    return build_splits(conn, list(codes), resume=False)["splits_rows"]
