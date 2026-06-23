"""financial_snapshots 構築: J-Quants（基礎財務）＋EDINET（深いBS）をマージ。

- 基礎財務(PL/BS/CF/株数)=J-Quants /fins/summary（年次FY確報・約2年窓）
- 深いBS(capex/投資有価証券/有利子負債/支払利息/利益剰余金/流動資産/負債合計)=EDINET最新有報
- accounting_standard は EDINET DEI（権威）優先・無ければ J-Quants DocType を stocks に記録
- 値が取れなければ NULL（捏造しない）。5状態statusは導出層で accounting_standard と
  ラベル辞書から再構成する（financial_snapshots は生値保持・D3）。
"""
from __future__ import annotations

from datetime import datetime

from .base import FetchPolicy, RateLimitedFetcher
from .edinet import DEEP_FIELDS, EdinetFetcher
from .jquants import FinancialsFetcher


def _load_code_meta(conn, codes: list[str]) -> dict[str, dict]:
    qs = ",".join("?" * len(codes))
    rows = conn.execute(
        f"SELECT code, edinet_code, fiscal_period_end_month FROM stocks WHERE code IN ({qs})",
        codes,
    ).fetchall()
    return {r[0]: {"edinet_code": r[1], "month": r[2]} for r in rows}


class _FinancialsBuilder(RateLimitedFetcher[dict]):
    """1銘柄＝J-Quants＋EDINET取得→マージ→financial_snapshots書込→commit を fetch_one で完結。

    **resume安全性の要**: 旧実装は両ソースを全件 .run() してから末尾でまとめて書いていた。
    途中で落ちて resume すると取得済み銘柄は checkpoint で skip され、in-memory 結果が
    無いため financial_snapshots に**行が永久に書かれず・再取得もされない silent gap** が
    生じた（定款のsilent-drop禁止に違反）。本実装は fetch_one 内で書込・commit まで終える
    ので、base.run() が **commit 後にのみ checkpoint を刻む** ＝ いつ落ちても「書けた銘柄
    だけが done」で resume が正しく続く。EDINET の一過性失敗(EdinetScanError)は backoff
    リトライ、連続失敗はサーキットブレーカーで中断（すべて base 由来）。
    """

    name = "financials_build"
    # EDINET の日次スキャンが律速。保守レートで（EdinetFetcher と同等）。
    policy = FetchPolicy(batch_size=20, sleep_between_batches=3.0, sleep_between_items=0.3,
                         max_retries=4)

    def __init__(self, conn, c2e, c2m, now, insert_sql, base_cols, deep_cols, value_cols):
        self.conn = conn
        self.now = now
        self.insert_sql = insert_sql
        self.base_cols = base_cols
        self.deep_cols = deep_cols
        self.value_cols = value_cols
        self.jqf = FinancialsFetcher()
        self.edf = EdinetFetcher(c2e, c2m)
        self.n_rows = self.n_deep = self.n_summary = self.std_set = 0
        self.jq_ok = self.ed_ok = 0

    def is_rate_limit(self, exc: Exception) -> bool:
        # 両ソースのレート判定を統合（EdinetScanError含む）。尽きれば failed＝done を刻まない。
        return self.jqf.is_rate_limit(exc) or self.edf.is_rate_limit(exc)

    def fetch_one(self, code: str) -> dict:
        # 1) 両ソース取得（rate-limit/scan失敗は _fetch_with_retry が backoff リトライ）。
        #    どちらかが例外なら fetch_one 全体が失敗扱い＝書込前に抜け、checkpointされない。
        fy_list = self.jqf.fetch_one(code)        # list[FinFY]（空＝当該銘柄J-Quants無し）
        erec = self.edf.fetch_one(code)           # EdinetRecord

        # 2) 取得成功後にのみDBへ。ここで例外が出たら rollback して再送出（部分行を残さない）。
        try:
            deep_fy = erec.fiscal_year if erec else None
            std = (erec.accounting_standard if erec else None)
            if not std and fy_list:
                std = next((f.accounting_standard for f in reversed(fy_list)
                            if f.accounting_standard), None)
            if std:
                self.conn.execute(
                    "UPDATE stocks SET accounting_standard=?, updated_at=? WHERE code=?",
                    (std, self.now, code))
                self.std_set += 1

            rows: dict[int, dict] = {}

            def _blank(src: str, as_of, disclosed=None) -> dict:
                r = {c: None for c in self.value_cols}
                r["_source"], r["_as_of"], r["_disclosed"] = src, as_of, disclosed
                return r

            # J-Quants 基礎財務（年次・確報）
            for fin in fy_list:
                r = _blank("jquants", fin.period_end, fin.disclosed_date)
                for c in self.base_cols:
                    r[c] = fin.base.get(c)
                rows[fin.fiscal_year] = r

            # EDINET 深いBS（最新有報年度のみ。J-Quants行があればマージ）
            if erec and deep_fy:
                r = rows.get(deep_fy)
                if r is None:
                    r = _blank("edinet", erec.period_end)
                    rows[deep_fy] = r
                for f in self.deep_cols:
                    r[f] = erec.values.get(f)
                if r["_source"] == "jquants":
                    r["_source"] = "jquants+edinet"
                self.n_deep += 1

            # EDINET「主要な経営指標等の推移」5年史（COALESCE: 既存J-Quantsを優先し欠損のみ補完）
            if erec and erec.summary:
                for fy, svals in erec.summary.items():
                    r = rows.get(fy)
                    if r is None:
                        r = _blank("edinet_summary", erec.period_end)
                        rows[fy] = r
                        self.n_summary += 1
                    for f, v in svals.items():
                        if r.get(f) is None:
                            r[f] = v

            for fy, r in sorted(rows.items()):
                values = [code, fy, *[r.get(c) for c in self.value_cols],
                          r["_source"], "present", r["_as_of"], r.get("_disclosed"), self.now]
                self.conn.execute(self.insert_sql, values)
                self.n_rows += 1
            self.conn.commit()        # ← ここまで終えてから base.run が checkpoint を刻む
        except Exception:
            self.conn.rollback()      # 部分書込を次銘柄の commit に混ぜない
            raise

        if fy_list:
            self.jq_ok += 1
        if erec and erec.doc_id:
            self.ed_ok += 1
        return {"code": code, "rows": len(rows), "has_deep": bool(erec and deep_fy)}


