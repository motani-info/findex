"""投稿テーマの生成（D5 §2-§3）。テンプレ × データクエリ × 品質ゲート。

MVP（Phase6 段階1）は看板の手前、確実に出せる「連続増配ランキング」1テーマ。
- 本文＝フック（≤140字・CJK加重2）。数字は本文に詰めず画像へ。
- 画像＝ランキング表（report.py と同じ品質ゲートを通った値だけ）。
- 出力は draft（claim・通過ゲートを添えて返す）。投稿可否は CLI 側で判断。

鉄則（定款）: status=ok のclaimだけ。打ち切りは「N年以上」。出典明示。免責必須。
"""
from __future__ import annotations

from datetime import date

from ..score.engine import _QUALITY_FACTOR
from .report import (
    _CSS, _QUALITY_JP, _grade_chip, _pct, _streak_cell, fetch_rows,
)


def weighted_len(s: str) -> int:
    """Xの加重文字数（多くのCJK文字は2、ラテン等は1）。URLは別途23字固定だが本文では概算。"""
    n = 0
    for ch in s:
        n += 2 if ord(ch) > 0x1100 and not ch.isascii() else 1
    return n


# 薄データ閾値（doc 09 §2-4）: 採点指標数 n_scored がこれ未満の銘柄は動的分母が薄く、
# 少数の幸運な指標で順位が上振れする（report.py も警告）。全3,710社の n_scored 分布の
# 左裾（1-7=425社/11.5%）を除外。golden18社は全て n_scored≥11 で不変・配当claim銘柄への
# 巻き込みも13社のみ（実測）。全銘柄スケールでの順位信頼性ゲート。
MIN_N_SCORED = 8


def _sufficient(r: dict) -> bool:
    """薄データ銘柄を除外（順位信頼性ゲート）。n_scored が閾値未満なら全テーマで対象外。"""
    ns = r.get("n_scored")
    return ns is not None and ns >= MIN_N_SCORED


# 配当利回りフロア（doc 09 §5・2026-06-17 ユーザー判断）: テーマの看板に応じた段階的フロア。
# 「高配当/増配を謳うテーマに低・無配当が上位に来る」FBへの是正。バリュー/資本効率テーマ
# （value_quality/net_cash/roic_spread）は利回りが主旨でないため適用しない。
YIELD_FLOOR_HIGH = 0.03      # 高配当系（"高配当"の名に値する水準）
YIELD_FLOOR_DIV = 0.02       # 増配・配当系（無配・ほぼ無配の見かけ倒しを排除）
YIELD_FLOOR_STREAK = 0.015   # 連続/質系（増配アリストクラットを残す＝花王2.5%/小林1.9%は通過）

# high_yield_safe の安全フィルタ（doc 10・P1-2・2026-06-17 FB是正）: 看板「減配しにくい高配当」
# に反する罠（高利回り×減配常習×配当性向>100%）を除外。GeminiFBのバリューコマース
# （減配信頼性0.0/配当性向217%）が利回り降順で上位に来た問題への是正。derive層の status は
# 既に確証を保証するが、テーマ層が「安全性」を実フィルタしていなかった（D4.5較正の思想が未波及）。
HY_SAFE_MIN_REL = 0.6        # 減配信頼性（過去20年の減配1回以内＝1.0/0.6のみ。0.0=2回以上は除外）
HY_SAFE_MAX_PAYOUT = 1.0     # 配当性向の健全上限（利益で配当を賄えている＝100%以下）


def _hy_safe_eligible(r: dict) -> bool:
    """high_yield_safe の安全フィルタ（doc 10・P1-2）。高配当の中から「減配しにくい」だけを残す。

    利回りフロア＋配当gradeA/Bに加え、減配信頼性 rel>=0.6（減配1回以内）かつ配当性向が健全域
    （0<payout<=100%＝利益で配当を賄えている）。rel/payout 未算出は安全性を確証できず除外。
    """
    return (_yield_ok(r, YIELD_FLOOR_HIGH) and r["gd"] in ("A", "B")
            and r["rel"] is not None and r["rel"] >= HY_SAFE_MIN_REL
            and r["payout_ratio"] is not None and 0 < r["payout_ratio"] <= HY_SAFE_MAX_PAYOUT)


def _yield_ok(r: dict, floor: float) -> bool:
    """現配当利回りがフロア以上か。stale/suspect/missing（dy=None）は不通過＝低・無配を排除。"""
    dy = r.get("dy")
    return dy is not None and dy >= floor


# CF系テーマ（FCFカバ/ネットキャッシュ）から除外する金融業種（doc 10・P2-3・D4.5較正③の業種考慮）。
# 銀行・証券・保険・その他金融はFCF/ネットキャッシュの概念が事業構造上当てはまらず、CF系の
# ランキングを構造的に独占・歪曲する（GeminiFB: fcf_coverage が銀行独占）。配当/連続テーマには
# 引き続き登場する（除外はCF系の2テーマのみ）。
_FINANCIAL_SECTORS = frozenset({"銀行業", "証券、商品先物取引業", "保険業", "その他金融業"})


def _non_financial(r: dict) -> bool:
    """金融業種でないか（CF系テーマのフィルタ）。sector33 未取得(None)は除外しない＝従来挙動を維持。"""
    return r.get("sector33") not in _FINANCIAL_SECTORS


