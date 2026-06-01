"""EDINET API v2 から ⑦有利子負債比率・⑫ネットキャッシュPER を取得するフェッチャー"""
import io
import time
import zipfile
import csv
import requests
import pandas as pd

from findex.cache import load_cache, save_cache
from findex.settings import Settings

# EDINET API エンドポイント
EDINET_BASE = "https://api.edinet-fsa.go.jp/api/v2"
EDINET_CODE_MAP_URL = (
    "https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140190.csv"
)


# ── EDINETコード対応表 ────────────────────────────────────────────

def fetch_edinet_code_map(settings: Settings) -> dict[str, str]:
    """証券コード → EDINETコード の対応辞書を返す。キャッシュTTL=7日。"""
    cached = load_cache("edinet_codemap", "master", ttl_days=7)
    if cached:
        return cached

    resp = requests.get(EDINET_CODE_MAP_URL, timeout=30)
    resp.raise_for_status()

    # Shift-JIS エンコーディングのCSV
    content = resp.content.decode("cp932", errors="replace")
    reader = csv.DictReader(io.StringIO(content))

    code_map: dict[str, str] = {}
    for row in reader:
        sec_code   = (row.get("証券コード") or "").strip().zfill(4)[:4]
        edinet_code = (row.get("ＥＤＩＮＥＴコード") or "").strip()
        if sec_code and edinet_code:
            code_map[sec_code] = edinet_code

    save_cache("edinet_codemap", "master", code_map)
    return code_map


# ── 有価証券報告書 docID 検索 ─────────────────────────────────────

def find_latest_doc_id(edinet_code: str, settings: Settings) -> str | None:
    """EDINETコードに対応する最新の有価証券報告書 docID を返す。"""
    # 直近2年分の月末を検索（提出日は決算後3ヶ月以内）
    from datetime import date, timedelta

    search_dates = []
    today = date.today()
    for months_ago in range(0, 18):
        d = today.replace(day=1) - timedelta(days=1)
        for _ in range(months_ago):
            d = (d.replace(day=1) - timedelta(days=1))
        search_dates.append(d)

    for d in search_dates:
        url = f"{EDINET_BASE}/documents.json"
        params = {
            "date": d.strftime("%Y-%m-%d"),
            "type": 2,
            "Subscription-Key": settings.edinet_api_key,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue

        for doc in data.get("results", []):
            if (doc.get("edinetCode") == edinet_code and
                    doc.get("docTypeCode") == "120" and  # 有価証券報告書
                    doc.get("csvFlag") == "1"):
                return doc["docID"]

    return None


# ── EDINET 財務CSV 取得・解析 ─────────────────────────────────────

def fetch_financial_csv(doc_id: str, settings: Settings) -> list[dict] | None:
    """docID から財務CSV（TSV形式）のレコードリストを返す。"""
    url = f"{EDINET_BASE}/documents/{doc_id}"
    params = {"type": 5, "Subscription-Key": settings.edinet_api_key}
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except Exception:
        return None

    # ZIPを展開してCSVを解析
    records = []
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            if not name.endswith(".csv"):
                continue
            raw = zf.read(name)
            try:
                text = raw.decode("utf-8-sig")
            except Exception:
                text = raw.decode("cp932", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                records.append(dict(row))

    return records if records else None


def _find_value(records: list[dict], *keywords,
                context: str = "CurrentYearInstant",
                consolidated: str = "連結") -> float | None:
    """レコードリストから指定キーワードを含む項目の値を探す。"""
    for row in records:
        label = row.get("項目名", "") or row.get("label", "")
        ctx   = row.get("コンテキストID", "") or row.get("contextRef", "")
        cons  = row.get("連結・個別", "") or ""
        val   = row.get("値", "") or row.get("value", "")

        if not val or val.strip() in ("", "-", "－"):
            continue
        if consolidated and consolidated not in cons:
            continue
        if context and context not in ctx:
            continue
        if all(kw in label for kw in keywords):
            try:
                return float(val.replace(",", ""))
            except ValueError:
                continue
    return None


def extract_metrics(records: list[dict], per: float | None,
                    market_cap: float | None) -> dict:
    """財務レコードから ⑦⑫ に必要な値を抽出して返す。"""
    result: dict = {}

    # ⑦ 有利子負債比率 = 有利子負債合計 / 自己資本
    interest_bearing_debt = (
        _find_value(records, "有利子負債", context="CurrentYearInstant") or
        _find_value(records, "借入金", "合計", context="CurrentYearInstant")
    )
    equity = _find_value(records, "純資産", "合計", context="CurrentYearInstant")

    if interest_bearing_debt is not None and equity and equity > 0:
        result["debt_to_equity"] = interest_bearing_debt / equity

    # ⑫ ネットキャッシュPER（簡易版: 流動資産 - 負債総額）
    current_assets    = _find_value(records, "流動資産", "合計", context="CurrentYearInstant")
    total_liabilities = _find_value(records, "負債", "合計", context="CurrentYearInstant")

    if (current_assets is not None and total_liabilities is not None and
            per and market_cap and market_cap > 0):
        net_cash = current_assets - total_liabilities
        net_cash_ratio = net_cash / market_cap
        net_cash_per = per * (1 - net_cash_ratio)
        if -500 < net_cash_per < 500:
            result["net_cash_per"] = net_cash_per

    return result


# ── メイン取得関数 ────────────────────────────────────────────────

def fetch_edinet(codes: list[str], settings: Settings,
                 delay: float = 0.5) -> pd.DataFrame:
    """銘柄コードリストの ⑦⑫ を EDINET から取得する。"""
    if not settings.edinet_api_key:
        # APIキー未設定: 空のDataFrameを返す
        return pd.DataFrame([{"code": c} for c in codes])

    code_map = fetch_edinet_code_map(settings)
    rows = []

    for code in codes:
        edinet_code = code_map.get(code)
        if not edinet_code:
            rows.append({"code": code})
            continue

        # キャッシュ確認（TTL=永続）
        cached = load_cache("edinet", code, ttl_days=None)
        if cached:
            rows.append({"code": code, **cached})
            continue

        # docID 取得
        doc_id = find_latest_doc_id(edinet_code, settings)
        if not doc_id:
            rows.append({"code": code})
            time.sleep(delay)
            continue

        # 財務CSV 取得・解析
        records = fetch_financial_csv(doc_id, settings)
        if not records:
            rows.append({"code": code})
            time.sleep(delay)
            continue

        # メトリクス抽出（PER・時価総額はyfinanceから取得済みの想定）
        metrics = extract_metrics(records, per=None, market_cap=None)
        save_cache("edinet", code, metrics, doc_id=doc_id)
        rows.append({"code": code, **metrics})
        time.sleep(delay)

    return pd.DataFrame(rows)
