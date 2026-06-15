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
    n_rows = n_deep = n_summary = 0
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

        # 年度別に行を集約してからマージ書き込み（J-Quants基礎→EDINET深BS→EDINET5年史）
        rows: dict[int, dict] = {}

        def _blank(src: str, as_of) -> dict:
            r = {c: None for c in value_cols}
            r["_source"], r["_as_of"] = src, as_of
            return r

        # 1) J-Quants 基礎財務（年次・確報）
        for fin in fy_list:
            r = _blank("jquants", fin.period_end)
            for c in base_cols:
                r[c] = fin.base.get(c)
            rows[fin.fiscal_year] = r

        # 2) EDINET 深いBS（最新有報年度のみ。J-Quants行があればマージ）
        if erec and deep_fy:
            r = rows.get(deep_fy)
            if r is None:
                r = _blank("edinet", erec.period_end)
                rows[deep_fy] = r
            for f in deep_cols:
                r[f] = erec.values.get(f)
            if r["_source"] == "jquants":
                r["_source"] = "jquants+edinet"
            n_deep += 1

        # 3) EDINET「主要な経営指標等の推移」5年史（COALESCE: 既存(J-Quants)を優先し欠損のみ補完）
        if erec and erec.summary:
            for fy, svals in erec.summary.items():
                r = rows.get(fy)
                if r is None:
                    r = _blank("edinet_summary", erec.period_end)
                    rows[fy] = r
                    n_summary += 1
                for f, v in svals.items():
                    if r.get(f) is None:
                        r[f] = v

        for fy, r in sorted(rows.items()):
            values = [code, fy, *[r.get(c) for c in value_cols],
                      r["_source"], "present", r["_as_of"], now]
            conn.execute(insert_sql, values)
            n_rows += 1
    conn.commit()
    return {
        "jq": jq.summary,
        "edinet": ed.summary,
        "snapshot_rows": n_rows,
        "rows_with_deep": n_deep,
        "rows_from_summary": n_summary,
        "accounting_standard_set": std_set,
    }