# 画像カードは固定ダークテーマ（スクショは prefers-color-scheme を当てにできない）
_CARD_CSS = _CSS + """
body{background:transparent;padding:0}
.card{max-width:960px;margin:0;background:var(--panel);border:1px solid var(--line);
border-radius:16px;padding:26px 30px 22px;box-shadow:0 8px 30px rgba(0,0,0,.25)}
.card h1{font-size:23px;margin:0 0 2px}
.brand{font-size:12px;font-weight:800;letter-spacing:.14em;color:var(--accent2);text-transform:uppercase}
.cap{color:var(--muted);font-size:12px;margin:.2em 0 1em}
.card table{margin:0}
.foot{margin-top:12px;font-size:11px;color:var(--muted);line-height:1.8}
/* 順位強調（1〜3位の銘柄名を金銀銅＋太字） */
.nm{font-weight:800}
.r1{color:#d4a017}.r2{color:#8b96a6}.r3{color:#c0763a}
/* 単位で10超の数値を強調 */
.hot{color:var(--accent2);font-weight:800;background:rgba(126,224,192,.12);
border-radius:5px;padding:1px 5px}
@media (prefers-color-scheme:light){.hot{background:rgba(15,157,119,.10)}}
"""


def _streak_body(n: int) -> str:
    """フック本文（≤140字・CJK加重2）。看板テーゼ「増配率でなく続く配当」を1行で。"""
    return (
        f'「増配率」ではなく"続く配当"。\n'
        f"連続増配・連続非減配ランキング📈 トップ{n}\n"
        "長く減らさず増やし続けた銘柄。\n"
        "#増配株 #高配当株"
    )


def _ranking_card_html(rows: list[dict], top_n: int, has_override: bool) -> str:
    today = date.today().isoformat()
    shown = rows[:top_n]
    body = []
    for i, r in enumerate(shown, 1):
        q = _q_jp(r["quality"])
        rel = f'{r["rel"]:.1f}' if r["rel"] is not None else '<span class="muted">—</span>'
        body.append(
            f'<tr>{_row_prefix(i, r)}'
            f'<td>{_streak_td(r, "g")}</td><td>{_streak_td(r, "nc")}</td>'
            f'<td>{rel}</td><td>{q}</td>'
            f'<td>{_hot(_pct(r["yoc"]), None if r["yoc"] is None else r["yoc"] * 100)}</td>'
            f'<td>{_grade_chip(r["gd"])}</td></tr>'
        )
    zai_note = _ZAI_FOOT if _has_override(shown) else ""
    return f"""<!doctype html><meta charset="utf-8"><style>{_CARD_CSS}</style>
<div class="card">
<div class="brand">findex</div>
<h1>連続増配・連続非減配ランキング</h1>
<div class="cap">打ち切りは「N年以上」と正直表示／作成日 {today}</div>
<table><thead><tr>
<th>#</th><th class="l">コード</th><th class="l">銘柄</th><th>配当利回り</th><th>連続増配</th><th>連続非減配</th>
<th>減配信頼性</th><th>増配の質</th><th>YoC(5年)</th><th>配当grade</th>
</tr></thead><tbody>
{chr(10).join(body)}
</tbody></table>
<div class="foot">減配信頼性: 過去の配当を減らさなかった度合い（1.0＝約20年減配なし）<br>
増配の質: 利益成長による増配＝健全／配当性向を上げた増配＝性向拡大<br>
YoC(5年): 5年前に買っていた場合の実質利回り（増配による利回り向上）<br>
{zai_note}情報提供であり投資助言ではありません。数値はFindex調べ。</div>
</div>"""


def build_streak_ranking(conn, codes: list[str], top_n: int = 10) -> dict:
    """連続増配ランキング投稿（本文＋画像HTML＋claim＋ゲート）を組み立てる。"""
    rows = fetch_rows(conn, codes)
    # ゲート: 配当claimがある(grade≠D)かつ連続増配年数が算出済みの銘柄のみ
    elig = [r for r in rows if _sufficient(r) and _yield_ok(r, YIELD_FLOOR_STREAK)
            and r["gd"] != "D" and r["g_years"] is not None]
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


def _num(v, suffix="", digits=1):
    return f"{v:.{digits}f}{suffix}" if v is not None else '<span class="muted">—</span>'


def _q_jp(quality):
    return _QUALITY_JP.get(quality, '<span class="muted">—</span>') if quality else '<span class="muted">—</span>'


_FOOT = ('情報提供であり投資助言ではありません。数値はFindex調べ。'
         '「—」は未算出項目、「N年以上」はデータ取得範囲の上限。')

# ZAi公表値を採用した連続増配年数がある場合の出典脚注（セル内バッジは置かず脚注で一括明示）
_ZAI_FOOT = '※連続増配年数の一部はダイヤモンドZAi公表値を採用。'

_MEDAL = {1: "🥇", 2: "🥈", 3: "🥉"}


def _has_override(rows: list[dict]) -> bool:
    return any(r.get("g_src") == "override" or r.get("nc_src") == "override" for r in rows)


def _hot(rendered: str, v, thr: float = 10.0) -> str:
    """単位で thr を超える数値を強調（v は表示単位での実数。利回り%・倍率・年数）。"""
    return f'<span class="hot">{rendered}</span>' if v is not None and v > thr else rendered


def _name_td(i: int, name: str) -> str:
    """順位別に銘柄名を強調（1〜3位は金銀銅＋太字色）。"""
    return f'<td class="l nm r{i}">{_MEDAL[i]} {name}</td>' if i in _MEDAL else f'<td class="l">{name}</td>'


