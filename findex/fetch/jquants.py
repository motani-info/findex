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
        out[fy] = FinFY(fiscal_year=fy, period_end=end, accounting_standard=std, base=base)
    return [out[k] for k in sorted(out)]


class FinancialsFetcher(RateLimitedFetcher[list]):
    name = "jquants_fins"
    policy = FetchPolicy(batch_size=50, sleep_between_batches=2.0, sleep_between_items=0.2, max_retries=4)

    def __init__(self):
        self.client = JQuantsClient()

    def fetch_one(self, code: str) -> list[FinFY]:
        return parse_fy_records(self.client.fins_summary(code))
