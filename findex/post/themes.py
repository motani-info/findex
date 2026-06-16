"""投稿テーマの生成（D5 §2-§3）。テンプレ × データクエリ × 品質ゲート。

MVP（Phase6 段階1）は看板の手前、確実に出せる「連続増配ランキング」1テーマ。
- 本文＝フック（≤140字・CJK加重2）。数字は本文に詰めず画像へ。
- 画像＝ランキング表（report.py と同じ品質ゲートを通った値だけ）。
- 出力は draft（claim・通過ゲートを添えて返す）。投稿可否は CLI 側で判断。

鉄則（定款）: status=ok のclaimだけ。打ち切りは「N年以上」。出典明示。免責必須。
"""
from __future__ import annotations

from datetime import date

from .report import (
    _CSS, _QUALITY_JP, _grade_chip, _pct, _streak_cell, fetch_rows,
)


def weighted_len(s: str) -> int:
    """Xの加重文字数（多くのCJK文字は2、ラテン等は1）。URLは別途23字固定だが本文では概算。"""
    n = 0
    for ch in s:
        n += 2 if ord(ch) > 0x1100 and not ch.isascii() else 1
    return n


# 画像カードは固定ダークテーマ（スクショは prefers-color-scheme を当てにできない）
_CARD_CSS = _CSS + """
body{background:transparent;padding:0}
.card{max-width:960px;margin:0;background:var(--panel);border:1px solid var(--line);
border-radius:16px;padding:26px 30px 22px;box-shadow:0 8px 30px rgba(0,0,0,.25)}
.card h1{font-size:23px;margin:0 0 2px}
.brand{font-size:12px;font-weight:800;letter-spacing:.14em;color:var(--accent2);text-transform:uppercase}
.cap{color:var(--muted);font-size:12px;margin:.2em 0 1em}
.card table{margin:0}
.foot{margin-top:12px;font-size:11px;color:var(--muted);line-height:1.5}
"""


def _streak_body(n: int) -> str:
    """フック本文（≤140字・CJK加重2）。看板テーゼ「増配率でなく続く配当」を1行で。"""
    return (
        f'「増配率」ではなく"続く配当"。\n'
        f"連続増配・非減配ランキング トップ{n}📈\n"
        "数字は全て検証済み（status=ok）。\n"
        "#日本株 #増配株 #高配当"
    )


def _ranking_card_html(rows: list[dict], top_n: int, has_override: bool) -> str:
    today = date.today().isoformat()
    body = []
    for i, r in enumerate(rows[:top_n], 1):
        q = _QUALITY_JP.get(r["quality"], "—") if r["quality"] else "—"
        rel = f'{r["rel"]:.1f}' if r["rel"] is not None else '<span class="muted">—</span>'
        body.append(
            f'<tr><td>{i}</td><td class="l">{r["code"]}</td><td class="l">{r["name"]}</td>'
            f'<td>{_streak_cell(r["g_years"], r["censored"], r["g_src"])}</td>'
            f'<td>{_streak_cell(r["nc_years"], r["censored"], r["nc_src"])}</td>'
            f'<td>{rel}</td><td>{q}</td><td>{_pct(r["yoc"])}</td>'
            f'<td>{_grade_chip(r["gd"])}</td></tr>'
        )
    src_note = ' <span class="src">ZAi公表</span>=ダイヤモンドZAi集計の公表値。' if has_override else ""
    return f"""<!doctype html><meta charset="utf-8"><style>{_CARD_CSS}</style>
<div class="card">
<div class="brand">findex</div>
<h1>連続増配・連続非減配ランキング</h1>
<div class="cap">検証済みデータ（status=ok）／打ち切りは「N年以上」と正直表示／生成 {today}</div>
<table><thead><tr>
<th>#</th><th class="l">コード</th><th class="l">銘柄</th><th>連続増配</th><th>連続非減配</th>
<th>減配信頼性</th><th>増配の質</th><th>YoC(5年)</th><th>配当grade</th>
</tr></thead><tbody>
{chr(10).join(body)}
</tbody></table>
<div class="foot">減配信頼性 1.0=過去20年無減配／増配の質 EPS牽引=健全・性向拡大・一過性。{src_note}
　情報提供であり投資助言ではありません。数値はfindexデータベース由来（status=okのみ）。</div>
</div>"""


def build_streak_ranking(conn, codes: list[str], top_n: int = 10) -> dict:
    """連続増配ランキング投稿（本文＋画像HTML＋claim＋ゲート）を組み立てる。"""
    rows = fetch_rows(conn, codes)
    # ゲート: 配当claimがある(grade≠D)かつ連続増配年数が算出済みの銘柄のみ
    elig = [r for r in rows if r["gd"] != "D" and r["g_years"] is not None]
    elig.sort(key=lambda r: (r["g_years"] or -1, r["nc_years"] or -1), reverse=True)
    has_override = any(r["g_src"] == "override" or r["nc_src"] == "override" for r in elig[:top_n])

    n = min(top_n, len(elig))
    body = _streak_body(n)

    claims = [
        {
            "code": r["code"], "name": r["name"],
            "consecutive_dividend_growth_years": r["g_years"],
            "consecutive_no_cut_years": r["nc_years"],
            "censored": r["censored"],
            "source": r["g_src"] or "computed",
            "grade_dividend": r["gd"],
        }
        for r in elig[:top_n]
    ]

    gates = {
        "status_ok_only": True,           # fetch_rows がstatus=okのみ値を持たせる
        "censored_as_n_plus": True,       # 打ち切りは「N年以上」表示
        "source_cited": has_override,     # override由来は出典バッジ
        "grade_shown": True,              # claim別グレード併示
        "eligible_count": n,
        "body_weighted_len": weighted_len(body),
        "body_within_limit": weighted_len(body) <= 140,
        "passed": n > 0 and weighted_len(body) <= 140,
    }

    return {
        "theme": "streak",
        "body": body,
        "image_html": _ranking_card_html(elig, top_n, has_override),
        "claims": claims,
        "gates": gates,
    }


# テーマ名 → ビルダー
THEMES = {
    "streak": build_streak_ranking,
}