def _dy_td(r: dict) -> str:
    """全テーマ共通の配当利回り列（銘柄の直後）。10%超は強調。"""
    dy = r.get("dy")
    return f'<td>{_hot(_pct(dy), None if dy is None else dy * 100)}</td>'


def _streak_td(r: dict, which: str) -> str:
    """連続年数セル（ZAi出典バッジは置かず脚注で一括明示）。確定値が10年超なら強調。"""
    yrs = r["g_years"] if which == "g" else r["nc_years"]
    cell = _streak_cell(yrs, r["censored"], None)
    return _hot(cell, yrs) if (yrs is not None and not r["censored"]) else cell


def _row_prefix(i: int, r: dict) -> str:
    """全テーマ共通の行頭: 順位 / コード / 銘柄(順位強調) / 配当利回り。"""
    return f'<td>{i}</td><td class="l">{r["code"]}</td>{_name_td(i, r["name"])}{_dy_td(r)}'


def _rank_card(title: str, subtitle: str, head_cells: list[str], body_rows: list[str],
               foot_extra: str = "") -> str:
    """汎用ランキングカード（ダークテーマ・画像化用）。head_cells と body_rows<tr> を流し込む。"""
    today = date.today().isoformat()
    ths = "".join(
        f'<th class="l">{h[1:]}</th>' if h.startswith("@") else f"<th>{h}</th>"
        for h in head_cells
    )
    return f"""<!doctype html><meta charset="utf-8"><style>{_CARD_CSS}</style>
<div class="card">
<div class="brand">findex</div>
<h1>{title}</h1>
<div class="cap">{subtitle}／作成日 {today}</div>
<table><thead><tr>{ths}</tr></thead><tbody>
{chr(10).join(body_rows)}
</tbody></table>
<div class="foot">{foot_extra + '<br>' if foot_extra else ''}{_FOOT}</div>
</div>"""


def _gates(body: str, n: int, **extra) -> dict:
    wl = weighted_len(body)
    return {
        "status_ok_only": True, "censored_as_n_plus": True, "grade_shown": True,
        "eligible_count": n, "body_weighted_len": wl, "body_within_limit": wl <= 140,
        "passed": n > 0 and wl <= 140, **extra,
    }


def build_high_yield_safe(conn, codes: list[str], top_n: int = 10) -> dict:
    """高配当×安全: 利回り高 かつ 配当gradeA/B かつ 減配信頼性が算出済み（罠高配当を除く）。"""
    rows = fetch_rows(conn, codes)
    # 安全フィルタ（doc 10・P1-2）: 減配信頼性 rel>=0.6（減配1回以内）かつ 配当性向が健全域
    # （利益で賄える＝0<payout<=100%）。看板「減配しにくい」に反する罠（高利回り×減配常習×
    # 配当性向>100%）を排除。rel/payout が未算出（None）の銘柄も安全性を確証できず除外。
    elig = [r for r in rows if _sufficient(r) and _hy_safe_eligible(r)]
    elig.sort(key=lambda r: r["dy"], reverse=True)
    n = min(top_n, len(elig))
    body = ('"高利回り=危険"とは限らない。\n'
            f"減配しにくい高配当ランキング💰 トップ{n}\n"
            "利回り×継続性×財務の質で選別。\n"
            "#高配当株 #配当")
    head = ["#", "@コード", "@銘柄", "配当利回り", "YoC(5年)", "減配信頼性", "配当性向", "連続非減配", "増配の質", "配当grade"]
    shown = elig[:top_n]
    trs = []
    for i, r in enumerate(shown, 1):
        trs.append(
            f'<tr>{_row_prefix(i, r)}'
            f'<td>{_hot(_pct(r["yoc"]), None if r["yoc"] is None else r["yoc"] * 100)}</td>'
            f'<td>{_num(r["rel"])}</td>'
            f'<td>{_pct(r["payout_ratio"])}</td><td>{_streak_td(r, "nc")}</td>'
            f'<td>{_q_jp(r["quality"])}</td><td>{_grade_chip(r["gd"])}</td></tr>'
        )
    claims = [{"code": r["code"], "name": r["name"], "div_yield": r["dy"],
               "dividend_reliability": r["rel"], "payout_ratio": r["payout_ratio"],
               "grade_dividend": r["gd"]} for r in shown]
    foot = ("減配信頼性: 過去の配当を減らさなかった度合い（1.0＝約20年減配なし）／"
            "配当性向100%以下＝利益で配当を賄えている<br>") + (_ZAI_FOOT if _has_override(shown) else "")
    return {"theme": "high_yield_safe", "body": body,
            "image_html": _rank_card("高配当×安全 ランキング", "減配信頼性1.0=過去20年無減配",
                                     head, trs, foot),
            "claims": claims, "gates": _gates(body, n)}


def _yoc_quality_key(r: dict) -> float:
    """div_growth のソートキー: YoC × 増配の質係数（採点層 _QUALITY_FACTOR と同一）。

    「高YoCだが一過性(cyclical×0.3)」を軟減点し、持続的な増配(sound×1.0)を上位に置く。
    質未算出(None)は採点層と同じく ×1.0（既定）。
    """
    return r["yoc"] * _QUALITY_FACTOR.get(r["quality"], 1.0)


