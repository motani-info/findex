"""financial_snapshots 構築: J-Quants（基礎財務）＋EDINET（深いBS）をマージ。

- 基礎財務(PL/BS/CF/株数)=J-Quants /fins/summary（年次FY確報・約2年窓）
- 深いBS(capex/投資有価証券/有利子負債/支払利息/利益剰余金/流動資産/負債合計)=EDINET最新有報
- accounting_standard は EDINET DEI（権威）優先・無ければ J-Quants DocType を stocks に記録
- 値が取れなければ NULL（捏造しない）。5状態statusは導出層で accounting_standard と
  ラベル辞書から再構成する（financial_snapshots は生値保持・D3）。
"""
from __future__ import annotations

from datetime import datetime

from .edinet import DEEP_FIELDS, EdinetFetcher
from .jquants import FinancialsFetcher


def _load_code_meta(conn, codes: list[str]) -> dict[str, dict]:
    qs = ",".join("?" * len(codes))
    rows = conn.execute(
        f"SELECT code, edinet_code, fiscal_period_end_month FROM stocks WHERE code IN ({qs})",
        codes,
    ).fetchall()
    return {r[0]: {"edinet_code": r[1], "month": r[2]} for r in rows}


def build_financials(conn, codes: list[str], *, resume: bool = True) -> dict:
    """コホート/指定銘柄の financial_snapshots を構築。"""
    now = datetime.now().isoformat(timespec="seconds")
    meta = _load_code_meta(conn, codes)

    # 1) J-Quants 基礎財務（年次）
    jq = FinancialsFetcher().run(codes, resume=resume)

    # 2) EDINET 深いBS（最新有報）
    c2e = {c: meta[c]["edinet_code"] for c in codes if meta.get(c, {}).get("edinet_code")}
    c2m = {c: meta[c]["month"] for c in codes}
    ed = EdinetFetcher(c2e, c2m).run(codes, resume=resume)

    from .jquants import JQ_BASE_MAP

    base_cols = list(JQ_BASE_MAP.keys())
    deep_cols = list(DEEP_FIELDS)
    value_cols = base_cols + deep_cols
    all_cols = ["code", "fiscal_year", *value_cols, "source", "confidence", "as_of", "collected_at"]
    placeholders = ",".join("?" * len(all_cols))
    set_clause = ",".join(
        f"{c}=excluded.{c}" for c in (*value_cols, "source", "confidence", "as_of", "collected_at")
    )
    insert_sql = (
        f"INSERT INTO financial_snapshots ({','.join(all_cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(code, fiscal_year) DO UPDATE SET {set_clause}"
    )
    n_rows = n_deep = 0
    std_set = 0
    for code in codes:
        fy_list = jq.ok.get(code, [])
        erec = ed.ok.get(code)
        deep_fy = erec.fiscal_year if erec else None
        # accounting_standard: EDINET DEI 優先
        std = (erec.accounting_standard if erec else None)
        if not std and fy_list:
            std = next((f.accounting_standard for f in reversed(fy_list) if f.accounting_standard), None)
        if std:
            conn.execute("UPDATE stocks SET accounting_standard=?, updated_at=? WHERE code=?",
                         (std, now, code))
            std_set += 1

        for fin in fy_list:
            row = {c: fin.base.get(c) for c in base_cols}
            source = "jquants"
            # 最新年度に EDINET 深いBSをマージ
            if erec and fin.fiscal_year == deep_fy:
                for f in deep_cols:
                    row[f] = erec.values.get(f)
                source = "jquants+edinet"
                n_deep += 1
            else:
                for f in deep_cols:
                    row[f] = None
            values = [code, fin.fiscal_year, *[row[c] for c in value_cols],
                      source, "present", fin.period_end, now]
            conn.execute(insert_sql, values)
            n_rows += 1

        # EDINETの有報年度がJ-Quants実績に無い場合、深いBSのみの行を残す（捨てない）
        jq_years = {f.fiscal_year for f in fy_list}
        if erec and deep_fy and deep_fy not in jq_years:
            row = {c: None for c in base_cols}
            for f in deep_cols:
                row[f] = erec.values.get(f)
            values = [code, deep_fy, *[row[c] for c in value_cols],
                      "edinet", "present", erec.period_end, now]
            conn.execute(insert_sql, values)
            n_rows += 1
            n_deep += 1
    conn.commit()
    return {
        "jq": jq.summary,
        "edinet": ed.summary,
        "snapshot_rows": n_rows,
        "rows_with_deep": n_deep,
        "accounting_standard_set": std_set,
    }
