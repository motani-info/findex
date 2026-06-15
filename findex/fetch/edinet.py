"""EDINET有報XBRL から深いBS項目を取得（J-Quantsで取れない入手難フィールド）。

会計基準別ラベル辞書（edinet_labels.yaml）で IFRS/JGAAP を横断。連結＝コンテキストが
サフィックス無し(CurrentYearInstant/Duration)のものだけ採る。US GAAPは連結が構造化
XBRLに出ない（実証済）→ unavailable 扱いで grade_capital フォールバック。

提出書類の探索は**提出日を日次スキャン**（締切=期末+3ヶ月の窓）。月末だけ見る旧実装の
バグ（D2.5）を是正。取得は RateLimitedFetcher 経由。
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import yaml

from .. import config
from .base import FetchPolicy, RateLimitedFetcher, RateLimitError

BASE = "https://api.edinet-fsa.go.jp/api/v2"
_LABELS_PATH = Path(__file__).parent / "edinet_labels.yaml"
_LABELS = yaml.safe_load(_LABELS_PATH.read_text(encoding="utf-8"))

CONSOLIDATED_CTX = {
    "instant": "CurrentYearInstant",
    "duration": "CurrentYearDuration",
}

# EDINET財務項目 → financial_snapshots カラム（深いBSのみ。PL/CFはJ-Quants主）
DEEP_FIELDS = list(_LABELS["fields"].keys())


@dataclass
class EdinetRecord:
    code: str
    edinet_code: str
    doc_id: str | None = None
    fiscal_year: int | None = None
    period_end: str | None = None
    accounting_standard: str | None = None  # jgaap/ifrs/us
    values: dict[str, float | None] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)  # field→ok/missing/insufficient/censored


def _filing_windows(fy_end_month: int) -> list[tuple[date, date]]:
    """締切=期末+3ヶ月。直近2期分の提出窓（締切−18日〜締切+2日）。"""
    today = date.today()
    wins = []
    for yr in (today.year, today.year - 1, today.year - 2):
        deadline = date(yr, fy_end_month, 28) + timedelta(days=92)
        if deadline <= today:
            wins.append((deadline - timedelta(days=18), deadline + timedelta(days=2)))
    return wins[:2]


def _request(url: str, params: dict, timeout: int = 30) -> requests.Response:
    r = requests.get(url, params=params, timeout=timeout)
    if r.status_code in (429, 403):
        raise RateLimitError(f"EDINET {r.status_code}")
    r.raise_for_status()
    return r


def find_latest_doc(edinet_code: str, fy_end_month: int) -> tuple[str | None, str | None]:
    """最新の有価証券報告書(docTypeCode=120,csvFlag=1) docID と periodEnd を返す。"""
    for lo, hi in _filing_windows(fy_end_month):
        d = lo
        while d <= hi:
            try:
                r = _request(
                    f"{BASE}/documents.json",
                    {"date": d.isoformat(), "type": 2, "Subscription-Key": config.EDINET_API_KEY},
                    timeout=15,
                )
                for doc in r.json().get("results", []):
                    if (
                        doc.get("edinetCode") == edinet_code
                        and doc.get("docTypeCode") == "120"
                        and doc.get("csvFlag") == "1"
                    ):
                        return doc["docID"], doc.get("periodEnd")
            except RateLimitError:
                raise
            except Exception:
                pass
            d += timedelta(days=1)
    return None, None


def fetch_csv_records(doc_id: str) -> list[dict]:
    """docID の財務CSV（UTF-16・TAB区切り）を辞書リストで返す。"""
    r = _request(f"{BASE}/documents/{doc_id}", {"type": 5, "Subscription-Key": config.EDINET_API_KEY})
    out: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        for name in zf.namelist():
            if not name.endswith(".csv"):
                continue
            raw = zf.read(name)
            try:
                txt = raw.decode("utf-16")
            except Exception:
                txt = raw.decode("utf-8-sig", errors="replace")
            out.extend(dict(x) for x in csv.DictReader(io.StringIO(txt), delimiter="\t"))
    return out


def detect_standard(records: list[dict]) -> str | None:
    """AccountingStandardsDEI → 内部基準キー(jgaap/ifrs/us)。"""
    for r in records:
        if r.get("要素ID") == "jpdei_cor:AccountingStandardsDEI":
            return _LABELS["standards"].get((r.get("値") or "").strip())
    return None


def _index(records: list[dict]) -> dict[tuple[str, str], float]:
    """(要素ID, コンテキストID) → 値（連結ctxのみ・数値化できたもの）。"""
    idx: dict[tuple[str, str], float] = {}
    for r in records:
        ctx = r.get("コンテキストID", "")
        if ctx not in ("CurrentYearInstant", "CurrentYearDuration"):
            continue
        v = (r.get("値") or "").replace(",", "").strip()
        if v in ("", "-", "－"):
            continue
        try:
            idx[(r.get("要素ID", ""), ctx)] = float(v)
        except ValueError:
            continue
    return idx


def extract_fields(records: list[dict], std: str) -> tuple[dict, dict]:
    """会計基準別辞書で深いBS項目を抽出。値と status(ok/missing/insufficient) を返す。"""
    idx = _index(records)
    values: dict[str, float | None] = {}
    status: dict[str, str] = {}
    us_unavail = _LABELS.get("us_unavailable") and std == "us"
    for fname, spec in _LABELS["fields"].items():
        if us_unavail:
            values[fname] = None
            status[fname] = "censored"  # US連結は構造化されず取得不能
            continue
        ctx = CONSOLIDATED_CTX[spec.get("ctx", "instant")]
        candidates = spec.get(std, []) if std else []
        if not candidates:
            values[fname] = None
            status[fname] = "insufficient"  # その基準では構造的に単独タグ無し
            continue
        found = [idx[(eid, ctx)] for eid in candidates if (eid, ctx) in idx]
        if not found:
            values[fname] = None
            status[fname] = "missing"  # タグ在るはずだが当該社の有報に無い
            continue
        val = sum(found) if spec.get("mode") == "sum" else found[0]
        if spec.get("abs"):
            val = abs(val)
        values[fname] = val
        status[fname] = "ok"
    return values, status


class EdinetFetcher(RateLimitedFetcher[EdinetRecord]):
    name = "edinet_xbrl"
    policy = FetchPolicy(batch_size=20, sleep_between_batches=3.0, sleep_between_items=0.3, max_retries=4)

    def __init__(self, code_to_edinet: dict[str, str], code_to_month: dict[str, int]):
        self.c2e = code_to_edinet
        self.c2m = code_to_month

    def fetch_one(self, code: str) -> EdinetRecord:
        ec = self.c2e.get(code)
        rec = EdinetRecord(code=code, edinet_code=ec or "")
        if not ec:
            rec.status = {f: "missing" for f in DEEP_FIELDS}
            return rec
        month = self.c2m.get(code) or 3
        doc_id, period_end = find_latest_doc(ec, month)
        rec.doc_id, rec.period_end = doc_id, period_end
        if not doc_id:
            rec.status = {f: "missing" for f in DEEP_FIELDS}
            return rec
        records = fetch_csv_records(doc_id)
        rec.accounting_standard = detect_standard(records)
        if period_end:
            rec.fiscal_year = int(period_end[:4])
        rec.values, rec.status = extract_fields(records, rec.accounting_standard)
        return rec
