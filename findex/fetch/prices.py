"""株価履歴の取得（2000年遡及）→ price_history。

yfinance `Close`(auto_adjust=False) は **分割調整済み・配当未調整**（実証: NTT 25:1分割の
前後で連続）。これは PER/PBR/取得利回り(YoC) に正しい系列（配当調整は per-share を歪める）。
→ close_adj には yfinance Close を入れる（"Adj Close"=配当込みは使わない）。

外れ値（隣接日で±50%超の跳ね）は分割漏れ/誤データの疑いとして件数を記録（捨てない）。
J-Quants は現契約2年窓のため、長期はyfinance主・J-Quantsは直近補完/突合（design-review #3）。
"""
from __future__ import annotations

from datetime import datetime

import yfinance as yf

from .base import FetchPolicy, RateLimitedFetcher

OUTLIER_RATIO = 0.5  # 隣接日で±50%超=要確認


class PriceFetcher(RateLimitedFetcher[dict]):
    name = "prices_yfinance"
    policy = FetchPolicy(batch_size=50, sleep_between_batches=2.0, sleep_between_items=0.3, max_retries=4)

    def __init__(self, conn):
        self.conn = conn

    def fetch_one(self, code: str) -> dict:
        h = yf.Ticker(f"{code}.T").history(period="max", auto_adjust=False)
        if h.empty:
            return {"rows": 0, "outliers": 0}
        h = h[["Close", "Volume"]].dropna(subset=["Close"])
        h = h[h["Close"] > 0]
        if h.empty:
            return {"rows": 0, "outliers": 0}
        # 外れ値検知（隣接日リターン）
        ret = h["Close"].pct_change().abs()
        outliers = int((ret > OUTLIER_RATIO).sum())
        rows = [
            (code, idx.date().isoformat(), float(c), int(v) if v == v else None, "yfinance")
            for idx, c, v in zip(h.index, h["Close"], h["Volume"])
        ]
        self.conn.executemany(
            """INSERT INTO price_history (code, date, close_adj, volume, source)
               VALUES (?,?,?,?,?)
               ON CONFLICT(code, date) DO UPDATE SET
                 close_adj=excluded.close_adj, volume=excluded.volume, source=excluded.source""",
            rows,
        )
        self.conn.commit()
        return {"rows": len(rows), "outliers": outliers,
                "first": rows[0][1], "last": rows[-1][1]}

    def is_rate_limit(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return super().is_rate_limit(exc) or "too many requests" in msg


def build_prices(conn, codes: list[str], *, resume: bool = True) -> dict:
    res = PriceFetcher(conn).run(codes, resume=resume)
    total_rows = sum(r["rows"] for r in res.ok.values())
    total_out = sum(r["outliers"] for r in res.ok.values())
    # first_data_date を price_history から更新（導出値）
    now = datetime.now().isoformat(timespec="seconds")
    for code in res.ok:
        row = conn.execute("SELECT MIN(date) FROM price_history WHERE code=?", (code,)).fetchone()
        if row and row[0]:
            conn.execute("UPDATE stocks SET first_data_date=?, updated_at=? WHERE code=?",
                         (row[0], now, code))
    conn.commit()
    return {"ok": len(res.ok), "failed": len(res.failed),
            "rows": total_rows, "outliers": total_out, "failures": res.failed}
