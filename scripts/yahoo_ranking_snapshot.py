#!/usr/bin/env python
"""Yahoo!ファイナンスの公開ランキング（配当利回り/PBR/PER/時価総額/ROE…）の「今日断面」を
取得してファイルに保存し、findex の computed_metrics と整合性を突合する検証ツール（柱1データ完全性）。

源泉: https://finance.yahoo.co.jp/stocks/ranking/<type>?market=all&page=N
各ページに __PRELOADED_STATE__ JSON が埋まり、`mainRankingList.results[]` に
rank / stockCode / stockName / savePrice と、種別ごとの実値（rankingResult 内のネスト辞書）を持つ。
サーバHTML＝JS不要・スクリプタブル。Yahoo の値は当日断面（updateDateTime 付き）。

これは検証専用（読み取りのみ）。findex のパイプラインは一切変更しない。外向き取得は
種別×ページ数に比例するため、既定は各種別 上位 `--pages`（既定4＝上位約200）に限定し、
ページ間に礼儀的スリープを入れる（レート制限の鉄則）。全件は `--all-pages` で明示。

突合の解釈（基準差に注意・乖離＝即バグではない）:
- クリーンに比較できる軸 = **PBR（実績）/時価総額/配当利回り（findexも予想化済）**。
- 基準差が出る軸 = **PER（会社予想 vs findexのJ-Quants確報EPS）/ROE（算定基準差）**。
- ランキングは普通株以外（REIT・投資法人等）も含む → findex（内国株式3,734）に無いコードは in_findex=False で除外。
- findex 側の鮮度を `dividends-jq --all`→`derive --all` で最新化してから突合すると、残る乖離＝真の不具合に絞れる。

実行例:
  uv run python scripts/yahoo_ranking_snapshot.py                 # 既定種別の上位を保存のみ
  uv run python scripts/yahoo_ranking_snapshot.py --compare       # 保存＋findex突合サマリ
  uv run python scripts/yahoo_ranking_snapshot.py --types lowPbr,marketCapitalHigh --compare
  uv run python scripts/yahoo_ranking_snapshot.py --types lowPbr --all-pages --compare
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from findex import config  # noqa: E402

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
SLEEP_BETWEEN = 1.2          # 礼儀的レート（外向き取得・ページ/種別間）
BASE = "https://finance.yahoo.co.jp/stocks/ranking/{slug}"

# ランキング種別の定義。box=rankingResult内の容器キー / val=値キー / unit=単位 /
# findex_col=突合相手のcomputed_metrics列 / findex_scale=findex値→Yahoo単位への係数 / aux=補助で残す参考値。
RANKINGS: dict[str, dict] = {
    "dividendYield": dict(text="配当利回り（会社予想）", box="shareDividendYield", val="shareDividendYield",
                          unit="%", findex_col="div_yield", findex_scale=100.0,
                          aux=["dps", "profileSettlementYm"]),
    "lowPbr":  dict(text="低PBR（実績）", box="pbr", val="pbr", unit="x",
                    findex_col="pbr", findex_scale=1.0, aux=["bps", "profileSettlementYm", "settleTypeForBps"]),
    "highPbr": dict(text="高PBR（実績）", box="pbr", val="pbr", unit="x",
                    findex_col="pbr", findex_scale=1.0, aux=["bps", "profileSettlementYm", "settleTypeForBps"]),
    "lowPer":  dict(text="低PER（会社予想）", box="per", val="per", unit="x",
                    findex_col="per", findex_scale=1.0, aux=["eps", "profileSettlementYm"]),
    "highPer": dict(text="高PER（会社予想）", box="per", val="per", unit="x",
                    findex_col="per", findex_scale=1.0, aux=["eps", "profileSettlementYm"]),
    "roe":     dict(text="ROE", box="roe", val="profileRoe", unit="%",
                    findex_col="roe", findex_scale=100.0, aux=["profileShareholdersEquity", "profileSettlementYm"]),
    "marketCapitalHigh": dict(text="時価総額上位", box="totalPriceObj", val="totalPrice", unit="百万円",
                             findex_col="current_market_cap", findex_scale=1e-6, aux=["sharesIssued", "shareUnit"]),
    "marketCapitalLow":  dict(text="時価総額下位", box="totalPriceObj", val="totalPrice", unit="百万円",
                             findex_col="current_market_cap", findex_scale=1e-6, aux=["sharesIssued", "shareUnit"]),
}
DEFAULT_TYPES = ["dividendYield", "lowPbr", "highPbr", "lowPer", "highPer", "roe", "marketCapitalHigh"]
# 相対乖離（|findex-Yahoo|/|Yahoo|）がこの値超を不具合候補としてフラグ。配当利回り/ROEは%なので緩め。
FLAG_REL = 0.05


def _extract_state(html: str) -> dict:
    i = html.find("__PRELOADED_STATE__")
    if i < 0:
        raise ValueError("__PRELOADED_STATE__ not found")
    start = html.find("{", i)
    depth = 0
    for j in range(start, len(html)):
        c = html[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[start:j + 1])
    raise ValueError("unbalanced braces in __PRELOADED_STATE__")


def _num(s) -> float | None:
    """'+8.49' / '34,800.00' / '---' / '' → float|None。"""
    if s is None:
        return None
    t = str(s).replace(",", "").replace("+", "").strip()
    if t in ("", "---", "--", "-"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def fetch_ranking(session: requests.Session, slug: str, max_pages: int | None) -> list[dict]:
    """1種別を巡回し行リストを返す。max_pages=None で全ページ。"""
    spec = RANKINGS[slug]
    rows: list[dict] = []
    page = 1
    total_page = 1
    while page <= total_page:
        r = session.get(BASE.format(slug=slug), params={"market": "all", "page": page},
                        headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        state = _extract_state(r.text)
        ml = state["mainRankingList"]
        total_page = ml.get("paging", {}).get("totalPage", 1)
        for res in ml["results"]:
            box = (res.get("rankingResult") or {}).get(spec["box"]) or {}
            rows.append({
                "ranking_type": slug,
                "type_text": spec["text"],
                "rank": _num(res.get("rank")),
                "code": str(res.get("stockCode", "")).split(".")[0],
                "name": res.get("stockName"),
                "yahoo_market": res.get("marketName"),
                "price": _num(res.get("savePrice")),
                "yahoo_value": _num(box.get(spec["val"])),
                "unit": spec["unit"],
                "update_dt": box.get("updateDateTime") or res.get("date"),
                "settlement_ym": box.get("profileSettlementYm"),
                "aux": json.dumps({k: box.get(k) for k in spec["aux"]}, ensure_ascii=False),
            })
        last = ml.get("paging", {})
        print(f"  [{slug}] page {page}/{total_page}: {len(ml['results'])}件 "
              f"(累計 {len([x for x in rows if x['ranking_type']==slug])}) totalSize={last.get('totalSize')}")
        page += 1
        if max_pages is not None and page > max_pages:
            break
        if page <= total_page:
            time.sleep(SLEEP_BETWEEN)
    return rows


def load_findex(conn: sqlite3.Connection) -> dict[str, dict]:
    cols = ["div_yield", "per", "pbr", "current_market_cap", "roe"]
    q = f"SELECT code, {', '.join(cols)}, status_json FROM computed_metrics"
    out: dict[str, dict] = {}
    for row in conn.execute(q):
        code = row[0]
        d = {c: row[1 + i] for i, c in enumerate(cols)}
        d["status_json"] = row[-1]
        out[code] = d
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", default=",".join(DEFAULT_TYPES),
                    help=f"カンマ区切りの種別、または 'all'。既定={','.join(DEFAULT_TYPES)}")
    ap.add_argument("--pages", type=int, default=4, help="各種別の取得ページ数上限（既定4＝上位約200）")
    ap.add_argument("--all-pages", action="store_true", help="全ページ取得（ページ数上限を無視）")
    ap.add_argument("--compare", action="store_true", help="findex computed_metrics と突合してサマリ＋CSV出力")
    args = ap.parse_args()

    types = list(RANKINGS) if args.types == "all" else [t.strip() for t in args.types.split(",") if t.strip()]
    bad = [t for t in types if t not in RANKINGS]
    if bad:
        sys.exit(f"未知の種別: {bad}\n選択肢: {list(RANKINGS)}")
    max_pages = None if args.all_pages else args.pages

    print(f"Yahoo ランキング断面取得: types={types} pages={'all' if max_pages is None else max_pages}")
    all_rows: list[dict] = []
    with requests.Session() as s:
        for k, slug in enumerate(types):
            all_rows += fetch_ranking(s, slug, max_pages)
            if k < len(types) - 1:
                time.sleep(SLEEP_BETWEEN)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    logs = Path(__file__).resolve().parent.parent / "logs"
    snap_csv = logs / f"yahoo_ranking_snapshot_{ts}.csv"
    fields = ["ranking_type", "type_text", "rank", "code", "name", "yahoo_market",
              "price", "yahoo_value", "unit", "update_dt", "settlement_ym", "aux"]
    with snap_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)
    print(f"\n断面CSV: {snap_csv}  （{len(all_rows)}行・{len(types)}種別）")

    if not args.compare:
        print("（--compare で findex 突合サマリを表示）")
        return

    conn = sqlite3.connect(config.DB_PATH)
    findex = load_findex(conn)
    conn.close()

    cmp_rows: list[dict] = []
    for r in all_rows:
        spec = RANKINGS[r["ranking_type"]]
        f = findex.get(r["code"])
        yv = r["yahoo_value"]
        fcol = spec["findex_col"]
        fv = None
        if f is not None and f.get(fcol) is not None:
            fv = f[fcol] * spec["findex_scale"]
        rel = None
        if yv not in (None, 0) and fv is not None:
            rel = (fv - yv) / abs(yv)
        st = None
        if f is not None and f.get("status_json"):
            try:
                st = json.loads(f["status_json"]).get(fcol if fcol != "current_market_cap" else "market_cap")
            except Exception:
                st = None
        cmp_rows.append({**{k: r[k] for k in ("ranking_type", "rank", "code", "name", "unit")},
                         "yahoo_value": yv, "findex_value": None if fv is None else round(fv, 4),
                         "rel_diff": None if rel is None else round(rel, 4),
                         "findex_status": st, "in_findex": r["code"] in findex})

    cmp_csv = logs / f"yahoo_ranking_compare_{ts}.csv"
    with cmp_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cmp_rows[0].keys()))
        w.writeheader()
        w.writerows(cmp_rows)

    print(f"\n=== findex 突合サマリ（種別別）===")
    print(f"{'種別':<18} {'Yahoo件':>6} {'両方値':>6} {'未収載':>6} {'NULL':>6} {'中央rel':>8} {'最大rel':>8} {'5%超':>5}")
    for slug in types:
        sub = [c for c in cmp_rows if c["ranking_type"] == slug]
        both = [c for c in sub if c["rel_diff"] is not None]
        notin = [c for c in sub if not c["in_findex"]]
        nullv = [c for c in sub if c["in_findex"] and c["findex_value"] is None]
        flagged = [c for c in both if abs(c["rel_diff"]) > FLAG_REL]
        med = statistics.median([abs(c["rel_diff"]) for c in both]) if both else float("nan")
        mx = max([abs(c["rel_diff"]) for c in both]) if both else float("nan")
        print(f"{slug:<18} {len(sub):>6} {len(both):>6} {len(notin):>6} {len(nullv):>6} "
              f"{med:>7.1%} {mx:>7.1%} {len(flagged):>5}")

    flagged_all = sorted((c for c in cmp_rows if c["rel_diff"] is not None and abs(c["rel_diff"]) > FLAG_REL),
                         key=lambda c: abs(c["rel_diff"]), reverse=True)
    print(f"\n=== 乖離 {FLAG_REL:.0%} 超の不具合候補: {len(flagged_all)}件（上位25・基準差/分割漏れ/鮮度差を要弁別）===")
    print(f"{'種別':<16} {'code':>5} {'銘柄':<14} {'Yahoo':>10} {'findex':>10} {'rel':>8} {'status':>8}")
    for c in flagged_all[:25]:
        nm = (c["name"] or "")[:13]
        print(f"{c['ranking_type']:<16} {c['code']:>5} {nm:<14} {str(c['yahoo_value']):>10} "
              f"{str(c['findex_value']):>10} {c['rel_diff']:>+8.1%} {str(c['findex_status']):>8}")
    print(f"\n突合CSV: {cmp_csv}")


if __name__ == "__main__":
    main()
