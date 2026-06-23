"""J-Quants API V2 クライアント＋財務サマリー取得。

認証は x-api-key ヘッダのみ（ダッシュボード発行キー）。基礎財務（PL/BS/CF/株数/配当）は
ここから、深いBS（capex/投資有価証券/有利子負債/支払利息）は EDINET から（D2.5分担）。
現契約は約2年窓のため、深い時系列は別途（EDINET有報＋旧DB）で補う。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import requests

from .. import config
from .base import FetchPolicy, RateLimitedFetcher, RateLimitError

BASE_URL = "https://api.jquants.com/v2"


class JQuantsClient:
    def __init__(self, api_key: str | None = None):
        key = api_key or config.JQUANTS_API_KEY
        if not key:
            raise RuntimeError("JQUANTS_API_KEY 未設定（findex/.env）")
        self.s = requests.Session()
        self.s.headers.update({"x-api-key": key})

    def _get(self, path: str, **params) -> dict:
        items: list = []
        list_key = ""
        pkey = None
        while True:
            p = {k: v for k, v in params.items() if v is not None}
            if pkey:
                p["pagination_key"] = pkey
            r = self.s.get(f"{BASE_URL}{path}", params=p, timeout=60)
            if r.status_code == 429:
                raise RateLimitError("jquants 429")
            if not r.ok:
                raise RuntimeError(f"jquants {r.status_code}: {r.text[:200]}")
            d = r.json()
            if "data" in d and isinstance(d["data"], list):
                list_key, lst = "data", d["data"]
            else:
                list_key, lst = next(((k, v) for k, v in d.items() if isinstance(v, list)), ("", []))
            items.extend(lst)
            pkey = d.get("pagination_key")
            if not pkey:
                break
        if list_key:
            d[list_key] = items
        return d

    def fins_summary(self, code: str) -> list[dict]:
        d = self._get("/fins/summary", code=code)
        return d.get("data") or []


def _f(v) -> float | None:
    """J-Quants文字列値→float（空文字/None→None）。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# J-Quants fins/summary フィールド → financial_snapshots カラム（基礎財務）
JQ_BASE_MAP = {
    "revenue": "Sales",
    "operating_income": "OP",
    "net_income": "NP",
    "eps": "EPS",
    "bps": "BPS",
    "shares_outstanding": "ShOutFY",
    "total_assets": "TA",
    "equity_attributable": "Eq",
    "operating_cf": "CFO",
    "cash_and_equivalents": "CashEq",
}

# DocType の会計基準サフィックス → 内部キー
_DOCTYPE_STD = {"IFRS": "ifrs", "US": "us", "JP": "jgaap"}


def _doctype_standard(doctype: str) -> str | None:
    for tok in (doctype or "").split("_"):
        if tok in _DOCTYPE_STD:
            return _DOCTYPE_STD[tok]
    if "JP" in (doctype or "") or "Japan" in (doctype or ""):
        return "jgaap"
    return None


@dataclass
class FinFY:
    """1会計年度の基礎財務（J-Quants由来）。"""
    fiscal_year: int
    period_end: str
    accounting_standard: str | None
    base: dict[str, float | None] = field(default_factory=dict)
    disclosed_date: str | None = None    # 開示日（DisclosedDate）＝分割補正の基準日（doc11是正）


def parse_fy_records(records: list[dict]) -> list[FinFY]:
    """fins/summary から **年次(FY)実績の財務諸表** だけを年度別に抽出。

    予想・配当訂正開示(EarnForecastRevision 等)は CurPerType=FY でも Sales が空。
    DocType に FinancialStatements を含み Sales が在るものだけ採る（空訂正開示の混入を排除）。
    """
    out: dict[int, FinFY] = {}
    for r in records:
        if r.get("CurPerType") != "FY":
            continue
        if "FinancialStatements" not in (r.get("DocType") or ""):
            continue
        end = r.get("CurFYEn") or r.get("CurPerEn") or ""
        if not end:
            continue
        base = {col: _f(r.get(src)) for col, src in JQ_BASE_MAP.items()}
        if base.get("revenue") is None:  # 実績は売上が必ず在る
            continue
        fy = int(end[:4])
        std = _doctype_standard(r.get("DocType", ""))
        disc = r.get("DisclosedDate") or r.get("DiscDate") or None
        cand = FinFY(fiscal_year=fy, period_end=end, accounting_standard=std,
                     base=base, disclosed_date=disc)
        # 同一FYに複数開示（訂正等）があれば最新開示(DisclosedDate)を採る。開示日不明は従来どおり後勝ち。
        prev = out.get(fy)
        if prev is None or not (prev.disclosed_date and disc and disc < prev.disclosed_date):
            out[fy] = cand
    return [out[k] for k in sorted(out)]


