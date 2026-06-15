"""Phase 1 マスター構築: JPX一覧（識別）＋ EDINETコードリスト（会計メタ）→ stocks。

ユニバースは**国内上場普通株のみ**（ETF/ETN/REIT/外国株/出資証券/PRO Market を除外。
design-review #8 / charter §2）。会計基準(accounting_standard)はXBRL由来のためPhase 2で補完。
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime

import pandas as pd
import requests

JPX_EXCEL_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)
EDINET_CODELIST_URL = (
    "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
)

# 普通株ユニバース（内国株式のみ）。ETF・ETN/REIT等/外国株/出資証券/PRO Marketは除外
DOMESTIC_MARKETS = {
    "プライム（内国株式）",
    "スタンダード（内国株式）",
    "グロース（内国株式）",
}

_MONTH_RE = re.compile(r"(\d{1,2})\s*月")


def _parse_fiscal_month(s: str) -> int | None:
    """『3月31日』→ 3。決算期末月（FY正規化の基準・地雷2）。"""
    m = _MONTH_RE.search(s or "")
    return int(m.group(1)) if m else None


def fetch_jpx_master() -> pd.DataFrame:
    """JPX公式Excel → 普通株のみの code/name/market/sector33。"""
    r = requests.get(JPX_EXCEL_URL, timeout=60)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), engine="xlrd")
    df = df.rename(
        columns={
            "コード": "code",
            "銘柄名": "name",
            "市場・商品区分": "market_raw",
            "33業種区分": "sector33",
        }
    )
    df["code"] = df["code"].astype(str).str.strip()
    df = df[df["market_raw"].isin(DOMESTIC_MARKETS)].copy()
    df["market"] = df["market_raw"].str.replace("（内国株式）", "", regex=False)
    return df[["code", "name", "market", "sector33"]].reset_index(drop=True)


def fetch_edinet_codelist() -> dict[str, dict]:
    """EDINETコードリストzip → {4桁証券コード: 会計メタ}。XBRL不要・全社同梱。"""
    r = requests.get(EDINET_CODELIST_URL, timeout=90)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
    txt = zf.read(name).decode("cp932", errors="replace")
    lines = txt.splitlines()
    # 1行目は「ダウンロード実行日…」のメタ行。2行目がヘッダ
    reader = csv.DictReader(io.StringIO("\n".join(lines[1:])))
    out: dict[str, dict] = {}
    for row in reader:
        sec = (row.get("証券コード") or "").strip()
        if not sec:
            continue
        code = sec[:4]  # 証券コードは5桁(末尾チェックデジット)
        out[code] = {
            "edinet_code": (row.get("ＥＤＩＮＥＴコード") or "").strip() or None,
            "fiscal_period_end_month": _parse_fiscal_month(row.get("決算日") or ""),
            "consolidated": 1 if (row.get("連結の有無") or "").strip() == "有" else 0,
        }
    return out


def build_stocks(conn, codes: list[str] | None = None) -> dict[str, int]:
    """JPX + EDINETコードリストを統合し stocks にupsert。

    codes 指定時はそのコードのみ（検証コホート用）。会計基準はPhase 2で補完。
    既存行の手当て済みフィールド（listing_date等）は上書きしない。
    """
    now = datetime.now().isoformat(timespec="seconds")
    jpx = fetch_jpx_master()
    if codes:
        jpx = jpx[jpx["code"].isin(set(codes))].copy()
    meta = fetch_edinet_codelist()

    inserted = updated = 0
    for _, row in jpx.iterrows():
        code = row["code"]
        m = meta.get(code, {})
        exists = conn.execute("SELECT 1 FROM stocks WHERE code=?", (code,)).fetchone()
        conn.execute(
            """
            INSERT INTO stocks
              (code, name, market, sector33, edinet_code,
               fiscal_period_end_month, consolidated, is_active, updated_at)
            VALUES (?,?,?,?,?,?,?,1,?)
            ON CONFLICT(code) DO UPDATE SET
              name=excluded.name, market=excluded.market, sector33=excluded.sector33,
              edinet_code=COALESCE(excluded.edinet_code, stocks.edinet_code),
              fiscal_period_end_month=COALESCE(excluded.fiscal_period_end_month,
                                               stocks.fiscal_period_end_month),
              consolidated=COALESCE(excluded.consolidated, stocks.consolidated),
              is_active=1, updated_at=excluded.updated_at
            """,
            (
                code, row["name"], row["market"], row["sector33"],
                m.get("edinet_code"), m.get("fiscal_period_end_month"),
                m.get("consolidated"), now,
            ),
        )
        if exists:
            updated += 1
        else:
            inserted += 1
    conn.commit()
    return {
        "universe": len(jpx),
        "inserted": inserted,
        "updated": updated,
        "edinet_meta_codes": len(meta),
    }
