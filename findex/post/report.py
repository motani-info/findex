"""MVP出力: 検証済みデータから「閲覧可能なHTMLレポート」を生成（D5・ローカルHTML一級化）。

定款の鉄則を実装で守る:
  - **status=ok / zero_legit の数字だけ表示**（missing/insufficient は「—」。確証なき数字は出さない）
  - **連続年数の打ち切りは「N年以上」**（裸の数字で言い切らない＝花王36→16事故の再発防止）
  - **出典明示**（連続増配がZAi公表値override由来なら明記）
  - **claim別グレード併示**（配当A・財務Dを混同させない）
  - **免責必須**・数字は全てDB由来（手打ちしない）
本HTMLは投稿画像の母体であり、単独で閲覧可能な自前サイトも兼ねる（X障害時の受け皿）。
"""
from __future__ import annotations

import json
from datetime import date

from .. import config

_OK = ("ok", "zero_legit")

# docs/html と同系統のCSS（オフラインで開ける・外部CDN非依存）
_CSS = """
:root{--bg:#0f1115;--panel:#161922;--ink:#e6e8ee;--muted:#9aa3b2;--line:#272c38;
--accent:#6ea8fe;--accent2:#7ee0c0;--warn:#ffc24b;--th:#1d2230;--a:#7ee0c0;--b:#6ea8fe;--c:#ffc24b;--d:#8a93a3;}
@media (prefers-color-scheme:light){:root{--bg:#f7f8fa;--panel:#fff;--ink:#1b1f27;--muted:#5b6472;
--line:#e3e7ee;--accent:#2563eb;--accent2:#0f9d77;--warn:#9a6700;--th:#eef1f6;--a:#0f9d77;--b:#2563eb;--c:#9a6700;--d:#8a93a3;}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",Segoe UI,sans-serif;line-height:1.7;font-size:15px}
main{max-width:1040px;margin:0 auto;padding:40px 28px 80px}
.badge{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
color:var(--accent2);border:1px solid var(--line);border-radius:999px;padding:3px 10px;margin-bottom:12px}
h1{font-size:26px;margin:.1em 0 .3em}h2{font-size:19px;margin:1.8em 0 .5em;padding-bottom:.3em;border-bottom:1px solid var(--line)}
.sub{color:var(--muted);font-size:13px;margin-bottom:6px}
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:13px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:right;vertical-align:middle;white-space:nowrap}
th{background:var(--th);font-weight:700;text-align:center}
td.l,th.l{text-align:left}tr:nth-child(even) td{background:rgba(127,127,127,.05)}
.g{display:inline-block;width:20px;height:20px;line-height:20px;text-align:center;border-radius:5px;font-weight:700;font-size:12px;color:#0b0d12}
.gA{background:var(--a)}.gB{background:var(--b)}.gC{background:var(--c)}.gD{background:var(--d)}
.src{font-size:10.5px;color:var(--accent2);border:1px solid var(--line);border-radius:6px;padding:1px 5px;margin-left:5px}
.np{color:var(--warn);font-weight:700}.muted{color:var(--muted)}
.disclaimer{margin-top:32px;padding:14px 18px;border-left:3px solid var(--warn);
background:rgba(255,194,75,.08);border-radius:0 8px 8px 0;font-size:12.5px;color:var(--muted)}
.note{font-size:12px;color:var(--muted);margin:.4em 0 1.2em}
"""


def _val(metrics, status, field):
    """status が ok/zero_legit のときだけ値を返す。それ以外は None（表示は「—」）。"""
    return metrics.get(field) if status.get(field) in _OK else None


def _pct(v, digits=1):
    return f"{v * 100:.{digits}f}%" if v is not None else '<span class="muted">—</span>'


def _grade_chip(g):
    return f'<span class="g g{g}">{g}</span>' if g in ("A", "B", "C", "D") else '<span class="muted">—</span>'


def _streak_cell(years, censored, source):
    """連続年数セル: 打ち切りは『N年以上』・ZAi公表override由来は出典バッジ。"""
    if years is None:
        return '<span class="muted">—</span>'
    label = f'<span class="np">{years}年以上</span>' if censored else f"{years}年"
    if source == "override":
        label += '<span class="src">ZAi公表</span>'
    return label


_QUALITY_JP = {"sound": "EPS牽引", "payout_driven": "性向拡大", "cyclical": "一過性"}


