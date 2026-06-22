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
from .jquants import JQuantsClient, parse_forecast_dividend, parse_fy_dividends

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


class _DividendsBuilder(RateLimitedFetcher[dict]):
    """1銘柄＝yfinance配当取得→dividend_events/annual書込→commit を fetch_one で完結。

    **resume安全性の要**: 旧実装は DividendFetcher().run() を全件回してから末尾でまとめて
    書いていた。途中で落ちて resume すると取得済み銘柄は checkpoint で skip され、in-memory
    結果が無いため annual/events に**行が書かれず・再取得もされない silent gap** が生じた
    （financials と同型・定款のsilent-drop禁止に違反）。本実装は fetch_one 内で書込・commit
    まで終え、base.run() が **commit 後にのみ checkpoint を刻む**。空配当([])は正規の無配と
    して done を刻む（再取得しない）／空history は DividendFetcher 側で RateLimitError＝再取得。
    """

    name = "dividends_yfinance"
    policy = FetchPolicy(batch_size=50, sleep_between_batches=2.0, sleep_between_items=0.3,
                         max_retries=4)

    def __init__(self, conn, months, now):
        self.conn = conn
        self.months = months
        self.now = now
        self.df = DividendFetcher()
        self.n_events = self.n_annual = self.no_div = 0

    def is_rate_limit(self, exc: Exception) -> bool:
        return self.df.is_rate_limit(exc)

    def fetch_one(self, code: str) -> dict:
        events = self.df.fetch_one(code)   # 空history は RateLimitError → _fetch_with_retry が再取得
        try:
            if not events:
                self.no_div += 1
            else:
                # 1) dividend_events 生データ
                self.conn.executemany(
                    """INSERT INTO dividend_events (code, ex_date, amount, source) VALUES (?,?,?, 'yfinance')
                       ON CONFLICT(code, ex_date) DO UPDATE SET amount=excluded.amount""",
                    [(code, ex, amt) for ex, amt in events],
                )
                self.n_events += len(events)
                # 2) 会計年度別に合算（地雷2・部分初年度のみ除外）
                fy_sum = aggregate_events(events, self.months.get(code, 3))
                for fy, dps in sorted(fy_sum.items()):
                    # 優先度: events は最弱。既存が上位ソースなら上書きしない
                    if _existing_priority(self.conn, code, fy) > SOURCE_PRIORITY["events"]:
                        continue
                    self.conn.execute(
                        """INSERT INTO dividend_annual (code, fiscal_year, dps, source, confidence, as_of, updated_at)
                           VALUES (?,?,?, 'events', 'present', NULL, ?)
                           ON CONFLICT(code, fiscal_year) DO UPDATE SET
                             dps=excluded.dps, source='events', confidence='present', updated_at=excluded.updated_at""",
                        (code, fy, dps, self.now),
                    )
                    self.n_annual += 1
            self.conn.commit()        # ← ここまで終えてから base.run が checkpoint を刻む
        except Exception:
            self.conn.rollback()
            raise
        return {"code": code, "events": len(events)}


def build_dividends(conn, codes: list[str], *, resume: bool = True) -> dict:
    """dividend_events/annual を resume 安全に構築（per-stock 書込→commit→checkpoint）。"""
    now = datetime.now().isoformat(timespec="seconds")
    months = {
        r[0]: (r[1] or 3)
        for r in conn.execute(
            f"SELECT code, fiscal_period_end_month FROM stocks WHERE code IN ({','.join('?' * len(codes))})",
            codes,
        )
    }
    builder = _DividendsBuilder(conn, months, now)
    res = builder.run(codes, resume=resume)
    # 能動洗浄は全codes対象（DB依存・冪等。resumeでも漏れなく走らせる）
    n_review = cleanse_haitoukin_seam(conn, codes)
    n_review += flag_dividend_anomalies(conn, codes)
    return {"ok": len(res.ok), "failed": len(res.failed), "no_dividend": builder.no_div,
            "events": builder.n_events, "annual_rows": builder.n_annual, "review_flags": n_review,
            "failures": res.failed}


