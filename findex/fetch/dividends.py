"""配当イベント再取得→dividend_events→dividend_annual(events)＋能動洗浄。

- yfinance `history` の Dividends 列（分割調整済み・実証: 花王2025=77+77=154=J-Quants DivAnn）
  を使う（`.dividends` 単独はNoneを返す不安定があるため history経由で頑健化）
- 会計年度集計（地雷2）: ex_date.month > 決算期末月 なら翌FY。初年度は期中の可能性で捨てる（地雷1）
- 競合時の優先: manual>ir>haitoukin>jquants>events（手動確定値を機械再構築で潰さない）
- 能動洗浄（design-review #7）: 移行haitoukin(pre2000)とevents由来の重複年/接合部を相互照合し
  乖離をconfidence=reviewで記録（捏造しない・気づける）
"""
from __future__ import annotations

from datetime import datetime

import yfinance as yf

from .base import FetchPolicy, RateLimitedFetcher, RateLimitError

SOURCE_PRIORITY = {"manual": 5, "ir": 4, "haitoukin": 3, "jquants": 2, "events": 1}


def fiscal_year_of(ex_date_iso: str, fiscal_end_month: int) -> int:
    """ex_date(YYYY-MM-DD) → 会計年度（決算期末月で正規化・地雷2）。"""
    y, m = int(ex_date_iso[:4]), int(ex_date_iso[5:7])
    return y + 1 if m > fiscal_end_month else y


class DividendFetcher(RateLimitedFetcher[list]):
    name = "dividends_yfinance"
    policy = FetchPolicy(batch_size=50, sleep_between_batches=2.0, sleep_between_items=0.3, max_retries=4)

    def fetch_one(self, code: str) -> list[tuple[str, float]]:
        h = yf.Ticker(f"{code}.T").history(period="max", auto_adjust=False)
        if h.empty:
            raise RateLimitError(f"yfinance empty history for {code} (retry)")
        if "Dividends" not in h.columns:
            return []
        div = h[h["Dividends"] > 0]["Dividends"]
        return [(idx.date().isoformat(), float(v)) for idx, v in div.items()]

    def is_rate_limit(self, exc: Exception) -> bool:
        return super().is_rate_limit(exc) or "empty history" in str(exc).lower()


def _existing_priority(conn, code: str, fy: int) -> int:
    row = conn.execute(
        "SELECT source FROM dividend_annual WHERE code=? AND fiscal_year=?", (code, fy)
    ).fetchone()
    return SOURCE_PRIORITY.get(row[0], 0) if row else 0


def build_dividends(conn, codes: list[str], *, resume: bool = True) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    months = {
        r[0]: (r[1] or 3)
        for r in conn.execute(
            f"SELECT code, fiscal_period_end_month FROM stocks WHERE code IN ({','.join('?' * len(codes))})",
            codes,
        )
    }
    res = DividendFetcher().run(codes, resume=resume)

    n_events = n_annual = n_review = no_div = 0
    for code, events in res.ok.items():
        if not events:
            no_div += 1
            continue
        # 1) dividend_events 生データ
        conn.executemany(
            """INSERT INTO dividend_events (code, ex_date, amount, source) VALUES (?,?,?, 'yfinance')
               ON CONFLICT(code, ex_date) DO UPDATE SET amount=excluded.amount""",
            [(code, ex, amt) for ex, amt in events],
        )
        n_events += len(events)

        # 2) 会計年度別に合算（地雷2）
        fy_sum: dict[int, float] = {}
        for ex, amt in events:
            fy = fiscal_year_of(ex, months.get(code, 3))
            fy_sum[fy] = fy_sum.get(fy, 0.0) + amt
        if not fy_sum:
            continue
        first_fy = min(fy_sum)  # 初年度は期中の可能性で捨てる（地雷1）

        # 3) 能動洗浄: 既存haitoukin(pre2000)との接合/重複照合（#7）
        for fy, dps in sorted(fy_sum.items()):
            if fy == first_fy:
                continue
            row = conn.execute(
                "SELECT dps, source FROM dividend_annual WHERE code=? AND fiscal_year=?", (code, fy)
            ).fetchone()
            confidence = "present"
            if row and row[1] == "haitoukin" and row[0]:
                rel = abs(dps - row[0]) / row[0] if row[0] else 0
                if rel > 0.10:  # 10%超の乖離=要確認
                    confidence = "review"
                    n_review += 1
            # 優先度: events は最弱。既存が上位ソースなら上書きしない
            if _existing_priority(conn, code, fy) > SOURCE_PRIORITY["events"]:
                continue
            conn.execute(
                """INSERT INTO dividend_annual (code, fiscal_year, dps, source, confidence, as_of, updated_at)
                   VALUES (?,?,?, 'events', ?, NULL, ?)
                   ON CONFLICT(code, fiscal_year) DO UPDATE SET
                     dps=excluded.dps, source='events', confidence=excluded.confidence, updated_at=excluded.updated_at""",
                (code, fy, dps, confidence, now),
            )
            n_annual += 1
    conn.commit()
    return {"ok": len(res.ok), "failed": len(res.failed), "no_dividend": no_div,
            "events": n_events, "annual_rows": n_annual, "review_flags": n_review,
            "failures": res.failed}
