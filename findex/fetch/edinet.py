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
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import yaml

from .. import config
from .base import FetchPolicy, RateLimitedFetcher, RateLimitError


class EdinetScanError(Exception):
    """提出書類の日次スキャンが一過性失敗で不完全だった（再取得対象）。

    「対象書類が真に存在しない（clean な空）」と「ネットワーク等の一過性失敗で
    見落とした可能性がある」を弁別するための例外。後者を None で握り潰すと、
    base.py が done を刻んで二度と再取得しない＝silent-drop になる。
    """

BASE = "https://api.edinet-fsa.go.jp/api/v2"
_LABELS_PATH = Path(__file__).parent / "edinet_labels.yaml"
_LABELS = yaml.safe_load(_LABELS_PATH.read_text(encoding="utf-8"))

CONSOLIDATED_CTX = {
    "instant": "CurrentYearInstant",
    "duration": "CurrentYearDuration",
}

# 「主要な経営指標等の推移」5年史のコンテキスト接頭辞→当年からの遡り年数。
# 連結＝サフィックス無し（_NonConsolidatedMember 等は除外）。
SUMMARY_CTX_OFFSETS = {
    "CurrentYear": 0,
    "Prior1Year": 1,
    "Prior2Year": 2,
    "Prior3Year": 3,
    "Prior4Year": 4,
}

# EDINET財務項目 → financial_snapshots カラム（深いBSのみ。PL/CFはJ-Quants主）
DEEP_FIELDS = list(_LABELS["fields"].keys())


SUMMARY_FIELDS = list(_LABELS.get("summary_fields", {}).keys())


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
    summary: dict[int, dict] = field(default_factory=dict)  # {fiscal_year: {field: val}} 5年史
    policy_text: str | None = None          # 配当政策 verbatim 原文（doc18 A）
    policy_signals: dict = field(default_factory=dict)  # 構造化シグナル＋status（doc18 B）


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


def _scan_one_date(d: date, edinet_code: str) -> tuple[str, str | None] | None:
    """指定日の提出一覧から対象有報を探す。見つかれば (docID, periodEnd)、無ければ None。

    一過性失敗は数回リトライ。リトライ尽きても失敗なら EdinetScanError を送出する
    （その日を「空」とは断定できない＝silent-drop を防ぐ）。
    """
    for attempt in range(3):
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
            return None  # clean: その日に対象書類は無い
        except RateLimitError:
            raise
        except Exception:
            if attempt == 2:
                raise EdinetScanError(f"{edinet_code} {d.isoformat()} スキャン失敗（再取得対象）")
            time.sleep(1.0 * (attempt + 1))
    return None  # 到達しない（型のため）


def find_latest_doc(edinet_code: str, fy_end_month: int) -> tuple[str | None, str | None]:
    """最新の有価証券報告書(docTypeCode=120,csvFlag=1) docID と periodEnd を返す。

    窓内の全日を clean にスキャンして見つからなければ (None, None)。途中で
    一過性失敗が解消しなければ EdinetScanError を送出し、空との断定を避ける。

    **走査は窓内を締切側(hi)から lo へ逆順**。有報は提出締切の直前に集中するため、
    前方(lo)からだと十数日ぶん無駄打ちしてからヒットする。1つの提出窓に同一企業の
    有報(docTypeCode=120)は1枚しか無いので、走査方向を変えても**返る docID は不変**・
    速くなるだけ（結果同一を実データcohortで実証済み）。窓の順序(最新期→前期)は維持
    するので「最新の有報」を返す性質も不変。
    """
    for lo, hi in _filing_windows(fy_end_month):
        d = hi
        while d >= lo:
            hit = _scan_one_date(d, edinet_code)
            if hit:
                return hit
            d -= timedelta(days=1)
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


def _summary_index(records: list[dict], suffix: str = "") -> dict[tuple[str, str], float]:
    """(要素ID, コンテキストID) → 値。summary用 Current/Prior1-4 の Instant/Duration。

    suffix="" は連結（サフィックス無し）、"_NonConsolidatedMember" は単体。
    """
    valid = set()
    for base in SUMMARY_CTX_OFFSETS:
        valid.add(base + "Instant" + suffix)
        valid.add(base + "Duration" + suffix)
    idx: dict[tuple[str, str], float] = {}
    for r in records:
        ctx = r.get("コンテキストID", "")
        if ctx not in valid:
            continue
        v = (r.get("値") or "").replace(",", "").strip()
        if v in ("", "-", "－"):
            continue
        try:
            idx[(r.get("要素ID", ""), ctx)] = float(v)
        except ValueError:
            continue
    return idx