def build_div_growth(conn, codes: list[str], top_n: int = 10) -> dict:
    """取得利回り（YoC・5年）上位。"育った利回り"＝5年前の株価に対する現在配当利回り。

    D4.5較正①（doc 10・P1-1）: 生の増配率CAGRは低基底・一過性復配で外れ値化する
    （イクヨ66倍・日本製鉄=減益下の増配）。YoC=年配当÷5年前株価を主軸に、採点層と同じ
    持続性ゲート（増配の質 sound×1.0/payout_driven×0.5/cyclical×0.3）をソートキーに掛け、
    「高YoCだが一過性」を軟減点する（score/engine.py の _QUALITY_FACTOR を共有＝単一実装）。
    生CAGR順位を廃止。
    """
    rows = fetch_rows(conn, codes)
    elig = [r for r in rows if _sufficient(r) and _yield_ok(r, YIELD_FLOOR_DIV) and r["yoc"] is not None and r["gd"] != "D"]
    # YoC × 質係数（採点層と同一）。一過性は ×0.3 まで減点され、よほど高YoCでない限り沈む。
    elig.sort(key=_yoc_quality_key, reverse=True)
    n = min(top_n, len(elig))
    body = ('"今の利回り"より、育った利回り。\n'
            f"取得利回り(YoC)ランキング📈 トップ{n}\n"
            "5年前に買えば利回りはこう育つ。\n"
            "#増配株 #高配当株")
    head = ["#", "@コード", "@銘柄", "配当利回り", "YoC(5年)", "増配率5年", "連続増配", "増配の質", "配当grade"]
    shown = elig[:top_n]
    trs = []
    for i, r in enumerate(shown, 1):
        trs.append(
            f'<tr>{_row_prefix(i, r)}'
            f'<td>{_hot(_pct(r["yoc"]), None if r["yoc"] is None else r["yoc"] * 100)}</td>'
            f'<td>{_hot(_pct(r["dpc5"]), None if r["dpc5"] is None else r["dpc5"] * 100)}</td>'
            f'<td>{_streak_td(r, "g")}</td>'
            f'<td>{_q_jp(r["quality"])}</td><td>{_grade_chip(r["gd"])}</td></tr>'
        )
    claims = [{"code": r["code"], "name": r["name"], "yield_on_cost_5y": r["yoc"],
               "grade_dividend": r["gd"]} for r in shown]
    foot = ("YoC(5年): 5年前の株価に対する現在配当利回り（増配で利回りが育った度合い）<br>"
            + (_ZAI_FOOT if _has_override(shown) else ""))
    return {"theme": "div_growth", "body": body,
            "image_html": _rank_card("取得利回り（YoC・5年）ランキング", "5年前に買っていたら利回りはこう育つ",
                                     head, trs, foot),
            "claims": claims, "gates": _gates(body, n)}


def build_value_quality(conn, codes: list[str], top_n: int = 10) -> dict:
    """割安×優良: PBR<1 かつ 財務gradeA/B かつ ROE算出済み。質を伴う割安。"""
    rows = fetch_rows(conn, codes)
    elig = [r for r in rows if _sufficient(r) and r["pbr"] is not None and r["pbr"] < 1
            and r["gh"] in ("A", "B") and r["roe"] is not None]
    elig.sort(key=lambda r: r["roe"], reverse=True)
    n = min(top_n, len(elig))
    body = ("PBR1倍割れ=万年割安、とは限らない。\n"
            f'"質を伴う割安"株ランキング🔍 トップ{n}\n'
            "ROEと財務健全性で選別。\n"
            "#割安株 #バリュー株")
    head = ["#", "@コード", "@銘柄", "配当利回り", "PBR", "PER", "ROE", "自己資本比率", "財務grade", "バリューgrade"]
    shown = elig[:top_n]
    trs = []
    for i, r in enumerate(shown, 1):
        trs.append(
            f'<tr>{_row_prefix(i, r)}'
            f'<td>{_hot(_num(r["pbr"], "倍", 2), r["pbr"])}</td><td>{_hot(_num(r["per"], "倍"), r["per"])}</td>'
            f'<td>{_hot(_pct(r["roe"]), None if r["roe"] is None else r["roe"] * 100)}</td>'
            f'<td>{_hot(_pct(r["equity_ratio"]), None if r["equity_ratio"] is None else r["equity_ratio"] * 100)}</td>'
            f'<td>{_grade_chip(r["gh"])}</td><td>{_grade_chip(r["gv"])}</td></tr>'
        )
    claims = [{"code": r["code"], "name": r["name"], "pbr": r["pbr"], "roe": r["roe"],
               "grade_health": r["gh"]} for r in shown]
    return {"theme": "value_quality", "body": body,
            "image_html": _rank_card("割安×優良（PBR1倍割れの質）ランキング", "PBR<1かつ財務健全",
                                     head, trs),
            "claims": claims, "gates": _gates(body, n)}


