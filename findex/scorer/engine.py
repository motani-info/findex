"""ルールエンジン：YAMLのルール定義に基づき各銘柄をスコアリングする"""
import json
from pathlib import Path
import yaml
import pandas as pd

FINANCIAL_SECTORS = {"銀行業", "保険業", "証券・商品先物取引業", "その他金融業"}


def load_rules(path: str | Path) -> list[dict]:
    with open(path) as f:
        return yaml.safe_load(f)["rules"]


def _score_field(value: float | None, rule: dict) -> float:
    """1指標の生スコアを計算する（0〜max_score）。Nullは0点。"""
    max_score = rule.get("max_score", 10)
    if value is None or pd.isna(value):
        return 0.0

    threshold = rule["threshold"]
    direction = rule["direction"]

    if threshold == 0:
        return 0.0

    if direction == "low" and value == 0:
        # 値が0 = 完全に達成（例: 有利子負債=0 → 満点）
        return float(max_score)

    if value == 0:
        return 0.0

    if direction == "high":
        raw = value / threshold * max_score
    else:  # low
        raw = threshold / value * max_score

    return round(min(max_score, max(0.0, raw)), 4)


def select_rules(rules: list[dict], market_cap: float | None, sector: str | None) -> list[dict]:
    """銘柄属性に応じて適用ルールセットを返す。
    - large_cap（1兆円以上）: ⑨→⑬、⑫→⑭
    - financial: ⑥除外、⑨→⑬、⑫→⑭
    - available=false のルールは常に除外
    """
    is_large_cap = bool(market_cap and market_cap >= 1_000_000_000_000)
    is_financial = sector in FINANCIAL_SECTORS if sector else False

    replaced_fields: set[str] = set()
    active: list[dict] = []

    # Step1: 代替指標（applies_toあり）を評価
    for rule in rules:
        if not rule.get("available", True):
            continue
        applies_to = rule.get("applies_to", [])
        if not applies_to:
            continue
        if (is_large_cap and "large_cap" in applies_to) or \
           (is_financial and "financial" in applies_to):
            active.append(rule)
            replaced_fields.add(rule["replaces"])

    # Step2: 基本指標（置き換えられていないものを追加）
    for rule in rules:
        if not rule.get("available", True):
            continue
        if rule.get("applies_to"):
            continue  # 代替指標は上で処理済み
        if rule["field"] in replaced_fields:
            continue  # 置き換え対象はスキップ
        if is_financial and rule["field"] == "equity_ratio":
            continue  # 金融株は自己資本比率を除外
        active.append(rule)

    return active


def score_one(raw: dict, rules: list[dict]) -> dict:
    """1銘柄分のスコアを計算する。
    Returns:
        {
            "raw":                {field: 0〜10},
            "weighted":           {field: raw × weight},
            "total":              100点換算,
            "max_weighted_total": 満点
        }
    """
    score_raw: dict[str, float] = {}
    score_weighted: dict[str, float] = {}
    max_weighted = 0.0

    for rule in rules:
        field = rule["field"]
        weight = rule.get("weight", 1.0)
        max_score = rule.get("max_score", 10)
        max_weighted += max_score * weight

        raw_score = _score_field(raw.get(field), rule)
        score_raw[field] = raw_score
        score_weighted[field] = round(raw_score * weight, 4)

    total_weighted = sum(score_weighted.values())
    total = round(total_weighted / max_weighted * 100, 2) if max_weighted else 0.0

    return {
        "raw": score_raw,
        "weighted": score_weighted,
        "total": total,
        "max_weighted_total": round(max_weighted, 2),
    }


def score(df: pd.DataFrame, rules: list[dict]) -> pd.DataFrame:
    """DataFrameの全銘柄をスコアリングし、total_score降順で返す。"""
    rows = []
    for _, row in df.iterrows():
        active_rules = select_rules(
            rules,
            market_cap=row.get("market_cap"),
            sector=row.get("sector"),
        )
        raw = {r["field"]: row.get(r["field"]) for r in rules}
        sj = score_one(raw, active_rules)

        out = row.to_dict()
        out["total_score"] = sj["total"]
        out["_score_json"] = json.dumps(sj, ensure_ascii=False)
        # 指標別スコアを列として展開（表示・CSV用）
        for field, val in sj["raw"].items():
            out[f"_score_{field}"] = val
        rows.append(out)

    result = pd.DataFrame(rows)
    return result.sort_values("total_score", ascending=False).reset_index(drop=True)