class _JQuantsDividendBuilder(RateLimitedFetcher[dict]):
    """J-Quants確定配当(DivAnn)から **無配年(0.0)だけ** を dividend_annual に補完（doc13）。

    ghost利回り根治: yfinanceは「無配＝ex-dateイベント無し」で**構造的に無配年を出せない**ため、
    無配転落しても dividend_annual の最新が直近の有配年（例: サンウェルズFY2024=14）に固定され、
    暴落株価で割って幽霊利回りになる。J-Quantsは確定無配を DivAnn=0.0 で開示する＝これを取り込む。

    **golden保護のため fill-absent-無配-only**: 既存行がある年は一切触らない（正系列・events・
    override・haitoukin を上書きしない）。確定無配(0.0)で既存行が無い年だけ source=jquants で挿入。
    非ゼロの鮮度補完は対象外（yfinanceが有配年は出せるため不要・系列改変リスクを避ける）。
    resume安全: 1銘柄＝取得→書込→commit を fetch_one で完結（events builder と同型）。
    """

    name = "dividends_jquants"
    policy = FetchPolicy(batch_size=50, sleep_between_batches=1.5, sleep_between_items=0.2,
                         max_retries=4)

    def __init__(self, conn, now):
        self.conn = conn
        self.now = now
        self.client = JQuantsClient()
        self.n_filled = 0
        self.n_codes_filled = 0
        self.n_forecasts = 0

    def fetch_one(self, code: str) -> dict:
        records = self.client.fins_summary(code)
        divs = parse_fy_dividends(records)
        forecast = parse_forecast_dividend(records)   # 同一レスポンスから会社予想も抽出（追加取得なし）
        filled = 0
        try:
            for fy, dv in sorted(divs.items()):
                if dv != 0.0:
                    continue  # Phase1: 確定無配(0.0)のみ。有配年は yfinance events に任せる
                if self.conn.execute(
                    "SELECT 1 FROM dividend_annual WHERE code=? AND fiscal_year=?", (code, fy)
                ).fetchone():
                    continue  # 既存系列は触らない（fill-absentのみ＝golden保護）
                self.conn.execute(
                    "INSERT INTO dividend_annual (code, fiscal_year, dps, source, confidence, as_of, updated_at) "
                    "VALUES (?,?,0.0,'jquants','present',NULL,?)",
                    (code, fy, self.now),
                )
                filled += 1
            if forecast is not None:
                f_fy, f_dps, f_asof = forecast
                self.conn.execute(
                    "INSERT INTO dividend_forecast (code, forecast_fy, forecast_dps, source, as_of, updated_at) "
                    "VALUES (?,?,?,'jquants_forecast',?,?) "
                    "ON CONFLICT(code) DO UPDATE SET forecast_fy=excluded.forecast_fy, "
                    "forecast_dps=excluded.forecast_dps, source=excluded.source, "
                    "as_of=excluded.as_of, updated_at=excluded.updated_at",
                    (code, f_fy, f_dps, f_asof, self.now),
                )
            self.conn.commit()        # ← commit 後にのみ base.run が checkpoint を刻む
        except Exception:
            self.conn.rollback()
            raise
        self.n_filled += filled
        if filled:
            self.n_codes_filled += 1
        if forecast is not None:
            self.n_forecasts += 1
        return {"code": code, "filled": filled, "forecast": forecast is not None}