def build_net_cash(conn, codes: list[str], top_n: int = 10) -> dict:
    """ネットキャッシュ潤沢: 実質PER(ネットキャッシュ控除)が低い順。表面より割安。"""
    rows = fetch_rows(conn, codes)
    # ネットキャッシュPER=PER×(1−ネットキャッシュ/時価総額)。net_cash_per<per ⟺ ネットキャッシュ>0
    # ＝真に現金潤沢（純負債銘柄を「潤沢」と誤ラベルしない・定款の正確性）。
    elig = [r for r in rows if _sufficient(r) and _non_financial(r)
            and r["net_cash_per"] is not None and r["per"] is not None
            and r["per"] > 0 and r["net_cash_per"] < r["per"]]
    elig.sort(key=lambda r: r["net_cash_per"])  # 実質PERが低い順＝最も割安な現金潤沢株
    n = min(top_n, len(elig))
    body = ('現金を引くと"実質PER"はもっと安い。\n'
            f"ネットキャッシュ潤沢ランキング💴 トップ{n}\n"
            '表面より割安な"実質バリュー"。\n'
            "#割安株 #バリュー株")
    head = ["#", "@コード", "@銘柄", "配当利回り", "実質PER", "表面PER", "PBR", "自己資本比率", "財務grade"]
    shown = elig[:top_n]
    trs = []
    for i, r in enumerate(shown, 1):
        trs.append(
            f'<tr>{_row_prefix(i, r)}'
            f'<td>{_hot(_num(r["net_cash_per"], "倍"), r["net_cash_per"])}</td>'
            f'<td>{_hot(_num(r["per"], "倍"), r["per"])}</td>'
            f'<td>{_hot(_num(r["pbr"], "倍", 2), r["pbr"])}</td>'
            f'<td>{_hot(_pct(r["equity_ratio"]), None if r["equity_ratio"] is None else r["equity_ratio"] * 100)}</td>'
            f'<td>{_grade_chip(r["gh"])}</td></tr>'
        )
    claims = [{"code": r["code"], "name": r["name"], "net_cash_per": r["net_cash_per"],
               "per": r["per"], "grade_health": r["gh"]} for r in shown]
    return {"theme": "net_cash", "body": body,
            "image_html": _rank_card("ネットキャッシュ潤沢（実質PER）ランキング",
                                     "実質PER=現金控除後の割安度", head, trs,
                                     "実質PER=（時価総額−ネットキャッシュ）÷利益。"),
            "claims": claims, "gates": _gates(body, n)}


def _yen(v):
    if v is None:
        return '<span class="muted">—</span>'
    if v >= 1e12:
        return f"{v / 1e12:.2f}兆円"
    return f"{v / 1e8:.0f}億円"


# 列種別 → セル描画。r は fetch_rows の1行。
def _cell(r: dict, key: str, kind: str) -> str:
    if kind == "streak_g":
        return _streak_td(r, "g")
    if kind == "streak_nc":
        return _streak_td(r, "nc")
    v = r.get(key)
    if kind == "pct":
        return _hot(_pct(v), None if v is None else v * 100)
    if kind == "num":
        return _hot(_num(v), v)
    if kind == "x":
        return _hot(_num(v, "倍"), v)
    if kind == "x2":
        return _hot(_num(v, "倍", 2), v)
    if kind == "grade":
        return _grade_chip(v)
    if kind == "quality":
        return _q_jp(v)
    if kind == "yen":
        return _yen(v)
    if kind == "int":
        return _hot(str(int(v)), v) if v is not None else '<span class="muted">—</span>'
    return '<span class="muted">—</span>'


def _ranking_theme(conn, codes, top_n, *, theme, title, subtitle, body_fn, columns,
                   eligible, sort_key, reverse=True, claim_keys, foot_extra=""):
    """宣言的ランキングテーマの共通実装。columns=[(見出し, key, kind), ...]。

    先頭3列（#/コード/銘柄）は自動。eligible=行フィルタ, sort_key=並べ替えキー。
    fetch_rows が status ゲート済み（確証データのみ値を持つ）ので、ここは整形のみ。
    """
    rows = fetch_rows(conn, codes)
    elig = [r for r in rows if _sufficient(r) and eligible(r)]
    elig.sort(key=sort_key, reverse=reverse)
    n = min(top_n, len(elig))
    body = body_fn(n)
    shown = elig[:top_n]
    # 配当利回りは全テーマ共通で銘柄の直後（columns側の重複定義は除外）
    cols = [c for c in columns if c[1] != "dy"]
    head = ["#", "@コード", "@銘柄", "配当利回り", *[c[0] for c in cols]]
    trs = []
    for i, r in enumerate(shown, 1):
        cells = "".join(f"<td>{_cell(r, key, kind)}</td>" for _, key, kind in cols)
        trs.append(f'<tr>{_row_prefix(i, r)}{cells}</tr>')
    claims = [{"code": r["code"], "name": r["name"], **{k: r.get(k) for k in claim_keys}}
              for r in shown]
    has_streak_col = any(kind in ("streak_g", "streak_nc") for _, _, kind in cols)
    foot = foot_extra + (_ZAI_FOOT if has_streak_col and _has_override(shown) else "")
    return {"theme": theme, "body": body,
            "image_html": _rank_card(title, subtitle, head, trs, foot),
            "claims": claims, "gates": _gates(body, n)}


