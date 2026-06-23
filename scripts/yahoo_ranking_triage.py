#!/usr/bin/env python
"""Yahoo多軸ランキング断面（yahoo_ranking_snapshot.py の全件出力）を findex と突合し、
銘柄ごとに「どの軸でどれだけズレるか」を横断して**根因を多視点で分類**する整理ツール（柱1）。

設計の肝＝1つのデータ異常が複数軸に残す“符号・係数のパターン”で真因を切り分ける:
  - 株数が係数k倍ずれる   → PBR・PER・時価総額が ×k（同方向）、配当利回りは ÷k、ROEは無影響
  - 分割未適用/欠落       → 上と同型（株数/1株指標の基準ズレ）
  - PER だけズレる        → 会社予想EPS vs findex確報EPS の基準差（即バグでない）
  - ROE だけズレる        → ROE定義/期間差
  - PBR だけズレる        → BPS/自己資本の基準差（株数ではない）
  - 時価総額だけズレる     → 発行済 vs 上場株式数（自己株/浮動株）の基準差
これにより「1軸では異常でも多軸で見れば正当（逆も）」を判別する。

入力: 最新の logs/yahoo_ranking_snapshot_*.csv（全5軸・全件）＋ findex DB。
出力: logs/yahoo_ranking_triage_<ts>.csv（銘柄×軸のワイド表＋分類）と同名 .md（集計レポート）。
読み取り専用。実行: uv run python scripts/yahoo_ranking_triage.py
"""
from __future__ import annotations

import csv
import glob
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from findex import config  # noqa: E402

# 軸 → (snapshotのranking_type, findex列, findex→Yahoo単位係数, 単位)
AXES = {
    "yield": ("dividendYield", "div_yield", 100.0, "%"),
    "pbr":   ("lowPbr", "pbr", 1.0, "x"),
    "per":   ("lowPer", "per", 1.0, "x"),
    "roe":   ("roe", "roe", 100.0, "%"),
    "mcap":  ("marketCapitalHigh", "current_market_cap", 1e-6, "百万円"),
}
TOL = 0.15           # |rel| がこの値超を「ズレ軸」とみなす（~8%の系統床より上の本物の信号）
TOL_CLEAN = 0.05     # 整合の厳しめ基準（レポートの参考）
FACTOR_DEV = 0.30    # 係数が1からこれ以上離れたら「factorずれ」（多軸一致の判定に使用）


def _num(s):
    if s in (None, ""):
        return None
    try:
        return float(str(s).replace(",", "").replace("+", ""))
    except ValueError:
        return None


def load_snapshot():
    files = sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "logs" / "yahoo_ranking_snapshot_*.csv")))
    if not files:
        sys.exit("snapshot CSV が無い。先に yahoo_ranking_snapshot.py --all-pages を実行")
    path = files[-1]
    # (axis_key, code) -> {yahoo, name, aux}
    type2axis = {v[0]: k for k, v in AXES.items()}
    snap = {}
    names = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        ax = type2axis.get(r["ranking_type"])
        if ax is None:
            continue
        code = r["code"]
        snap[(ax, code)] = {"yahoo": _num(r["yahoo_value"]), "aux": r["aux"]}
        if r["name"]:
            names.setdefault(code, r["name"])
    return path, snap, names


def load_findex(conn):
    cols = ["div_yield", "per", "pbr", "current_market_cap", "roe"]
    fx = {}
    for row in conn.execute(f"SELECT code, {', '.join(cols)}, status_json FROM computed_metrics"):
        code = row[0]
        fx[code] = {c: row[1 + i] for i, c in enumerate(cols)}
        fx[code]["status_json"] = row[-1]
    # 最新FYのbps/eps/shares/equity ＋ 分割有無（根因の裏取り用）
    snaps = {}
    for code, bps, eps, sh, eq in conn.execute(
        "SELECT f.code, f.bps, f.eps, f.shares_outstanding, f.equity_attributable "
        "FROM financial_snapshots f JOIN (SELECT code, MAX(fiscal_year) my FROM financial_snapshots GROUP BY code) m "
        "ON m.code=f.code AND m.my=f.fiscal_year"):
        snaps[code] = dict(bps=bps, eps=eps, shares=sh, equity=eq)
    has_split = {r[0] for r in conn.execute("SELECT DISTINCT code FROM stock_splits")}
    return fx, snaps, has_split


