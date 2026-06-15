"""評価層（v4）: computed_metrics → dividend_scores。

D4 §1 の **status_based Nullポリシー**（動的分母）が核心:
  ok/zero_legit のみ分子・分母に算入。missing/insufficient/censored は両方から除外
  （持っていないデータで罰しない）。「薄いデータで高得点」はスコアでなく claim別グレードで抑える。

D4.5 較正: ①YoC質ゲート（dividend_quality で生スコアを×1.0/0.5/0.3）②自己資本比率70%/ROE15%
③営業利益率は業種相対（sector33内パーセンタイル・母数不足は絶対閾値フォールバック）。
動的入れ替え: large_cap/financial で roic→利益剰余金倍率、net_cash_per→ミックス係数、金融は自己資本比率除外。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import yaml

from .. import config

_SCORED_STATUS = ("ok", "zero_legit")  # 分子・分母に算入する状態
_QUALITY_FACTOR = {"sound": 1.0, "payout_driven": 0.5, "cyclical": 0.3}


def load_rules(path=None) -> dict:
    """rules.yaml を読み込む（rules リスト＋分類設定＋version_tag）。"""
    p = path or config.RULES_PATH
    with open(p, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc


def rules_sha256(path=None) -> str:
    p = path or config.RULES_PATH
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _raw_score(value, rule) -> float:
    """1指標の生スコア（0〜max_score）。値の有無・status判定は呼び出し側の責務。"""
    max_score = rule.get("max_score", 10)
    threshold = rule["threshold"]
    direction = rule["direction"]
    upper_cap = rule.get("upper_cap")
    penalty_cap = rule.get("penalty_cap")
    if value is None or threshold == 0:
        return 0.0
    # upper_cap ペナルティゾーン（direction=high・上限超過）: cap で満点、2×cap で0点
    if upper_cap is not None and direction == "high" and value > upper_cap:
        overshoot = (value - upper_cap) / upper_cap
        return round(max(0.0, max_score * (1.0 - overshoot)), 4)
    # penalty_cap ハードキャップ（direction=low・上限以上→0点）
    if penalty_cap is not None and direction == "low" and value >= penalty_cap:
        return 0.0
    # direction=low で値が0以下＝「タダ以下」＝満点（ネットキャッシュPER負など）
    if direction == "low" and value <= 0:
        return float(max_score)
    if direction == "high":
        raw = value / threshold * max_score
    else:
        raw = threshold / value * max_score
    return round(min(max_score, max(0.0, raw)), 4)


def select_rules(rules: list[dict], market_cap, sector, *, large_cap_threshold, financial_sectors) -> list[dict]:
    """銘柄属性に応じた適用ルールセット（large_cap/financial の入れ替え）。"""
    is_large = bool(market_cap and market_cap >= large_cap_threshold)
    is_fin = sector in financial_sectors if sector else False
    replaced: set[str] = set()
    active: list[dict] = []
    for r in rules:  # 代替指標（applies_to）を先に評価
        if not r.get("available", True) or not r.get("applies_to"):
            continue
        if (is_large and "large_cap" in r["applies_to"]) or (is_fin and "financial" in r["applies_to"]):
            active.append(r)
            replaced.add(r["replaces"])
    for r in rules:  # 基本指標
        if not r.get("available", True) or r.get("applies_to"):
            continue
        if r["field"] in replaced:
            continue
        if is_fin and r["field"] == "equity_ratio":
            continue  # 金融株は自己資本比率を除外（構造的に低く出る）
        active.append(r)
    return active


def _pct_rank(value, values: list[float], max_score: float) -> float:
    """業種内パーセンタイル順位×max_score（below+0.5×equal / n）。"""
    n = len(values)
    if n == 0:
        return 0.0
    below = sum(1 for x in values if x < value)
    equal = sum(1 for x in values if x == value)
    return round((below + 0.5 * equal) / n * max_score, 4)


def score_one(metrics: dict, status: dict, active: list[dict], *,
              sector_margins: list[float], min_sector_n: int) -> dict:
    """1銘柄のスコア（status_based 動的分母）。"""
    raw_scores: dict[str, float] = {}
    weighted: dict[str, float] = {}
    num = den = 0.0
    excluded: dict[str, str] = {}
    for r in active:
        field = r["field"]
        st = status.get(field)
        weight = r.get("weight", 1.0)
        max_score = r.get("max_score", 10)
        if st not in _SCORED_STATUS:
            excluded[field] = st or "missing"  # 分子・分母から除外（薄データで罰しない）
            continue
        value = metrics.get(field)
        # 営業利益率の業種相対（母数充足時）。不足なら絶対閾値フォールバック
        if r.get("scoring") == "sector_relative" and len(sector_margins) >= min_sector_n:
            rs = _pct_rank(value, sector_margins, max_score)
        else:
            rs = _raw_score(value, r)
        # YoC質ゲート（dividend_quality で減点）
        if r.get("quality_gate"):
            rs *= _QUALITY_FACTOR.get(metrics.get("dividend_quality"), 1.0)
            rs = round(rs, 4)
        raw_scores[field] = rs
        weighted[field] = round(rs * weight, 4)
        num += rs * weight
        den += max_score * weight
    total = round(num / den * 100, 2) if den else 0.0
    return {
        "total": total, "raw": raw_scores, "weighted": weighted,
        "excluded": excluded, "den_weight": round(den, 2), "n_scored": len(raw_scores),
    }


def _ensure_rule_version(conn, version_tag: str) -> int:
    sha = rules_sha256()
    row = conn.execute("SELECT id FROM rule_versions WHERE rules_sha256=?", (sha,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO rule_versions (rules_sha256, version_tag, created_at) VALUES (?,?,?)",
        (sha, version_tag, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return cur.lastrowid


def build_scores(conn, codes: list[str]) -> dict:
    """コホート/指定銘柄を採点し dividend_scores に記録。ランキング配列を返す。"""
    doc = load_rules()
    rules = doc["rules"]
    cls = doc.get("classification", {})
    large_cap_threshold = cls.get("large_cap_threshold", 1_000_000_000_000)
    financial_sectors = cls.get("financial_sectors", [])
    min_sector_n = doc.get("min_sector_n", 4)
    version_tag = doc.get("version_tag", "v4")
    rule_version_id = _ensure_rule_version(conn, version_tag)
    now = datetime.now().isoformat(timespec="seconds")

    cols = [r[1] for r in conn.execute("PRAGMA table_info(computed_metrics)")]
    rows: dict[str, dict] = {}
    sector_of: dict[str, str | None] = {}
    for code in codes:
        m = conn.execute(
            f"SELECT {','.join(cols)} FROM computed_metrics WHERE code=?", (code,)
        ).fetchone()
        if not m:
            continue
        metrics = dict(zip(cols, m))
        metrics["status"] = json.loads(metrics["status_json"]) if metrics.get("status_json") else {}
        sec = conn.execute("SELECT sector33 FROM stocks WHERE code=?", (code,)).fetchone()
        sector_of[code] = sec[0] if sec else None
        rows[code] = metrics

    # Pass1: 業種別 operating_margin（status ok）を集める
    sector_margins: dict[str | None, list[float]] = {}
    for code, m in rows.items():
        if m["status"].get("operating_margin") == "ok" and m.get("operating_margin") is not None:
            sector_margins.setdefault(sector_of[code], []).append(m["operating_margin"])

    # Pass2: 採点
    ranking = []
    for code, m in rows.items():
        active = select_rules(
            rules, m.get("current_market_cap"), sector_of[code],
            large_cap_threshold=large_cap_threshold, financial_sectors=financial_sectors,
        )
        sj = score_one(
            m, m["status"], active,
            sector_margins=sector_margins.get(sector_of[code], []), min_sector_n=min_sector_n,
        )
        grades = (m.get("grade_dividend"), m.get("grade_valuation"),
                  m.get("grade_health"), m.get("grade_capital"))
        conn.execute(
            "INSERT INTO dividend_scores (code, scored_at, rule_version_id, total_score, "
            "grade_dividend, grade_valuation, grade_health, grade_capital, score_json) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(code, scored_at) DO UPDATE SET "
            "rule_version_id=excluded.rule_version_id, total_score=excluded.total_score, "
            "grade_dividend=excluded.grade_dividend, grade_valuation=excluded.grade_valuation, "
            "grade_health=excluded.grade_health, grade_capital=excluded.grade_capital, "
            "score_json=excluded.score_json",
            (code, now, rule_version_id, sj["total"], *grades,
             json.dumps(sj, ensure_ascii=False)),
        )
        ranking.append({"code": code, "total": sj["total"], "n_scored": sj["n_scored"],
                        "grade_dividend": grades[0], "grade_valuation": grades[1],
                        "grade_health": grades[2], "grade_capital": grades[3], "score": sj})
    conn.commit()
    ranking.sort(key=lambda x: x["total"], reverse=True)
    return {"rows": len(ranking), "rule_version_id": rule_version_id,
            "version_tag": version_tag, "scored_at": now, "ranking": ranking}
