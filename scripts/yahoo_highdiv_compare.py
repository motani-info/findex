#!/usr/bin/env python
"""Yahoo!ファイナンス「高配当」スクリーニング（約668件）の予想配当利回りを取り込み、
findex の div_yield と全件突合して乖離＝不具合候補を検出する検証ツール（柱1データ完全性）。

源泉: https://finance.yahoo.co.jp/stocks/screening/highdividend （?page=1..14・各50件）。
各ページに __PRELOADED_STATE__ JSON が埋まっており、screeningResults[].stockCode /
shareDividendYield（＝Yahooの予想配当利回り%）を持つ。サーバHTML＝JS不要・スクリプタブル。

これは検証専用（読み取りのみ）。findex のパイプラインは一切変更しない。Yahoo への外向き取得は
14ページのみ・ページ間に礼儀的スリープ。実行: `uv run python scripts/yahoo_highdiv_compare.py`。

注意（鮮度差の解釈）: この環境の J-Quants 会社予想は開示が遅延し得る。Yahoo は当日値。
findex 側を最新の `dividends-jq --all` → `derive --all` で更新してから突合すると、残る乖離＝
真の不具合に絞り込める（鮮度を揃える前は乖離に鮮度差が混じる）。
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from findex import config  # noqa: E402

URL = "https://finance.yahoo.co.jp/stocks/screening/highdividend"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
SLEEP_BETWEEN_PAGES = 1.5      # 礼儀的レート（外向き取得）
DELTA_FLAG = 1.0               # |findex% − Yahoo%| がこの値(pt)超を不具合候補としてフラグ


def _extract_preloaded_state(html: str) -> dict:
    """HTML から __PRELOADED_STATE__ の JSON を波括弧マッチで取り出す。"""
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


def fetch_yahoo_highdiv(session: requests.Session) -> dict[str, dict]:
    """全ページを巡回し {code4: {yahoo_yield, price, per, pbr, roe, name}} を返す。"""
    out: dict[str, dict] = {}
    page = 1
    total_page = 1
    while page <= total_page:
        r = session.get(URL, params={"page": page}, headers={"User-Agent": UA}, timeout=30)
        r.raise_for_status()
        state = _extract_preloaded_state(r.text)
        ms = state["mainScreening"]["response"]
        total_page = ms["paging"]["totalPage"]
        for row in ms["screeningResults"]:
            code = row["stockCode"].split(".")[0]   # "7203.T" -> "7203"
            out[code] = {
                "name": row.get("displayName"),
                "yahoo_yield": row.get("shareDividendYield"),  # 予想配当利回り(%)
                "price": row.get("price"),
                "per": row.get("per"),
                "pbr": row.get("pbr"),
                "roe": row.get("roe"),
            }
        print(f"  page {page}/{total_page}: {len(ms['screeningResults'])}件 "
              f"(累計 {len(out)})  lastUpdate={ms.get('lastUpdate')}")
        page += 1
        if page <= total_page:
            time.sleep(SLEEP_BETWEEN_PAGES)
    return out


def load_findex(conn: sqlite3.Connection) -> dict[str, dict]:
    """findex 側の div_yield(%)・予想/実績の別・予想DPS・status を code 別に。"""
    rows = conn.execute(
        "SELECT c.code, c.div_yield, c.annual_div, "
        "       json_extract(c.source_json,'$.div_yield'), "
        "       json_extract(c.status_json,'$.div_yield'), "
        "       f.forecast_dps, f.forecast_fy, f.as_of "
        "FROM computed_metrics c "
        "LEFT JOIN dividend_forecast f ON f.code=c.code"
    ).fetchall()
    out = {}
    for code, dy, annual, src, st, fdps, ffy, fasof in rows:
        out[code] = {
            "findex_yield": None if dy is None else dy * 100,
            "annual_div": annual, "div_source": src, "div_status": st,
            "forecast_dps": fdps, "forecast_fy": ffy, "forecast_asof": fasof,
        }
    return out


def main() -> None:
    print("Yahoo 高配当スクリーニング取得中 …")
    with requests.Session() as s:
        yahoo = fetch_yahoo_highdiv(s)
    print(f"Yahoo: {len(yahoo)}銘柄")

    conn = sqlite3.connect(config.DB_PATH)
    findex = load_findex(conn)
    conn.close()

    merged = []
    for code, y in yahoo.items():
        f = findex.get(code, {})
        fy = f.get("findex_yield")
        yy = y["yahoo_yield"]
        delta = (fy - yy) if (fy is not None and yy is not None) else None
        merged.append({
            "code": code, "name": y["name"],
            "yahoo_yield": yy, "findex_yield": fy,
            "delta": delta,
            "div_source": f.get("div_source"), "div_status": f.get("div_status"),
            "forecast_dps": f.get("forecast_dps"), "forecast_fy": f.get("forecast_fy"),
            "annual_div": f.get("annual_div"), "forecast_asof": f.get("forecast_asof"),
            "in_findex": code in findex,
        })

    # 出力CSV（logs=非追跡）
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_csv = Path(__file__).resolve().parent.parent / "logs" / f"yahoo_highdiv_compare_{ts}.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(merged[0].keys()))
        w.writeheader()
        w.writerows(merged)

    # サマリ
    have_both = [m for m in merged if m["delta"] is not None]
    missing = [m for m in merged if m["findex_yield"] is None]
    not_in_findex = [m for m in merged if not m["in_findex"]]
    flagged = sorted((m for m in have_both if abs(m["delta"]) > DELTA_FLAG),
                     key=lambda m: abs(m["delta"]), reverse=True)

    print(f"\n=== 突合サマリ（Yahoo高配当 {len(yahoo)}件）===")
    print(f"両方に利回りあり: {len(have_both)}")
    print(f"findex未収載(コード自体なし): {len(not_in_findex)}")
    print(f"findexで利回りNULL(missing/stale/suspect/無配予想): {len(missing)}")
    if have_both:
        import statistics
        ad = [abs(m["delta"]) for m in have_both]
        print(f"|乖離| 中央値={statistics.median(ad):.2f}pt 平均={statistics.mean(ad):.2f}pt "
              f"最大={max(ad):.2f}pt")
    print(f"\n=== 乖離 {DELTA_FLAG}pt 超の不具合候補: {len(flagged)}件（上位30）===")
    print(f"{'code':>6} {'銘柄':<14} {'Yahoo':>6} {'findex':>7} {'Δpt':>7} {'src':>8} "
          f"{'予想DPS':>7} {'予想FY':>6} {'実績':>7}")
    for m in flagged[:30]:
        nm = (m["name"] or "")[:13]
        print(f"{m['code']:>6} {nm:<14} {m['yahoo_yield']:>6.2f} "
              f"{m['findex_yield']:>7.2f} {m['delta']:>+7.2f} {str(m['div_source']):>8} "
              f"{str(m['forecast_dps']):>7} {str(m['forecast_fy']):>6} {str(m['annual_div']):>7}")
    print(f"\nCSV: {out_csv}")


if __name__ == "__main__":
    main()