# 軸の性質を分ける（多視点判定の核）:
#   DATA軸 = findexが正しければYahooと一致すべき → ズレ＝柱1の疑い
#   BASIS軸 = 定義/予想の差で構造的にズレる → 単独のズレはデータ健全（即バグでない）
DATA_AXES = {"pbr", "mcap", "yield"}
BASIS_AXES = {"per", "roe"}


def _consistent(facs):
    """係数群が同方向＆1から乖離＆倍率が揃っているか（株数/分割の符号）。"""
    facs = [f for f in facs if f]
    if len(facs) < 2:
        return None
    same = all(f > 1 + FACTOR_DEV for f in facs) or all(f < 1 - FACTOR_DEV for f in facs)
    if same and max(facs) / min(facs) < 1.8:
        return statistics.median(facs)
    return None


def classify(per_axis: dict):
    """per_axis: axis -> {'rel':, 'factor':}（両方値ありの軸のみ）。分類ラベルとメモを返す。

    多視点の肝: 時価総額(=価格×株数)が一致するなら株数は正しい→PBRのズレはBPS/自己資本側、
    と切り分ける。BASIS軸(PER/ROE)だけのズレはデータ健全とみなす。
    """
    dev = {a: d for a, d in per_axis.items() if d["rel"] is not None and abs(d["rel"]) > TOL}
    if not per_axis:
        return "比較不能(findex値なし)", ""
    if not dev:
        return "整合", ""
    dev_data = {a for a in dev if a in DATA_AXES}
    dev_basis = {a for a in dev if a in BASIS_AXES}
    basis_note = ("+" + "/".join(f"{a}{dev[a]['rel']:+.0%}" for a in sorted(dev_basis))) if dev_basis else ""

    # BASIS軸だけ → 予想EPS/ROE定義の差＝データ健全
    if not dev_data:
        return "基準差のみ(PER予想/ROE定義・データ健全)", "/".join(f"{a}:{dev[a]['rel']:+.0%}" for a in sorted(dev))

    # 株数/分割の符号: 時価総額がズレ、かつ PBR か PER も同方向・同係数でズレる
    if "mcap" in dev and ({"pbr", "per"} & set(dev)):
        k = _consistent([per_axis[a]["factor"] for a in ("pbr", "per", "mcap") if a in dev])
        if k:
            note = f"k≈{k:.2f} 軸={'/'.join(a for a in ('pbr','per','mcap') if a in dev)}"
            if "yield" in per_axis and per_axis["yield"]["factor"]:
                yf = per_axis["yield"]["factor"]
                if (k > 1 and yf < 0.9) or (k < 1 and yf > 1.1):
                    note += f" +利回り÷k一致({yf:.2f})"
            return "株数/分割基準(多軸一致)", note
    # PER欠落(赤字)で pbr+mcap だけでも同係数なら株数/分割
    if dev_data == {"pbr", "mcap"} and "per" not in per_axis:
        k = _consistent([per_axis["pbr"]["factor"], per_axis["mcap"]["factor"]])
        if k:
            return "株数/分割基準(多軸一致)", f"k≈{k:.2f} 軸=pbr/mcap(PER欠)"

    # 単一データ軸（時価総額が一致＝株数は正しい、の含意で切り分け）
    if dev_data == {"pbr"}:
        return "PBR/自己資本(BPS)基準差", f"pbr {dev['pbr']['rel']:+.0%} {basis_note}".strip()
    if dev_data == {"mcap"}:
        return "時価総額の株数基準(自己株/浮動)", f"mcap {dev['mcap']['rel']:+.0%} {basis_note}".strip()
    if dev_data == {"yield"}:
        return "配当の予想/鮮度差", f"yield {dev['yield']['rel']:+.0%} {basis_note}".strip()
    return "多軸混在(要確認)", "/".join(f"{a}:{dev[a]['rel']:+.0%}" for a in sorted(dev_data)) + " " + basis_note


