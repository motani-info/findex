"""洗替の検収（Phase5・F5）。

全データ洗替の結果が信頼に足るかを**読み取り専用**で点検する品質ゲート。
ネットワークに触れず DB だけを見る。出すのは「いま何が揃い・何が欠け・どこが
要注意か」の一覧＝洗替を回したあと「もう一周 fetch すべきか」を判断する材料。

検査項目:
  1. カバレッジ  : 層ごと（listing/price/financial/dividend/derived）に揃った銘柄数
  2. golden 整合 : 公表連続増配（result_overrides）と導出値の一致（最重要の正確性ゲート）
  3. 配当 seam 穴: dividend_annual の年度歯抜け（F3 が censored 化する根＝E2 の規模）
  4. review 率   : 単年アーティファクト隔離（confidence=review）の銘柄数
  5. status 分布 : computed_metrics の status_json 集計（ok/missing/insufficient/...）
"""
from __future__ import annotations

import json
from collections import Counter


def _universe(conn, codes: list[str] | None) -> list[str]:
    if codes:
        return codes
    return [r[0] for r in conn.execute("SELECT code FROM stocks ORDER BY code")]


def _distinct_codes(conn, table: str, codes: set[str]) -> int:
    n = 0
    for (code,) in conn.execute(f"SELECT DISTINCT code FROM {table}"):
        if code in codes:
            n += 1
    return n


def _coverage(conn, codes: list[str]) -> dict:
    s = set(codes)
    total = len(codes)
    listing = sum(
        1 for (c,) in conn.execute("SELECT code FROM stocks WHERE listing_date IS NOT NULL")
        if c in s
    )
    return {
        "total": total,
        "listing_date": listing,
        "price_history": _distinct_codes(conn, "price_history", s),
        "financial_snapshots": _distinct_codes(conn, "financial_snapshots", s),
        "dividend_annual": _distinct_codes(conn, "dividend_annual", s),
        "computed_metrics": _distinct_codes(conn, "computed_metrics", s),
    }


def _golden_check(conn, codes: set[str]) -> dict:
    """公表連続増配（result_overrides）と導出 consecutive_dividend_growth_years の整合。

    override は機械値≦公表値のとき昇格させる仕様ゆえ、導出値は公表値以上であるべき。
    導出値 < 公表値 は配線の異常（最重要の赤信号）。
    """
    rows = conn.execute(
        "SELECT code, value FROM result_overrides WHERE field='consecutive_dividend_growth_years'"
    ).fetchall()
    checked = matched = 0
    mismatches = []
    for code, pub in rows:
        if code not in codes:
            continue
        m = conn.execute(
            "SELECT consecutive_dividend_growth_years FROM computed_metrics WHERE code=?", (code,)
        ).fetchone()
        if not m or m[0] is None:
            mismatches.append({"code": code, "published": pub, "derived": None})
            continue
        checked += 1
        if m[0] >= int(pub):
            matched += 1
        else:
            mismatches.append({"code": code, "published": int(pub), "derived": m[0]})
    return {"checked": checked, "matched": matched, "mismatches": mismatches}


def _seam_holes(conn, codes: set[str]) -> dict:
    """dividend_annual（review除外）の年度歯抜けを集計。F3 が censored 化する根＝E2 の規模。"""
    with_gaps = 0
    seam_2000 = 0  # FY2000-2001 をまたぐ系統的 seam（haitoukin↔events 接合穴）
    gap_year_hist: Counter = Counter()
    series: dict[str, list[int]] = {}
    for code, fy in conn.execute(
        "SELECT code, fiscal_year FROM dividend_annual "
        "WHERE confidence IS NULL OR confidence!='review' ORDER BY code, fiscal_year"
    ):
        if code in codes:
            series.setdefault(code, []).append(fy)
    for code, ys in series.items():
        gaps = [(ys[i - 1], ys[i]) for i in range(1, len(ys)) if ys[i] - ys[i - 1] != 1]
        if gaps:
            with_gaps += 1
            for lo, hi in gaps:
                for missing in range(lo + 1, hi):
                    gap_year_hist[missing] += 1
                if lo <= 2001 and hi >= 2000:
                    seam_2000 += 1
                    break
    return {
        "codes_with_dividends": len(series),
        "codes_with_gaps": with_gaps,
        "fy2000_seam": seam_2000,
        "top_gap_years": gap_year_hist.most_common(6),
    }


def _review_rate(conn, codes: set[str]) -> dict:
    codes_review = set()
    rows = 0
    for code, in_review in conn.execute(
        "SELECT code, COUNT(*) FROM dividend_annual WHERE confidence='review' GROUP BY code"
    ):
        if code in codes:
            codes_review.add(code)
            rows += in_review
    return {"codes_with_review": len(codes_review), "review_rows": rows}


def _status_dist(conn, codes: set[str]) -> dict:
    dist: Counter = Counter()
    for code, sj in conn.execute("SELECT code, status_json FROM computed_metrics"):
        if code not in codes or not sj:
            continue
        for st in json.loads(sj).values():
            dist[st] += 1
    return dict(dist.most_common())


def run_verify(conn, codes: list[str] | None = None) -> dict:
    universe = _universe(conn, codes)
    s = set(universe)
    cov = _coverage(conn, universe)
    golden = _golden_check(conn, s)
    seam = _seam_holes(conn, s)
    review = _review_rate(conn, s)
    status = _status_dist(conn, s)

    # 検収判定: golden 配線の赤信号が無いこと（カバレッジは情報・洗替途中でも可）。
    # mismatches には「導出<公表」と「導出欠落」のみ入る＝空なら配線健全。
    golden_ok = not golden["mismatches"]
    return {
        "coverage": cov,
        "golden": golden,
        "golden_ok": golden_ok,
        "seam": seam,
        "review": review,
        "status_dist": status,
    }