def fetch_rows(conn, codes: list[str]) -> list[dict]:
    """検証済みデータから表示用の行dictを取得（品質ゲートの単一実装）。

    status=ok/zero_legit のフィールドだけ値を持たせ、それ以外は None（下流は「—」表示）。
    report.py と themes.py が同じゲートを共有するための共通入口。
    """
    # 銘柄名は stocks マスター（全3,734社）から引く。旧実装は load_cohort()(35社) からしか
    # 引いておらず、全銘柄ギャラリーで非コホート銘柄の name が空欄になる局所バグだった（doc 09 §1.A）。
    names = dict(conn.execute("SELECT code, name FROM stocks").fetchall())
    # sector33（33業種）: CF系テーマ（FCFカバ/ネットキャッシュ）の金融除外に使う（doc 10・P2-3）。
    sectors = dict(conn.execute("SELECT code, sector33 FROM stocks").fetchall())

    # status ゲートを通して露出する生値メトリクス（テーマ拡張の共通入口）
    _GATED = (
        "div_yield", "yield_on_cost_5y", "yield_on_cost_10y", "dividend_reliability",
        "dividend_multiple", "dividend_growth_5y_cagr", "dividend_growth_10y_cagr",
        "per", "pbr", "net_cash_per", "current_market_cap", "mix_coefficient",
        "roe", "equity_ratio", "operating_margin", "payout_ratio", "doe",
        "debt_to_equity", "eps_growth_5y", "revenue_growth_5y_cagr",
        "roic_minus_wacc", "fcf_payout_coverage", "retained_earnings_div_ratio", "annual_div",
    )
    _RAW = (
        "consecutive_dividend_growth_years", "consecutive_no_cut_years", "streak_is_censored",
        "dividend_quality", "dividend_cut_count_20y",
        "grade_dividend", "grade_valuation", "grade_health", "grade_capital",
    )
    sel_cols = ("source_json", "status_json", *_RAW, *_GATED)
    select_sql = f"SELECT {', '.join(sel_cols)} FROM computed_metrics WHERE code=?"

    rows = []
    for code in codes:
        m = conn.execute(select_sql, (code,)).fetchone()
        if not m:
            continue
        rec = dict(zip(sel_cols, m))
        src = json.loads(rec["source_json"]) if rec["source_json"] else {}
        status = json.loads(rec["status_json"]) if rec["status_json"] else {}
        # 採点（v4総合スコア・参考）
        sc = conn.execute(
            "SELECT total_score, score_json FROM dividend_scores WHERE code=? ORDER BY scored_at DESC LIMIT 1",
            (code,)
        ).fetchone()
        total = sc[0] if sc else None
        n_scored = json.loads(sc[1]).get("n_scored") if sc and sc[1] else None

        out = {
            "code": code, "name": names.get(code, ""), "sector33": sectors.get(code),
            "g_years": rec["consecutive_dividend_growth_years"],
            "nc_years": rec["consecutive_no_cut_years"],
            "censored": bool(rec["streak_is_censored"]),
            "g_src": src.get("consecutive_dividend_growth_years"),
            "nc_src": src.get("consecutive_no_cut_years"),
            "gd": rec["grade_dividend"], "gv": rec["grade_valuation"],
            "gh": rec["grade_health"], "gc": rec["grade_capital"],
            "quality": rec["dividend_quality"] if status.get("dividend_quality") in _OK else None,
            "dy_zero": status.get("div_yield") == "zero_legit",
            "cuts": rec["dividend_cut_count_20y"],
            "total": total, "n_scored": n_scored,
        }
        # status=ok/zero_legit のときだけ生値を載せる（確証なき数字は出さない）
        for f in _GATED:
            out[f] = _val(rec, status, f)
        # 既存テーマ互換の短い別名
        out["yoc"] = out["yield_on_cost_5y"]
        out["yoc10"] = out["yield_on_cost_10y"]
        out["dy"] = out["div_yield"]
        out["rel"] = out["dividend_reliability"]
        out["dpc5"] = out["dividend_growth_5y_cagr"]
        out["dpc10"] = out["dividend_growth_10y_cagr"]
        rows.append(out)
    return rows