def main():
    snap_path, snap, names = load_snapshot()
    conn = sqlite3.connect(config.DB_PATH)
    fx, fsnaps, has_split = load_findex(conn)
    conn.close()

    codes = sorted({c for (_, c) in snap})
    rows = []
    for code in codes:
        in_fx = code in fx
        per_axis = {}
        wide = {"code": code, "name": names.get(code), "in_findex": in_fx}
        for ax, (_rt, fcol, scale, _u) in AXES.items():
            sv = snap.get((ax, code))
            yv = sv["yahoo"] if sv else None
            fv = None
            if in_fx and fx[code].get(fcol) is not None:
                fv = fx[code][fcol] * scale
            rel = ((fv - yv) / abs(yv)) if (yv not in (None, 0) and fv is not None) else None
            factor = (fv / yv) if (yv not in (None, 0) and fv is not None) else None
            wide[f"y_{ax}"] = None if yv is None else round(yv, 4)
            wide[f"f_{ax}"] = None if fv is None else round(fv, 4)
            wide[f"rel_{ax}"] = None if rel is None else round(rel, 4)
            if rel is not None:
                per_axis[ax] = {"rel": rel, "factor": factor}
        if not in_fx:
            cat, note = "対象外(findex未収載=REIT/ETF等)", ""
        else:
            cat, note = classify(per_axis)
        fsn = fsnaps.get(code, {})
        wide["category"] = cat
        wide["note"] = note
        wide["fx_shares"] = fsn.get("shares")
        wide["fx_bps"] = fsn.get("bps")
        wide["has_split_rec"] = code in has_split
        rows.append(wide)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    logs = Path(__file__).resolve().parent.parent / "logs"
    out_csv = logs / f"yahoo_ranking_triage_{ts}.csv"
    fields = (["code", "name", "in_findex"]
              + [f"{p}_{ax}" for ax in AXES for p in ("y", "f", "rel")]
              + ["category", "note", "fx_shares", "fx_bps", "has_split_rec"])
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # ---- レポート(md) ----
    lines = []
    lines.append(f"# Yahoo多軸ランキング × findex 突合トリアージ（{ts}）\n")
    lines.append(f"- 源泉断面: `{Path(snap_path).name}`")
    lines.append(f"- 対象コード数: {len(codes)}（うち findex収載 {sum(r['in_findex'] for r in rows)}）")
    lines.append(f"- ズレ判定: |相対差| > {TOL:.0%}（~8%の系統床より上の本物の信号）\n")

    lines.append("## 軸別の整合度（findex vs Yahoo・両方値ありのみ）\n")
    lines.append("| 軸 | 比較数 | 中央|rel| | 符号中央 | ≤5% | ≤15% |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for ax in AXES:
        rl = [r[f"rel_{ax}"] for r in rows if r[f"rel_{ax}"] is not None]
        if not rl:
            continue
        a = [abs(x) for x in rl]
        lines.append(f"| {ax} | {len(rl)} | {statistics.median(a):.1%} | {statistics.median(rl):+.1%} | "
                     f"{sum(x<=TOL_CLEAN for x in a)/len(a):.0%} | {sum(x<=TOL for x in a)/len(a):.0%} |")

    lines.append("\n## 根因カテゴリ別の件数\n")
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    lines.append("| カテゴリ | 件数 |")
    lines.append("|---|---:|")
    for cat, rs in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"| {cat} | {len(rs)} |")

    # 要対応カテゴリの代表例
    actionable = ["株数/分割基準(多軸一致)", "PBR/自己資本(BPS)基準差",
                  "時価総額の株数基準(自己株/浮動)", "配当の予想/鮮度差", "多軸混在(要確認)"]
    for cat in actionable:
        rs = by_cat.get(cat, [])
        if not rs:
            continue
        def worst(r):
            return max((abs(r[f"rel_{ax}"]) for ax in AXES if r[f"rel_{ax}"] is not None), default=0)
        rs = sorted(rs, key=worst, reverse=True)
        lines.append(f"\n## 【要対応】{cat}（{len(rs)}件・最大乖離順 上位20）\n")
        lines.append("| code | 銘柄 | rel_pbr | rel_per | rel_mcap | rel_yield | rel_roe | shares | split記録 | note |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|:--:|---|")
        for r in rs[:20]:
            def pc(ax):
                v = r[f"rel_{ax}"]
                return "" if v is None else f"{v:+.0%}"
            nm = (r["name"] or "")[:12]
            lines.append(f"| {r['code']} | {nm} | {pc('pbr')} | {pc('per')} | {pc('mcap')} | {pc('yield')} | "
                         f"{pc('roe')} | {r['fx_shares'] or ''} | {'有' if r['has_split_rec'] else '無'} | {r['note']} |")

    out_md = logs / f"yahoo_ranking_triage_{ts}.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print(f"\nワイドCSV: {out_csv}\nレポート:  {out_md}")


if __name__ == "__main__":
    main()