def _extract_summary_with(records, std, current_fy, suffix):
    idx = _summary_index(records, suffix)
    out: dict[int, dict] = {}
    for base, offset in SUMMARY_CTX_OFFSETS.items():
        fy = current_fy - offset
        year_vals: dict[str, float] = {}
        for fname, spec in _LABELS["summary_fields"].items():
            cands = spec.get(std) or []
            if isinstance(cands, str):
                cands = [cands]
            ctx = base + ("Instant" if spec.get("ctx") == "instant" else "Duration") + suffix
            for eid in cands:  # フォールバック鎖: 最初に在る要素IDを採る
                if (eid, ctx) in idx:
                    year_vals[fname] = idx[(eid, ctx)]
                    break
        if year_vals:
            out[fy] = year_vals
    return out


def extract_summary(records: list[dict], std: str | None, current_fy: int | None) -> dict[int, dict]:
    """「主要な経営指標等の推移」から5年史 {fiscal_year: {field: val}} を抽出。

    最新有報1枚に Prior4..CurrentYear が同梱。当年=current_fy として遡る。連結優先。
    連結が一切無い会社は単体決算のみ（連結未作成）＝J-Quantsも単体を使う → 単体にフォールバック。
    US GAAP/基準不明/当年不明は空（捏造しない）。基準移行企業で旧基準年が別タグでも、
    基準をまたいだEPS接合は比較性を壊すのでしない（不足年は insufficient のまま＝正直）。
    """
    if not std or std == "us" or current_fy is None:
        return {}
    if not _LABELS.get("summary_fields"):
        return {}
    out = _extract_summary_with(records, std, current_fy, "")
    if not out:  # 連結皆無＝単体決算のみの会社
        out = _extract_summary_with(records, std, current_fy, "_NonConsolidatedMember")
    return out


# ── 配当方針（doc18）：A=生テキスト抽出 ／ B=保守的シグナル抽出 ────────────────
# 配当政策テキストブロックは jpcrp（企業内容開示）の統一タグ＝IFRS/JGAAP 同一要素ID。
POLICY_ELEMENT = "jpcrp_cor:DividendPolicyTextBlock"

# 全角→半角（数字・小数点・パーセント）。政策文は全角混在のため正規化してから解析。
_ZEN2HAN = str.maketrans("０１２３４５６７８９．％", "0123456789.%")

# 目標文脈マーカー（この近傍にあって初めて「目標%」として採る）。
_TARGET_MARKERS = ("目標", "目指", "方針", "維持", "以上", "程度", "水準", "目処", "めど",
                   "を基本", "とする", "下限", "目安", "念頭")
# 実績/決定文脈マーカー（この近傍があれば実績・確定値＝採らない。実績は payout_ratio が持つ）。
# ★スケール検証で判明（doc18）: 「（配当性向：X%）といたしました／実施することを決定」「X%となります」等、
#   方針語と共起しつつ実は実績/確定値という罠が全銘柄で多発。決定・実績の語を広く実績側に倒す。
# ★裸の「実施し/実施する/となる」は将来の実施意図（=方針）にも当たり過剰除外になるため不可。
#   確定・実績を示す語形（…ました／…決定）に限定する。
_RESULT_MARKERS = ("となりました", "となっており", "となった", "となりまし", "となります",
                   "といたしました", "といたします", "いたしました",
                   "実施しました", "実施いたしました", "実施することを決定",
                   "することを決定", "を決定いた", "実績は", "となる見込", "計上",
                   "予定であり", "予定です")
# 上限マーカー（「X%以下/以内」＝上限であって目標ではない。確証主義: 目標フィールドに入れない）。
_CAP_MARKERS = ("以下", "以内", "を上限", "上限")

# 各シグナルのキーワード（複数表記をフォールバック鎖で許容）。
_PAYOUT_KW = ("連結配当性向", "配当性向")
_DOE_KW = ("ＤＯＥ", "DOE", "株主資本配当率", "純資産配当率", "株主資本配当比率", "自己資本配当率")
_TOTAL_KW = ("総還元性向", "総配分性向", "株主還元性向")
# payout 探索時、配当性向キーワードと数値の間に別指標語があれば、その数値は別指標のもの
# （例「配当性向を加味しDOE2.5%」の2.5はDOE値）＝採らない。スケール検証で判明した混入の根治。
_PAYOUT_BLOCKERS = _DOE_KW + _TOTAL_KW

_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def extract_dividend_policy(records: list[dict]) -> str | None:
    """配当政策テキストブロックを verbatim 取得（doc18 A）。

    複数コンテキストが在りうる。当年(CurrentYearDuration)を最優先、無ければ最長の非空値。
    捏造の余地なし＝原文をそのまま返す（無ければ None）。
    """
    best: str | None = None
    for r in records:
        if r.get("要素ID") != POLICY_ELEMENT:
            continue
        v = (r.get("値") or "").strip()
        if not v or v in ("-", "－"):
            continue
        if r.get("コンテキストID", "") == "CurrentYearDuration":
            return v
        if best is None or len(v) > len(best):
            best = v
    return best