def build_report(conn, codes: list[str]) -> str:
    """検証済みコホート/指定銘柄の配当レポートHTMLを生成。"""
    rows = fetch_rows(conn, codes)

    # 配当ランキング: 配当claimのある銘柄(grade_dividend != D)を連続増配年数で降順
    div_rows = [r for r in rows if r["gd"] != "D"]
    div_rows.sort(key=lambda r: (r["g_years"] or -1, r["nc_years"] or -1), reverse=True)
    score_rows = [r for r in rows if r["total"] is not None]
    score_rows.sort(key=lambda r: r["total"], reverse=True)

    today = date.today().isoformat()
    has_override = any(r["g_src"] == "override" or r["nc_src"] == "override" for r in div_rows)

    def div_tr(i, r):
        q = _QUALITY_JP.get(r["quality"], '<span class="muted">—</span>') if r["quality"] else '<span class="muted">—</span>'
        dy = "無配" if r["dy_zero"] else _pct(r["dy"], 2)
        rel = f'{r["rel"]:.1f}' if r["rel"] is not None else '<span class="muted">—</span>'
        return (
            f'<tr><td>{i}</td><td class="l">{r["code"]}</td><td class="l">{r["name"]}</td>'
            f'<td>{_streak_cell(r["g_years"], r["censored"], r["g_src"])}</td>'
            f'<td>{_streak_cell(r["nc_years"], r["censored"], r["nc_src"])}</td>'
            f'<td>{rel}</td><td>{q}</td><td>{_pct(r["yoc"])}</td><td>{dy}</td>'
            f'<td>{_grade_chip(r["gd"])}</td></tr>'
        )

    def score_tr(i, r):
        return (
            f'<tr><td>{i}</td><td class="l">{r["code"]}</td><td class="l">{r["name"]}</td>'
            f'<td><b>{r["total"]:.1f}</b></td>'
            f'<td>{_grade_chip(r["gd"])}</td><td>{_grade_chip(r["gv"])}</td>'
            f'<td>{_grade_chip(r["gh"])}</td><td>{_grade_chip(r["gc"])}</td>'
            f'<td>{r["n_scored"] if r["n_scored"] is not None else "—"}</td></tr>'
        )

    div_html = "\n".join(div_tr(i, r) for i, r in enumerate(div_rows, 1))
    score_html = "\n".join(score_tr(i, r) for i, r in enumerate(score_rows, 1))

    src_note = (
        '連続年数の <span class="src">ZAi公表</span> は ダイヤモンドZAi 集計の公表値（機械計算より長い場合のみ昇格採用）。'
        if has_override else ""
    )
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>findex 配当レポート（検証コホート）</title><style>{_CSS}</style></head>
<body><main>
<div class="badge">findex · MVP report</div>
<h1>高配当・増配株レポート（検証コホート {len(rows)}社）</h1>
<div class="sub">生成日 {today} ・ 数値は全てDB由来・status=ok のみ表示 ・ 確証のない値は「—」</div>

<h2>① 連続増配・非減配ランキング</h2>
<div class="note">配当claim（grade_dividend≠D）を連続増配年数で降順。打ち切り（取得データ下限）は<span class="np">N年以上</span>と正直表示。{src_note}</div>
<table><thead><tr>
<th>#</th><th class="l">コード</th><th class="l">銘柄</th><th>連続増配</th><th>連続非減配</th>
<th>減配信頼性</th><th>増配の質</th><th>YoC(5年)</th><th>配当利回り</th><th>配当grade</th>
</tr></thead><tbody>
{div_html}
</tbody></table>
<div class="note">減配信頼性 1.0=過去20年無減配 / 0.6=1回 / 0.0=2回以上。増配の質: EPS牽引(健全)・性向拡大・一過性。</div>

<h2>② v4総合スコア（参考・grade併示）</h2>
<div class="note">⚠ 総合スコアは<b>暫定</b>です。重み配分は手づけで、前方アウトカムによる検証（バックテスト）は未完。
動的分母のため<b>採点指標数が少ない銘柄はスコアが上振れ</b>します（薄いデータの歯止めは点数でなく<b>4つのグレード</b>）。
スコアとグレードは必ず併せて読んでください。</div>
<table><thead><tr>
<th>#</th><th class="l">コード</th><th class="l">銘柄</th><th>v4スコア</th>
<th>配当</th><th>バリュ</th><th>財務</th><th>資本</th><th>採点指標数</th>
</tr></thead><tbody>
{score_html}
</tbody></table>

<div class="disclaimer">
<b>免責</b>：本資料は公開データ（EDINET有価証券報告書・J-Quants・yfinance・ダイヤモンドZAi公表値）に基づく
情報提供であり、特定銘柄の売買を勧誘・推奨するものではなく、投資助言でもありません。投資判断はご自身の責任で行ってください。
数値は findex データベース由来で、確証（status=ok）のあるもののみ掲載しています。連続年数の「N年以上」は取得データの
時系列下限による打ち切り表示で、実際の連続年数はこれ以上です。グレードは claim（主張）単位で、配当が優良でも財務評価が
低い場合があります（混同しないでください）。
</div>
</main></body></html>"""


def write_report(conn, codes: list[str], out_path=None) -> dict:
    out = out_path or (config.PROJECT_ROOT / "docs" / "html" / "report.html")
    html = build_report(conn, codes)
    out.write_text(html, encoding="utf-8")
    return {"path": str(out), "stocks": len(codes), "bytes": len(html)}