# ── 宣言的テーマ定義（label, builder） ───────────────────────────────
# 各 spec は _ranking_theme へ渡す kwargs。THEMES へ functools.partial で登録。
_SPECS: dict[str, dict] = {
    "no_cut": dict(
        title="連続非減配ランキング", subtitle="減配なしで配当を守り続けた年数",
        body_fn=lambda n: ('"増やす"より、まず"減らさない"。\n'
                           f"連続非減配ランキング🛡️ トップ{n}\n"
                           "不況でも配当を守った銘柄。\n#高配当株 #配当"),
        columns=[("連続非減配", "nc_years", "streak_nc"), ("連続増配", "g_years", "streak_g"),
                 ("減配信頼性", "rel", "num"), ("増配の質", "quality", "quality"),
                 ("配当grade", "gd", "grade")],
        eligible=lambda r: r["gd"] != "D" and r["nc_years"] is not None and _yield_ok(r, YIELD_FLOOR_STREAK),
        sort_key=lambda r: (r["nc_years"] or -1, r["g_years"] or -1),
        claim_keys=["nc_years", "gd"]),
    "long_growth": dict(
        title="長期増配の王様（10年以上）", subtitle="連続増配10年以上",
        body_fn=lambda n: ('一過性でなく、10年以上"続く"増配。\n'
                           f"長期増配の王様ランキング👑 トップ{n}\n"
                           "時間が証明した配当力。\n#増配株 #高配当株"),
        columns=[("連続増配", "g_years", "streak_g"), ("連続非減配", "nc_years", "streak_nc"),
                 ("増配率5年", "dpc5", "pct"), ("YoC(5年)", "yoc", "pct"),
                 ("配当grade", "gd", "grade")],
        eligible=lambda r: r["gd"] != "D" and (r["g_years"] or 0) >= 10 and _yield_ok(r, YIELD_FLOOR_STREAK),
        sort_key=lambda r: r["g_years"] or -1, claim_keys=["g_years", "gd"]),
    "growth_room": dict(
        title="増配余力（配当性向が低い）", subtitle="配当性向が低い＝増配の伸びしろ",
        body_fn=lambda n: ("配当性向が低い＝まだ増やせる。\n"
                           f"増配余力ランキング💪 トップ{n}\n"
                           "無理なく増配を続けられる株。\n#増配株 #高配当株"),
        columns=[("配当性向", "payout_ratio", "pct"), ("連続増配", "g_years", "streak_g"),
                 ("増配率5年", "dpc5", "pct"), ("FCFカバ", "fcf_payout_coverage", "x"),
                 ("配当grade", "gd", "grade")],
        # doc 10・P1-3: 低配当性向「だけ」では増配余力を担保できない（利益が薄い/赤字でも
        # 性向は低く出る）。稼ぐ現金で配当を賄えている裏付けとして fcf_payout_coverage>0 を要求。
        eligible=lambda r: r["gd"] in ("A", "B") and r["payout_ratio"] is not None
        and 0 < r["payout_ratio"] < 0.4 and r["g_years"] is not None
        and r["fcf_payout_coverage"] is not None and r["fcf_payout_coverage"] > 0
        and _yield_ok(r, YIELD_FLOOR_DIV),
        sort_key=lambda r: r["payout_ratio"], reverse=False, claim_keys=["payout_ratio", "gd"]),
    "fcf_coverage": dict(
        title="FCF配当カバレッジ", subtitle="稼ぐ現金で配当を何倍まかなえるか",
        body_fn=lambda n: ('配当は利益でなく"現金"で見る。\n'
                           f"FCF配当カバレッジ🔄 トップ{n}\n"
                           "稼ぐ現金で配当を何倍払えるか。\n#高配当株 #配当"),
        columns=[("FCFカバ", "fcf_payout_coverage", "x"), ("配当性向", "payout_ratio", "pct"),
                 ("連続増配", "g_years", "streak_g"), ("配当grade", "gd", "grade")],
        # doc 10・P2-3: 金融（銀行/証券/保険/その他金融）はFCFの概念が当てはまらずCF系を独占→除外。
        eligible=lambda r: r["gd"] != "D" and _non_financial(r)
        and r["fcf_payout_coverage"] is not None and _yield_ok(r, YIELD_FLOOR_DIV),
        sort_key=lambda r: r["fcf_payout_coverage"] or -1, claim_keys=["fcf_payout_coverage", "gd"]),
    "high_roe_growth": dict(
        title="高ROE×増配", subtitle="稼ぐ力と増配の両立",
        body_fn=lambda n: ('配当だけでなく"稼ぐ力"も。\n'
                           f"高ROE×増配ランキング💹 トップ{n}\n"
                           "ROEと増配を両立する優良株。\n#増配株 #ROE"),
        columns=[("ROE", "roe", "pct"), ("連続増配", "g_years", "streak_g"),
                 ("営業益率", "operating_margin", "pct"), ("財務grade", "gh", "grade"),
                 ("配当grade", "gd", "grade")],
        eligible=lambda r: r["gd"] != "D" and r["roe"] is not None and r["g_years"] is not None and _yield_ok(r, YIELD_FLOOR_STREAK),
        sort_key=lambda r: r["roe"] or -1, claim_keys=["roe", "gd"]),
    "total_score": dict(
        title="findex 配当総合スコア", subtitle="配当/バリュー/財務/資本の総合評価(v4)",
        body_fn=lambda n: ("配当・割安・財務・資本を総合評価。\n"
                           f"findex総合スコアランキング📊 トップ{n}\n"
                           "多角指標で選ぶ配当株。\n#高配当株 #配当"),
        columns=[("総合", "total", "num"), ("配当", "gd", "grade"), ("バリュー", "gv", "grade"),
                 ("財務", "gh", "grade"), ("資本", "gc", "grade"), ("指標数", "n_scored", "int")],
        eligible=lambda r: r["total"] is not None and _yield_ok(r, YIELD_FLOOR_DIV),
        sort_key=lambda r: r["total"] or -1, claim_keys=["total", "gd"]),
    "high_yield": dict(
        title="高利回り（3.5%以上）", subtitle="配当利回り3.5%以上",
        body_fn=lambda n: ("まずは利回りで選ぶなら。\n"
                           f"高配当利回りランキング💰 トップ{n}\n"
                           "利回り3.5%以上＋継続性も併示。\n#高配当株 #配当"),
        columns=[("配当利回り", "dy", "pct"), ("配当性向", "payout_ratio", "pct"),
                 ("減配信頼性", "rel", "num"), ("連続非減配", "nc_years", "streak_nc"),
                 ("配当grade", "gd", "grade")],
        eligible=lambda r: r["dy"] is not None and r["dy"] >= 0.035,
        sort_key=lambda r: r["dy"] or -1, claim_keys=["dy", "gd"]),
    "low_pbr_yield": dict(
        title="割安高配当（PBR1倍以下）", subtitle="PBR1倍以下×高利回り",
        body_fn=lambda n: ('"資産より安い"高配当。\n'
                           f"割安高配当ランキング🔍 トップ{n}\n"
                           "PBR1倍以下で利回りも高い株。\n#割安株 #高配当株"),
        columns=[("PBR", "pbr", "x2"), ("配当利回り", "dy", "pct"), ("PER", "per", "x"),
                 ("財務grade", "gh", "grade"), ("配当grade", "gd", "grade")],
        eligible=lambda r: r["gd"] != "D" and r["pbr"] is not None and 0 < r["pbr"] <= 1
        and _yield_ok(r, YIELD_FLOOR_HIGH),
        sort_key=lambda r: r["dy"] or -1, claim_keys=["pbr", "dy", "gd"]),
    "large_cap": dict(
        title="大型優良配当（時価総額1兆円超）", subtitle="時価総額1兆円超×配当gradeA/B",
        body_fn=lambda n: ("大型で安定、それでも配当が育つ。\n"
                           f"大型優良配当ランキング🏢 トップ{n}\n"
                           "時価総額1兆円超の安定高配当。\n#高配当株 #大型株"),
        columns=[("時価総額", "current_market_cap", "yen"), ("配当利回り", "dy", "pct"),
                 ("連続増配", "g_years", "streak_g"), ("配当grade", "gd", "grade")],
        eligible=lambda r: r["gd"] in ("A", "B") and r["current_market_cap"] is not None
        and r["current_market_cap"] >= 1e12 and _yield_ok(r, YIELD_FLOOR_HIGH),
        sort_key=lambda r: r["current_market_cap"] or -1, claim_keys=["current_market_cap", "gd"]),
    "small_value": dict(
        title="小型割安配当（時価総額1000億円未満）", subtitle="小型×PBR1倍以下×配当",
        body_fn=lambda n: ("見落とされがちな小型の割安配当。\n"
                           f"小型割安配当ランキング💎 トップ{n}\n"
                           "時価総額1000億未満・PBR1倍以下。\n#割安株 #小型株"),
        columns=[("時価総額", "current_market_cap", "yen"), ("PBR", "pbr", "x2"),
                 ("配当利回り", "dy", "pct"), ("財務grade", "gh", "grade"),
                 ("配当grade", "gd", "grade")],
        eligible=lambda r: r["gd"] != "D" and r["current_market_cap"] is not None
        and r["current_market_cap"] < 1e11 and r["pbr"] is not None and 0 < r["pbr"] <= 1
        and _yield_ok(r, YIELD_FLOOR_HIGH),
        sort_key=lambda r: r["dy"] or -1, claim_keys=["current_market_cap", "pbr", "gd"]),
    "roic_spread": dict(
        title="価値創造（ROIC−WACC）", subtitle="資本コストを超えて稼ぐ企業",
        body_fn=lambda n: ("資本コストを超えて稼げているか。\n"
                           f"価値創造(ROIC−WACC)ランキング🚀 トップ{n}\n"
                           "本当の意味で儲かる会社。\n#ROIC #バリュー株"),
        columns=[("ROIC−WACC", "roic_minus_wacc", "pct"), ("ROE", "roe", "pct"),
                 ("営業益率", "operating_margin", "pct"), ("資本grade", "gc", "grade")],
        # doc 10・P2-2: ROIC−WACC>0 だけでは分母崩壊系（千代田化工=ROE算出不能）が混じる。
        # 財務健全性が確証できる（ROE算出済み）銘柄に限定。
        eligible=lambda r: r["roic_minus_wacc"] is not None and r["roic_minus_wacc"] > 0
        and r["roe"] is not None,
        sort_key=lambda r: r["roic_minus_wacc"] or -1, claim_keys=["roic_minus_wacc", "gc"]),
    "doe_king": dict(
        title="DOE（株主資本配当率）", subtitle="利益が薄くても株主資本に対し報いる力",
        body_fn=lambda n: ("利益が振れても、還元はブレない。\n"
                           f"DOE(株主資本配当率)ランキング💴 トップ{n}\n"
                           "安定還元の本命指標。\n#高配当株 #配当"),
        columns=[("DOE", "doe", "pct"), ("配当利回り", "dy", "pct"),
                 ("自己資本比率", "equity_ratio", "pct"), ("配当grade", "gd", "grade")],
        eligible=lambda r: r["gd"] != "D" and r["doe"] is not None and _yield_ok(r, YIELD_FLOOR_DIV),
        sort_key=lambda r: r["doe"] or -1, claim_keys=["doe", "gd"]),
}