def build_financials(conn, codes: list[str], *, resume: bool = True) -> dict:
    """financial_snapshots を resume 安全に構築（per-stock 書込→commit→checkpoint）。"""
    now = datetime.now().isoformat(timespec="seconds")
    meta = _load_code_meta(conn, codes)
    c2e = {c: meta[c]["edinet_code"] for c in codes if meta.get(c, {}).get("edinet_code")}
    c2m = {c: meta[c]["month"] for c in codes}

    from .jquants import JQ_BASE_MAP

    base_cols = list(JQ_BASE_MAP.keys())
    deep_cols = list(DEEP_FIELDS)
    value_cols = base_cols + deep_cols
    all_cols = ["code", "fiscal_year", *value_cols, "source", "confidence", "as_of",
                "disclosed_date", "collected_at"]
    placeholders = ",".join("?" * len(all_cols))
    set_clause = ",".join(
        f"{c}=excluded.{c}" for c in (*value_cols, "source", "confidence", "as_of",
                                      "disclosed_date", "collected_at")
    )
    insert_sql = (
        f"INSERT INTO financial_snapshots ({','.join(all_cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(code, fiscal_year) DO UPDATE SET {set_clause}"
    )

    builder = _FinancialsBuilder(conn, c2e, c2m, now, insert_sql, base_cols, deep_cols, value_cols)
    res = builder.run(codes, resume=resume)
    return {
        "jq": f"ok={builder.jq_ok}",
        "edinet": f"ok={builder.ed_ok}",
        "snapshot_rows": builder.n_rows,
        "rows_with_deep": builder.n_deep,
        "rows_from_summary": builder.n_summary,
        "accounting_standard_set": builder.std_set,
        "failed": len(res.failed),
        "fetch_summary": res.summary,
    }
