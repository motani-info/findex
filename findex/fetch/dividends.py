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


def aggregate_events(events: list[tuple[str, float]], fiscal_month: int) -> dict[int, float]:
    """配当イベント→会計年度別合算。**部分的な初年度のみ**を捨てる（地雷1を条件化）。

    旧実装は初年度を無条件ドロップ→花王FY2000(=10+12の完全な年)まで消し接合に穴が空いた。
    初年度の支払回数が次年度より少ない時だけ「期中＝部分的」とみなして捨てる。
    """
    fy_sum: dict[int, float] = {}
    fy_cnt: dict[int, int] = {}
    for ex, amt in events:
        fy = fiscal_year_of(ex, fiscal_month)
        fy_sum[fy] = fy_sum.get(fy, 0.0) + amt
        fy_cnt[fy] = fy_cnt.get(fy, 0) + 1
    if not fy_sum:
        return {}
    fys = sorted(fy_sum)
    first = fys[0]
    if len(fys) > 1 and fy_cnt[first] < fy_cnt[fys[1]]:
        del fy_sum[first]  # 部分的な初年度のみ捨てる
    return fy_sum


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

        # 2) 会計年度別に合算（地雷2・部分初年度のみ除外）
        fy_sum = aggregate_events(events, months.get(code, 3))
        for fy, dps in sorted(fy_sum.items()):
            # 優先度: events は最弱。既存が上位ソースなら上書きしない
            if _existing_priority(conn, code, fy) > SOURCE_PRIORITY["events"]:
                continue
            conn.execute(
                """INSERT INTO dividend_annual (code, fiscal_year, dps, source, confidence, as_of, updated_at)
                   VALUES (?,?,?, 'events', 'present', NULL, ?)
                   ON CONFLICT(code, fiscal_year) DO UPDATE SET
                     dps=excluded.dps, source='events', confidence='present', updated_at=excluded.updated_at""",
                (code, fy, dps, now),
            )
            n_annual += 1
    conn.commit()
    n_review = cleanse_haitoukin_seam(conn, list(res.ok))
    return {"ok": len(res.ok), "failed": len(res.failed), "no_dividend": no_div,
            "events": n_events, "annual_rows": n_annual, "review_flags": n_review,
            "failures": res.failed}


def cleanse_haitoukin_seam(conn, codes: list[str]) -> int:
    """能動洗浄（#7）: haitoukin(pre2000)を分割でevents単位に整合させる。

    haitoukinの分割調整状態は社により不統一（実証: リンナイは未調整・花王は調整済）。
    接合年で「生」と「分割係数で除算」の2仮説を比較し、events側トレンドに整合する方を採用。
    どちらも整合しなければ confidence=review（捏造せず気づける状態にする）。
    """
    import yfinance as yf

    now = datetime.now().isoformat(timespec="seconds")
    n_review = 0
    for code in codes:
        hai = conn.execute(
            "SELECT fiscal_year, dps FROM dividend_annual WHERE code=? AND source='haitoukin' ORDER BY fiscal_year",
            (code,),
        ).fetchall()
        if not hai:
            continue
        # events側の最初の確かな値（接合の参照）
        ev = conn.execute(
            "SELECT fiscal_year, dps FROM dividend_annual WHERE code=? AND source='events' ORDER BY fiscal_year LIMIT 1",
            (code,),
        ).fetchone()
        if not ev:
            continue
        ev_fy, ev_dps = ev
        last_hy, last_hv = hai[-1]
        try:
            splits = yf.Ticker(f"{code}.T").splits
        except Exception:
            splits = None
        factor = 1.0
        if splits is not None and len(splits):
            for idx, v in splits.items():
                if idx.year > last_hy:  # haitoukin最終年より後の分割
                    factor *= float(v)
        gap = max(ev_fy - last_hy, 1)
        # 1年あたり許容: 0.6〜1.8倍/年（増配/微減の現実的レンジ）
        def per_year(ratio):
            return ratio ** (1.0 / gap)
        raw_ratio = (last_hv / ev_dps) if ev_dps else 0
        adj_ratio = (last_hv / factor / ev_dps) if (ev_dps and factor) else 0
        raw_ok = 0.55 <= per_year(raw_ratio) <= 1.8 if raw_ratio > 0 else False
        adj_ok = 0.55 <= per_year(adj_ratio) <= 1.8 if adj_ratio > 0 else False
        if adj_ok and factor > 1 and not raw_ok:
            # 分割未調整 → 全haitoukin行を分割調整して単位統一
            for fy, dps in hai:
                conn.execute(
                    "UPDATE dividend_annual SET dps=?, confidence='present', updated_at=? WHERE code=? AND fiscal_year=?",
                    (dps / factor, now, code, fy),
                )
        elif raw_ok:
            pass  # 既に整合（調整不要）
        else:
            # どちらも不整合（合併等）→ review（pre2000は左打ち切り/override/N+で扱う）
            for fy, _ in hai:
                conn.execute(
                    "UPDATE dividend_annual SET confidence='review', updated_at=? WHERE code=? AND fiscal_year=?",
                    (now, code, fy),
                )
            n_review += 1
    conn.commit()
    return n_review


def rebuild_and_cleanse(conn, codes: list[str]) -> dict:
    """再取得せず、保存済み dividend_events から dividend_annual(events) を再構築＋洗浄。"""
    now = datetime.now().isoformat(timespec="seconds")
    months = {
        r[0]: (r[1] or 3)
        for r in conn.execute(
            f"SELECT code, fiscal_period_end_month FROM stocks WHERE code IN ({','.join('?' * len(codes))})",
            codes,
        )
    }
    n_annual = 0
    for code in codes:
        events = [
            (r[0], r[1])
            for r in conn.execute(
                "SELECT ex_date, amount FROM dividend_events WHERE code=? ORDER BY ex_date", (code,)
            )
        ]
        if not events:
            continue
        # 既存events行を作り直す前に消す（地雷1条件化で年構成が変わるため）
        conn.execute("DELETE FROM dividend_annual WHERE code=? AND source='events'", (code,))
        fy_sum = aggregate_events(events, months.get(code, 3))
        for fy, dps in sorted(fy_sum.items()):
            if _existing_priority(conn, code, fy) > SOURCE_PRIORITY["events"]:
                continue
            conn.execute(
                """INSERT INTO dividend_annual (code, fiscal_year, dps, source, confidence, as_of, updated_at)
                   VALUES (?,?,?, 'events', 'present', NULL, ?)
                   ON CONFLICT(code, fiscal_year) DO UPDATE SET
                     dps=excluded.dps, source='events', confidence='present', updated_at=excluded.updated_at""",
                (code, fy, dps, now),
            )
            n_annual += 1
    conn.commit()
    n_review = cleanse_haitoukin_seam(conn, codes)
    return {"annual_rows": n_annual, "review_flags": n_review}