def _make_theme(name: str):
    spec = _SPECS[name]
    return lambda conn, codes, top_n=10: _ranking_theme(conn, codes, top_n, theme=name, **spec)


# テーマ名 → ビルダー
THEMES = {
    "streak": build_streak_ranking,
    "high_yield_safe": build_high_yield_safe,
    "div_growth": build_div_growth,
    "value_quality": build_value_quality,
    "net_cash": build_net_cash,
    **{name: _make_theme(name) for name in _SPECS},
}


# ── 投稿ギャラリーHTML（全テーマを1ページで常時閲覧・本文コピー＋カード保存用）──────
_GALLERY_CSS = _CARD_CSS + """
body{background:var(--bg);padding:0}
.wrap{max-width:1040px;margin:0 auto;padding:34px 20px 90px}
.wrap h1{font-size:25px;margin:.1em 0 .1em}
.meta{color:var(--muted);font-size:13px;margin:.2em 0 8px}
.toc{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 8px}
.toc a{font-size:12px;color:var(--accent2);text-decoration:none;border:1px solid var(--line);
border-radius:999px;padding:3px 10px}
.toc a:hover{border-color:var(--accent);color:var(--accent)}
.theme{margin:34px 0 0;border-top:1px solid var(--line);padding-top:22px}
.theme-head{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
.theme-head .slug{font-family:ui-monospace,monospace;font-size:12px;color:var(--accent2);
background:var(--th);padding:3px 9px;border-radius:6px}
.copy{font-size:12px;cursor:pointer;border:1px solid var(--line);background:var(--panel);
color:var(--ink);border-radius:6px;padding:4px 11px}
.copy:hover{border-color:var(--accent)}
.copy.done{border-color:var(--accent2);color:var(--accent2)}
.dl{font-size:12px;cursor:pointer;border:1px solid var(--line);background:var(--panel);
color:var(--ink);border-radius:6px;padding:4px 11px}
.dl:hover{border-color:var(--accent)}
.dl.done{border-color:var(--accent2);color:var(--accent2)}
.hook{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:12px 14px;margin:0 0 14px;font-size:14px;line-height:1.85}
.hooklen{color:var(--muted);font-size:11px;margin-left:6px}
.cardwrap{overflow-x:auto}
"""

