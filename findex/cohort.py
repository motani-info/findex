"""検証コホート（約30社）の読み込み。

レート制限を避けるため、実装の検証は全銘柄ではなくこのコホートだけで回す。
docs/design/pre2000-data.md §6 を参照。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class CohortStock:
    code: str
    name: str
    category: str
    expected_growth_years: int | None
    expected_behavior: str
    needs_confirm: bool
    source: str


def load_cohort() -> list[CohortStock]:
    rows: list[CohortStock] = []
    with config.VERIFICATION_COHORT.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            egy = r["expected_growth_years"].strip()
            rows.append(
                CohortStock(
                    code=r["code"].strip(),
                    name=r["name"].strip(),
                    category=r["category"].strip(),
                    expected_growth_years=int(egy) if egy else None,
                    expected_behavior=r["expected_behavior"].strip(),
                    needs_confirm=r["needs_confirm"].strip().lower() == "yes",
                    source=r["source"].strip(),
                )
            )
    return rows


def cohort_codes() -> list[str]:
    return [c.code for c in load_cohort()]