def _find_target_pct(text: str, keywords: tuple[str, ...],
                     block_between: tuple[str, ...] = ()) -> float | None:
    """keyword 近傍の「目標%」だけを採る（実績/上限/別指標なら採らない）。

    確証主義（doc18 §3 B）: 政策文の配当性向%は多くが**実績値**。目標マーカーと共起し、
    かつ実績・上限マーカーが近傍に無く、keyword と数値の間に別指標語が無い場合のみ
    float を返す。曖昧・不在は None（捏造しない）。block_between はスケール検証で判明した
    別指標値の混入（「配当性向…DOE2.5%」）を断つためのガード。
    """
    for kw in keywords:
        start = 0
        while True:
            i = text.find(kw, start)
            if i < 0:
                break
            start = i + len(kw)
            seg = text[i:i + len(kw) + 30]   # keyword 直後30字以内に % があるか
            m = _PCT_RE.search(seg)
            if not m:
                continue
            num_abs_start, num_abs_end = i + m.start(), i + m.end()
            gap = text[i + len(kw):num_abs_start]
            if any(b in gap for b in block_between):
                continue   # 配当性向と数値の間に別指標語＝この数値は別指標のもの
            tail = text[num_abs_end:num_abs_end + 8]
            if any(cap in tail for cap in _CAP_MARKERS):
                continue   # 「X%以下/以内」＝上限であって目標ではない
            window = text[max(0, i - 18):min(len(text), num_abs_end + 22)]
            if any(r in window for r in _RESULT_MARKERS):
                continue   # 実績/決定文脈 → 採らない
            if any(t in window for t in _TARGET_MARKERS):
                return float(m.group(1))
    return None


def parse_policy_signals(text: str | None) -> dict:
    """配当政策テキストから保守的に構造化シグナルを起こす（doc18 B）。

    返り値: {progressive_flag, stable_flag, payout_target_pct, doe_target_pct,
            total_payout_target_pct, signals_status:{各キー: ok/missing}}。
    原文が無ければ全 missing。明示シグナルだけ ok・他は missing を死守する。
    """
    keys = ("progressive_flag", "stable_flag", "payout_target_pct",
            "doe_target_pct", "total_payout_target_pct")
    out: dict = {k: None for k in keys}
    out["signals_status"] = {k: "missing" for k in keys}
    if not text:
        return out
    norm = text.translate(_ZEN2HAN)

    # 累進/安定はリテラル検出（言い換えからの推測昇格はしない＝初版は保守）。
    if "累進配当" in norm:
        out["progressive_flag"], out["signals_status"]["progressive_flag"] = 1, "ok"
    if "安定的" in norm or "安定した" in norm or "安定配当" in norm:
        out["stable_flag"], out["signals_status"]["stable_flag"] = 1, "ok"

    for key, kws, blockers in (
        ("payout_target_pct", _PAYOUT_KW, _PAYOUT_BLOCKERS),
        ("doe_target_pct", _DOE_KW, ()),
        ("total_payout_target_pct", _TOTAL_KW, ()),
    ):
        # 配当性向の検索で総還元性向を拾わないよう、payout は総還元語を一旦伏せる。
        haystack = norm
        if key == "payout_target_pct":
            for t in _TOTAL_KW:
                haystack = haystack.replace(t, "○" * len(t))
        val = _find_target_pct(haystack, kws, block_between=blockers)
        if val is not None:
            out[key], out["signals_status"][key] = val, "ok"
    return out


class EdinetFetcher(RateLimitedFetcher[EdinetRecord]):
    name = "edinet_xbrl"
    policy = FetchPolicy(batch_size=20, sleep_between_batches=3.0, sleep_between_items=0.3, max_retries=4)

    def __init__(self, code_to_edinet: dict[str, str], code_to_month: dict[str, int]):
        self.c2e = code_to_edinet
        self.c2m = code_to_month

    def is_rate_limit(self, exc: Exception) -> bool:
        """リトライ（指数バックオフ）対象か。レート制限に加え、一過性スキャン失敗も
        リトライ対象とする（EDINETの一時的不調を即failedにせず吸収）。リトライ尽きれば
        failed＝done を刻まず次回 resume で再取得＝silent-drop を防ぐ。"""
        return isinstance(exc, EdinetScanError) or super().is_rate_limit(exc)

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
        rec.summary = extract_summary(records, rec.accounting_standard, rec.fiscal_year)
        rec.policy_text = extract_dividend_policy(records)          # doc18 A（同一書類を再利用）
        rec.policy_signals = parse_policy_signals(rec.policy_text)  # doc18 B（保守的・status付き）
        return rec