_GALLERY_JS = """
document.querySelectorAll('.copy').forEach(function(b){
  b.addEventListener('click', function(){
    navigator.clipboard.writeText(b.dataset.body).then(function(){
      b.classList.add('done'); var t=b.textContent; b.textContent='コピー済み ✓';
      setTimeout(function(){b.textContent=t; b.classList.remove('done');}, 1500);
    });
  });
});
document.querySelectorAll('.dl').forEach(function(b){
  b.addEventListener('click', function(){
    var sec = b.closest('.theme');
    var card = sec.querySelector('.cardwrap');
    b.textContent='生成中…';
    html2canvas(card, {scale:2, backgroundColor:'#1a1a2e'}).then(function(canvas){
      var a = document.createElement('a');
      a.download = b.dataset.theme + '.png';
      a.href = canvas.toDataURL('image/png');
      a.click();
      b.classList.add('done'); b.textContent='保存済み ✓';
      setTimeout(function(){b.textContent='画像を保存'; b.classList.remove('done');}, 2000);
    });
  });
});
"""


def _esc_attr(s: str) -> str:
    return (s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\n", "&#10;"))


def _card_only(image_html: str) -> str:
    """テーマの image_html（独立doc）から <div class="card">…</div> 本体だけ取り出す。"""
    i = image_html.find('<div class="card">')
    return image_html[i:] if i >= 0 else image_html


def build_gallery_html(conn, codes: list[str], *, scope_label: str = "") -> dict:
    """全テーマを1ページに並べた投稿ギャラリーHTMLを生成（本文コピー＋カード保存）。

    品質ゲート不通過のテーマは載せない（誤発信しない＝沈黙は許容）。
    """
    today = date.today().isoformat()
    sections, toc, shown = [], [], 0
    for name, fn in THEMES.items():
        post = fn(conn, codes, top_n=5)
        g = post["gates"]
        if not g["passed"]:
            continue
        shown += 1
        toc.append(f'<a href="#{name}">{name}</a>')
        sections.append(
            f'<section class="theme" id="{name}">'
            f'<div class="theme-head"><span class="slug">{name}</span>'
            f'<button class="copy" data-body="{_esc_attr(post["body"])}">本文をコピー</button>'
            f'<button class="dl" data-theme="{name}">画像を保存</button>'
            f'<span class="hooklen">{g["body_weighted_len"]}/140字・該当{g["eligible_count"]}社</span></div>'
            f'<div class="hook">{post["body"].replace(chr(10), "<br>")}</div>'
            f'<div class="cardwrap">{_card_only(post["image_html"])}</div>'
            f'</section>'
        )
    html = (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>findex 投稿テーマ一覧</title>'
        f'<style>{_GALLERY_CSS}</style>'
        '<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>'
        '</head><body><div class="wrap">'
        '<h1>findex 投稿テーマ一覧</h1>'
        f'<p class="meta">{scope_label}／作成日 {today}／{shown}テーマ。'
        '各テーマの「本文をコピー」→「画像を保存」で投稿。数値はFindex調べ。</p>'
        f'<nav class="toc">{"".join(toc)}</nav>'
        f'{"".join(sections)}'
        '</div><script>' + _GALLERY_JS + '</script></body></html>'
    )
    return {"html": html, "themes": shown}