def build_jquants_dividends(conn, codes: list[str], *, resume: bool = True) -> dict:
    """J-Quants確定無配を dividend_annual に補完（doc13・ghost利回り根治）。"""
    now = datetime.now().isoformat(timespec="seconds")
    builder = _JQuantsDividendBuilder(conn, now)
    res = builder.run(codes, resume=resume)
    return {"ok": len(res.ok), "failed": len(res.failed), "filled": builder.n_filled,
            "codes_filled": builder.n_codes_filled, "forecasts": builder.n_forecasts,
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


EXTREME_DROP_RATIO = 0.35   # 前年の35%未満への急落＝値そのものの異常（yfinance単年誤値）
INCOMPLETE_DROP_RATIO = 0.65  # 半期欠落で年合計が目減りした疑いの上限
RECOVER_EPS = 0.999


def flag_dividend_anomalies(conn, codes: list[str]) -> int:
    """events由来の単年アーティファクト（欠損/部分レコード・単年誤値）を confidence=review で隔離。

    yfinanceのDividends系列には2種のアーティファクトが混じる（実データで確認）。**直後に前年水準へ
    復帰するV字**を共通条件に、2つの精密シグナルで検出する:
      ①**部分集計**: 半期/四半期払いの社で、ある年度が通常より少ない回数しか取り込めず年合計が
        目減り（沖縄セルラー2010=9.375÷2・SPK2005=4.25÷2＝本来は2回払い）。→ 支払回数<その社の最頻回数
        かつ DPS<前年65%。
      ②**単年誤値**: 払い回数は正常だが値が前年の35%未満まで急落（神戸物産2009=0.156・サンエー2006=1.25）。
    **実減配との弁別**: 日産FY2022=5.0（10→5の実減配・払い回数は通常通り・下落50%）は①②どちらにも
    該当せず残す。確証主義: 捏造で埋めず review に隔離（下流は confidence!=review で自動除外）。
    特配スパイク（花王FY2012=93・上振れ）は下落でないため対象外。手動/IR/ZAi(override)/haitoukinは触らない。
    """
    import collections

    now = datetime.now().isoformat(timespec="seconds")
    months = {
        r[0]: (r[1] or 3)
        for r in conn.execute(
            f"SELECT code, fiscal_period_end_month FROM stocks WHERE code IN ({','.join('?' * len(codes))})",
            codes,
        )
    }
    n_flagged = 0
    for code in codes:
        series = conn.execute(
            "SELECT fiscal_year, dps, source FROM dividend_annual "
            "WHERE code=? AND confidence!='review' AND dps IS NOT NULL ORDER BY fiscal_year",
            (code,),
        ).fetchall()
        if len(series) < 3:
            continue
        # その社の典型的な支払回数（最頻値）。半期=2/四半期=4 等。
        fm = months.get(code, 3)
        pay_counts: dict[int, int] = collections.Counter()
        for ex_date, in conn.execute("SELECT ex_date FROM dividend_events WHERE code=?", (code,)):
            pay_counts[fiscal_year_of(ex_date, fm)] += 1
        modal = collections.Counter(pay_counts.values()).most_common(1)[0][0] if pay_counts else 1

        for i in range(1, len(series) - 1):
            fy, dps, source = series[i]
            if source != "events":
                continue  # 機械集計のeventsだけが疑い対象
            prev = series[i - 1][1]
            next_fy = series[i + 1][0]
            if prev <= 0:
                continue
            # 共通: 直後（次の1〜2クリーン点）で前年水準へ復帰する一過性であること
            recovered = any(
                series[j][1] >= prev * RECOVER_EPS for j in range(i + 1, min(i + 3, len(series)))
            )
            if not recovered:
                continue  # 復帰しない持続的下落＝実減配の可能性→隔離しない
            # ①部分集計: 払い回数が最頻未満で年合計が目減り。ただし**孤立**（翌年は最頻回数に戻る）
            #   こと＝単年の取りこぼし。複数年連続で回数減なら実減配の頻度低下→隔離しない（日産）。
            incomplete = (
                modal >= 2 and pay_counts.get(fy, 0) < modal
                and pay_counts.get(next_fy, 0) >= modal
                and dps < prev * INCOMPLETE_DROP_RATIO
            )
            # ②単年誤値: 払い回数は正常だが値が前年の35%未満（yfinance単年異常値）
            extreme = dps < prev * EXTREME_DROP_RATIO
            if incomplete or extreme:
                conn.execute(
                    "UPDATE dividend_annual SET confidence='review', updated_at=? "
                    "WHERE code=? AND fiscal_year=?",
                    (now, code, fy),
                )
                n_flagged += 1
    conn.commit()
    return n_flagged


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
    n_review += flag_dividend_anomalies(conn, codes)
    return {"annual_rows": n_annual, "review_flags": n_review}