def parse_fy_dividends(records: list[dict]) -> dict[int, float]:
    """fins/summary から **FY実績の確定年間配当 DivAnn** を年度別に抽出（doc13）。

    yfinance実支払い（ex-dateイベント）では構造的に表現できない無配年（DivAnn=0.0＝確定無配）を
    含むのが要点（無配＝ex-date無し→yfinanceに行が立たない→ghost利回りの原因）。
    予想（FDivAnn/NxFDivAnn）は採らない＝確定実績のみ（捏造しない）。空文字（未開示）は None で除外。
    会計年度キーは parse_fy_records と同じ「決算期末年（CurFYEn の年）」で整合。
    """
    out: dict[int, float] = {}
    for r in records:
        if r.get("CurPerType") != "FY":
            continue
        if "FinancialStatements" not in (r.get("DocType") or ""):
            continue
        end = r.get("CurFYEn") or r.get("CurPerEn") or ""
        if not end:
            continue
        dv = _f(r.get("DivAnn"))
        if dv is None:
            continue
        out[int(end[:4])] = dv
    return out


def _keep_latest(m: dict[int, tuple[float, str]], fy: int, dps: float, disc: str) -> None:
    """同一FYは最新開示(DiscDate)を残す（再開示・訂正で予想は更新される）。"""
    if fy not in m or disc > m[fy][1]:
        m[fy] = (dps, disc)


def parse_forecast_dividend(records: list[dict]) -> tuple[int, float, str | None] | None:
    """fins/summary から **会社予想の前向き年間配当** を1本返す。(forecast_fy, dps, as_of) or None。

    実績(DivAnn)とは別物。市場標準の「予想配当利回り」へ div_yield を合わせるための予想値:
      - 当期(未確定FY)の会社予想 = その開示の FDivAnn、対象FY=year(CurFYEn)。
      - 本決算開示(CurPerType=FY)の NxFDivAnn = 翌期予想、対象FY=year(CurFYEn)+1。
    同一FYに複数開示があれば最新開示(DiscDate)を採用し、最も前向き(最大FY)の予想を返す。
    予想0.0（会社予想=無配）も確定された予想として保持。空文字（未開示）は None で除外。
    """
    best: dict[int, tuple[float, str]] = {}  # fy -> (dps, disc_date)
    for r in records:
        disc = r.get("DiscDate") or r.get("DisclosedDate") or ""
        end = r.get("CurFYEn") or r.get("CurPerEn") or ""
        if not end:
            continue
        cur_fy = int(end[:4])
        f = _f(r.get("FDivAnn"))               # 当期予想（四半期/本決算いずれの開示にも載る）
        if f is not None:
            _keep_latest(best, cur_fy, f, disc)
        if r.get("CurPerType") == "FY":        # 本決算開示に載る翌期予想
            nf = _f(r.get("NxFDivAnn"))
            if nf is not None:
                _keep_latest(best, cur_fy + 1, nf, disc)
    if not best:
        return None
    fy = max(best)
    dps, disc = best[fy]
    return fy, dps, (disc or None)


class FinancialsFetcher(RateLimitedFetcher[list]):
    name = "jquants_fins"
    policy = FetchPolicy(batch_size=50, sleep_between_batches=2.0, sleep_between_items=0.2, max_retries=4)

    def __init__(self):
        self.client = JQuantsClient()

    def fetch_one(self, code: str) -> list[FinFY]:
        return parse_fy_records(self.client.fins_summary(code))
