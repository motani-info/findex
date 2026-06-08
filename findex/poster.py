"""増配ラボ SNS投稿テキスト生成

21テーマ × 2投稿（フック + ランキング）構成。
3投稿/日 × 7日でローテーション。
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path.home() / ".findex" / "db" / "findex.db"

MEDALS = ["🥇", "🥈", "🥉"]
INVEST = 1_000_000  # シミュレーション基準額（円）
SAVINGS_RATE = 0.001  # 定期預金比較用金利（0.1%）


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_yield(v) -> str:
    return f"{v*100:.1f}%" if v else "-"

def _fmt_pct(v) -> str:
    return f"{v*100:+.1f}%" if v else "-"

def _fmt_score(v) -> str:
    return f"{v:.1f}点" if v else "-"

def _fmt_years(v) -> str:
    return f"{int(v)}年" if v else "-"

def _fmt_cagr(v) -> str:
    return f"{v*100:.1f}%" if v else "-"

def _fmt_man(yen: float) -> str:
    """円を万円表記に"""
    return f"{yen/10000:.1f}万円"

def _short_name(name: str, limit: int = 12) -> str:
    """フック投稿用：長い社名を短縮"""
    return name if len(name) <= limit else name[:limit] + "…"

def _base_where(extra: str = "") -> str:
    w = """
        ds.scored_at = (SELECT MAX(scored_at) FROM dividend_scores)
        AND cm.div_yield >= 0.025
    """
    if extra:
        w += f" AND {extra}"
    return w


# ── ヘルパー：シミュレーション計算 ──────────────────────────

def _price(conn, code: str) -> float | None:
    r = conn.execute(
        "SELECT close FROM price_history WHERE code=? ORDER BY date DESC LIMIT 1", (code,)
    ).fetchone()
    return r["close"] if r else None


def _hist_annual_div(conn, code: str, year: int) -> float | None:
    """指定年の年間配当合計（dividend_history から）"""
    r = conn.execute(
        "SELECT SUM(amount) as total FROM dividend_history WHERE code=? AND strftime('%Y', ex_date)=?",
        (code, str(year))
    ).fetchone()
    return r["total"] if r and r["total"] else None


def _sim(close: float, annual_div: float, cagr: float | None) -> dict:
    """100万円投資シミュレーション"""
    shares = int(INVEST / close)
    now = shares * annual_div
    c = cagr if (cagr and 0.01 <= cagr <= 0.20) else None
    future_5 = now * (1 + c) ** 5 if c else None
    future_10 = now * (1 + c) ** 10 if c else None
    return {"shares": shares, "now": now, "cagr": c, "y5": future_5, "y10": future_10}


def _future_year(n: int) -> int:
    return date.today().year + n

# CTAバリエーション（テーマごとに固定割り当て）
_CTA = {
    "a": "2位・3位は↓",
    "b": "続きはリプ欄",
    "c": "他の銘柄は↓",
}


# ══════════════════════════════════════════════════════
# テーマ関数（各テーマ → [フック投稿, ランキング投稿]）
# ══════════════════════════════════════════════════════

def theme_01(conn) -> list[str]:
    """🌱 連続増配ランキング"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, cm.consecutive_dividend_growth_years,
               cm.div_yield, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.consecutive_dividend_growth_years >= 1")}
        ORDER BY cm.consecutive_dividend_growth_years DESC, ds.total_score DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    n = int(top["consecutive_dividend_growth_years"])
    this_year = date.today().year
    past_year = this_year - n
    past_div = _hist_annual_div(conn, top["code"], past_year)
    now_div = top["annual_div"]

    # フック（「もし○年前に買っていたら」型）
    close = _price(conn, top["code"])
    sim_now = _sim(close, top["annual_div"], None) if close else None
    hook_lines = [f"{top['name']}を{n}年前に100万円買っていたら", ""]
    if past_div and now_div and sim_now:
        ratio = now_div / past_div
        past_income = sim_now["shares"] * past_div
        hook_lines += [
            f"配当金は年間 {past_income:,.0f}円 → {sim_now['now']:,.0f}円 になった",
            "",
            f"株価ではなく「配当」が {ratio:.1f}倍 になっている",
            "",
            f"リーマンも、コロナも、関係なかった",
        ]
    hook_lines += ["", _CTA["a"]]

    # ランキング
    rank_lines = ["🌱 何年も増配し続けている日本株3選", "連続増配1年以上 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   連続増配 {_fmt_years(r['consecutive_dividend_growth_years'])} / 利回り {_fmt_yield(r['div_yield'])}")
    rank_lines += ["", "#増配株 #連続増配 #高配当株 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_02(conn) -> list[str]:
    """📈 増配成長率ランキング（10年CAGR）"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, cm.dividend_growth_10y_cagr,
               cm.div_yield, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where(
            "cm.dividend_growth_10y_cagr IS NOT NULL "
            "AND cm.dividend_growth_10y_cagr BETWEEN 0.03 AND 0.20"
        )}
        ORDER BY cm.dividend_growth_10y_cagr DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    close = _price(conn, top["code"])
    sim = _sim(close, top["annual_div"], top["dividend_growth_10y_cagr"]) if close else None

    hook_lines = [f"{top['name']}を今100万円買うと", ""]
    if sim and sim["y10"]:
        hook_lines += [
            f"💰 今年の配当　{_fmt_man(sim['now'])}（利回り {_fmt_yield(top['div_yield'])}）",
            "",
            "過去10年と同じ増配率なら（理論上）",
            f"🔮 {_future_year(5)}年　約 {_fmt_man(sim['y5'])}",
            f"🔮 {_future_year(10)}年　約 {_fmt_man(sim['y10'])}",
            "",
            _CTA["b"],
        ]

    rank_lines = ["📈 10年で配当が急成長した銘柄3選", "10年CAGR 3〜20%帯 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   10年CAGR {_fmt_cagr(r['dividend_growth_10y_cagr'])} / 利回り {_fmt_yield(r['div_yield'])}")
    rank_lines += ["", "#増配 #配当成長 #高配当株 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_03(conn) -> list[str]:
    """🛡️ 連続非減配ランキング"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, cm.consecutive_no_cut_years,
               cm.div_yield, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.consecutive_no_cut_years >= 1")}
        ORDER BY cm.consecutive_no_cut_years DESC, ds.total_score DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    n = int(top["consecutive_no_cut_years"])
    past_year = date.today().year - n
    past_div = _hist_annual_div(conn, top["code"], past_year)
    now_div = top["annual_div"]

    events = "リーマンショック\n東日本大震災\nコロナショック"
    hook_lines = [
        events,
        "",
        f"それでも{n}年間、一度も配当を減らさなかった会社がある",
        "",
        f"{top['name']}",
    ]
    if past_div and now_div:
        ratio = now_div / past_div
        hook_lines += [
            "",
            f"配当は {past_year}年の {past_div:.0f}円 から",
            f"今年 {now_div:.0f}円 へ（{ratio:.1f}倍）",
        ]
    hook_lines += ["", _CTA["a"]]

    rank_lines = ["🛡️ リーマン・震災・コロナを乗り越えた株3選", "連続非減配1年以上 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   非減配 {_fmt_years(r['consecutive_no_cut_years'])} / 利回り {_fmt_yield(r['div_yield'])}")
    rank_lines += ["", "#非減配 #安定配当 #高配当株 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_04(conn) -> list[str]:
    """💎 増配継続 × 高利回り"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, cm.consecutive_dividend_growth_years,
               cm.div_yield, cm.annual_div, cm.dividend_growth_5y_cagr
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.consecutive_dividend_growth_years >= 5 AND cm.div_yield >= 0.03")}
        ORDER BY ds.total_score DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    close = _price(conn, top["code"])
    sim = _sim(close, top["annual_div"], top["dividend_growth_5y_cagr"]) if close else None

    hook_lines = [f"{top['name']}を100万円買うと", ""]
    if sim:
        hook_lines += [
            f"💰 今年の配当　{_fmt_man(sim['now'])}",
            f"　利回り {_fmt_yield(top['div_yield'])}",
            "",
            f"しかも{int(top['consecutive_dividend_growth_years'])}年連続で増配中",
        ]
        if sim["y10"]:
            hook_lines += [
                "",
                "過去と同じ増配率なら（理論上）",
                f"🔮 {_future_year(10)}年には約 {_fmt_man(sim['y10'])}",
            ]
    hook_lines += ["", _CTA["b"]]

    rank_lines = ["💎 増配中なのに高利回り、その両立銘柄3選", "連続増配5年以上 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   連続増配 {_fmt_years(r['consecutive_dividend_growth_years'])} / 利回り {_fmt_yield(r['div_yield'])}")
    rank_lines += ["", "#増配 #高配当 #配当投資 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_05(conn) -> list[str]:
    """💪 増配余力ランキング（配当性向）"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, cm.payout_ratio, cm.div_yield,
               cm.annual_div, cm.consecutive_dividend_growth_years
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.payout_ratio IS NOT NULL AND cm.payout_ratio BETWEEN 0.10 AND 0.45")}
        ORDER BY cm.payout_ratio ASC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    payout_pct = top["payout_ratio"] * 100
    room_pct = 100 - payout_pct

    close = _price(conn, top["code"])
    sim = _sim(close, top["annual_div"], None) if close else None
    hook_lines = [f"{top['name']}を100万円買うと", ""]
    if sim:
        hook_lines += [f"💰 今年の配当　{_fmt_man(sim['now'])}（利回り {_fmt_yield(top['div_yield'])}）", ""]
    hook_lines += [
        f"利益のうち配当に使っているのは {payout_pct:.0f}% だけ",
        "",
        "増配の余地がある隠れた銘柄",
        "",
        _CTA["c"],
    ]

    rank_lines = ["💪 まだまだ増配できる余力のある銘柄3選", "配当性向10〜45%帯 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   配当性向 {r['payout_ratio']*100:.0f}% / 利回り {_fmt_yield(r['div_yield'])}")
    rank_lines += ["", "#増配余力 #配当性向 #高配当株 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_06(conn) -> list[str]:
    """🔄 FCF配当カバレッジランキング"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, cm.fcf_payout_coverage,
               cm.div_yield, cm.payout_ratio, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.fcf_payout_coverage IS NOT NULL AND cm.fcf_payout_coverage > 0")}
        ORDER BY cm.fcf_payout_coverage DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    cov = top["fcf_payout_coverage"]
    otsurimono = cov - 1.0

    close = _price(conn, top["code"])
    sim = _sim(close, top["annual_div"], None) if close else None
    hook_lines = [f"{top['name']}を100万円買うと", ""]
    if sim:
        hook_lines += [f"💰 今年の配当　{_fmt_man(sim['now'])}（利回り {_fmt_yield(top['div_yield'])}）", ""]
    hook_lines += [
        "この会社、配当を払った後も",
        f"同じだけの現金が {cov:.0f}回分 手元に残る",
        "",
        "減配リスクが極めて低い",
        "",
        _CTA["c"],
    ]

    rank_lines = ["🔄 減配リスクが極めて低い安心配当株3選", "FCFカバレッジ（高い順）/ 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   FCFカバレッジ {r['fcf_payout_coverage']:.1f}倍 / 利回り {_fmt_yield(r['div_yield'])}")
    rank_lines += ["", "#FCF #キャッシュフロー #増配 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_07(conn) -> list[str]:
    """👑 長期増配の王様（10年以上）"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, cm.consecutive_dividend_growth_years,
               cm.div_yield, cm.annual_div, cm.dividend_growth_10y_cagr
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.consecutive_dividend_growth_years >= 10")}
        ORDER BY cm.consecutive_dividend_growth_years DESC
        LIMIT 3
    """).fetchall()
    if not rows:
        rows = conn.execute(f"""
            SELECT ds.code, st.name, cm.consecutive_dividend_growth_years,
                   cm.div_yield, cm.annual_div, cm.dividend_growth_10y_cagr
            FROM dividend_scores ds
            JOIN stocks st ON ds.code = st.code
            JOIN computed_metrics cm ON ds.code = cm.code
            WHERE {_base_where("cm.consecutive_dividend_growth_years >= 5")}
            ORDER BY cm.consecutive_dividend_growth_years DESC
            LIMIT 3
        """).fetchall()

    top = rows[0]
    close = _price(conn, top["code"])
    past_div_10y = _hist_annual_div(conn, top["code"], date.today().year - 10)
    now_div = top["annual_div"]
    sim = _sim(close, now_div, top["dividend_growth_10y_cagr"]) if close else None

    events = "リーマンショック\n東日本大震災\nコロナショック"
    n_years = int(top["consecutive_dividend_growth_years"])
    hook_lines = [
        events,
        "",
        f"それでも {n_years}年連続で増配し続けた企業がある",
        "",
        f"{top['name']}（{top['code']}）",
    ]
    if sim:
        hook_lines += [
            "",
            f"10年前に100万円買っていたら",
        ]
        if past_div_10y and now_div:
            past_income = sim["shares"] * past_div_10y
            hook_lines += [
                f"配当は年間 {past_income:,.0f}円 → {sim['now']:,.0f}円 に",
            ]
    if sim and sim["y10"]:
        hook_lines += [
            "",
            "過去と同じ増配率なら（理論上）",
            f"🔮 {_future_year(10)}年には約 {_fmt_man(sim['y10'])}",
        ]
    hook_lines += ["", _CTA["a"]]

    rank_lines = ["👑 10年以上増配し続けた会社は日本に数社しかない", "連続増配10年以上 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        cagr_s = f" / 10年CAGR {_fmt_cagr(r['dividend_growth_10y_cagr'])}" if r["dividend_growth_10y_cagr"] else ""
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   連続増配 {_fmt_years(r['consecutive_dividend_growth_years'])}{cagr_s}")
    rank_lines += ["", "#長期増配 #配当貴族 #高配当株 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_08(conn) -> list[str]:
    """🌟 増配 × モメンタム両取り"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, ds.total_score, ms.total_score AS mom_score,
               cm.consecutive_dividend_growth_years, cm.div_yield,
               cm.rel_ret_3m, cm.rel_ret_12m
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        JOIN momentum_scores ms ON ds.code = ms.code
          AND ms.scored_at = (SELECT MAX(scored_at) FROM momentum_scores)
        WHERE {_base_where("cm.consecutive_dividend_growth_years >= 3")}
        ORDER BY (ds.total_score + ms.total_score) DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]

    hook_lines = [
        f"{top['name']}",
        "",
        f"株価　直近3ヶ月 {_fmt_pct(top['rel_ret_3m'])} 上昇",
        f"配当　{int(top['consecutive_dividend_growth_years'])}年連続で増加中",
        "",
        "株価と配当が同時に上がっている銘柄",
        "どちらも取りたい人向けのランキング",
        "",
        _CTA["b"],
    ]

    rank_lines = ["🌟 株価も配当も同時に伸びている銘柄3選", "連続増配3年以上 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   配当スコア {_fmt_score(r['total_score'])} / モメンタム {_fmt_score(r['mom_score'])} / 3M {_fmt_pct(r['rel_ret_3m'])}")
    rank_lines += ["", "#増配 #モメンタム #成長株 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_09(conn) -> list[str]:
    """📊 配当スコア総合ランキング"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, ds.total_score,
               cm.div_yield, cm.consecutive_no_cut_years, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where()}
        ORDER BY ds.total_score DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]

    close = _price(conn, top["code"])
    sim = _sim(close, top["annual_div"], None) if close else None
    hook_lines = [
        "国内約4,000社をスクリーニングした",
        "",
        f"配当総合ランキング1位　{top['name']}",
    ]
    if sim:
        hook_lines += [
            "",
            f"💰 100万円で年間 {_fmt_man(sim['now'])}",
            f"　利回り {_fmt_yield(top['div_yield'])}",
            f"　{int(top['consecutive_no_cut_years'])}年間減配なし",
        ]
    hook_lines += ["", _CTA["a"]]

    rank_lines = ["📊 全上場企業から厳選した配当優良株3選", "12指標120点満点 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   スコア {_fmt_score(r['total_score'])} / 利回り {_fmt_yield(r['div_yield'])} / 非減配 {_fmt_years(r['consecutive_no_cut_years'])}")
    rank_lines += ["", "#高配当株 #配当投資 #日本株 #増配ラボ"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_10(conn) -> list[str]:
    """💰 高利回りランキング（3.5%以上）"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, cm.div_yield, cm.payout_ratio, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.div_yield BETWEEN 0.035 AND 0.12")}
        ORDER BY cm.div_yield DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    close = _price(conn, top["code"])
    sim = _sim(close, top["annual_div"], None) if close else None
    savings_income = INVEST * SAVINGS_RATE

    hook_lines = [f"{top['name']}を100万円買うと", ""]
    if sim:
        times = sim["now"] / savings_income
        hook_lines += [
            f"💰 年間配当　約 {_fmt_man(sim['now'])}",
            "",
            f"定期預金（0.1%）なら年 {savings_income:.0f}円",
            f"その {times:.0f}倍 が口座に振り込まれる",
            "",
            _CTA["c"],
        ]

    rank_lines = ["💰 利回り3.5%以上、意外と知られていない高配当株3選", "利回り3.5〜12%帯", ""]
    for i, r in enumerate(rows, 1):
        payout_s = f" / 配当性向 {r['payout_ratio']*100:.0f}%" if r["payout_ratio"] else ""
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   利回り {_fmt_yield(r['div_yield'])}{payout_s}")
    rank_lines += ["", "#高配当 #利回り #配当投資 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_11(conn) -> list[str]:
    """🏢 大型株ランキング（時価総額1兆円以上）"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, ds.total_score,
               cm.div_yield, cm.current_market_cap,
               cm.consecutive_dividend_growth_years, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.current_market_cap >= 1000000000000")}
        ORDER BY ds.total_score DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    close = _price(conn, top["code"])
    mc_cho = top["current_market_cap"] / 1e12
    sim = _sim(close, top["annual_div"], None) if close else None

    hook_lines = [
        f"{_short_name(top['name'])}（{top['code']}）",
        f"時価総額 {mc_cho:.1f}兆円",
        "",
        "100万円買うと",
        "",
    ]
    if sim:
        hook_lines += [
            f"💰 年間 {_fmt_man(sim['now'])} の配当が入る",
            f"　利回り {_fmt_yield(top['div_yield'])}",
            "",
        ]
    hook_lines += [
        f"{int(top['consecutive_dividend_growth_years'])}年連続増配",
        "安定感のある大企業でこの利回り",
        "",
        _CTA["b"],
    ]

    rank_lines = ["🏢 大企業なのに高配当、その3社", "時価総額1兆円以上 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        mc = f"{r['current_market_cap']/1e12:.1f}兆円" if r["current_market_cap"] else "-"
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   スコア {_fmt_score(r['total_score'])} / 利回り {_fmt_yield(r['div_yield'])} / 時価総額 {mc}")
    rank_lines += ["", "#大型株 #高配当 #安定株 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_12(conn) -> list[str]:
    """🏬 中型株ランキング（1000億〜1兆円）"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, ds.total_score,
               cm.div_yield, cm.current_market_cap, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.current_market_cap >= 100000000000 AND cm.current_market_cap < 1000000000000")}
        ORDER BY ds.total_score DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    close = _price(conn, top["code"])
    mc_oku = top["current_market_cap"] / 1e8
    sim = _sim(close, top["annual_div"], None) if close else None

    hook_lines = [
        f"{top['name']}",
        f"時価総額 {mc_oku:.0f}億円",
        "",
        "名前を知らない人も多いはず",
    ]
    if sim:
        hook_lines += [
            "",
            f"でも100万円買うと年間 {_fmt_man(sim['now'])}",
            f"利回り {_fmt_yield(top['div_yield'])}",
        ]
    hook_lines += [
        "",
        "大企業より知名度は低い",
        "配当力は負けていない",
        "",
        _CTA["c"],
    ]

    rank_lines = ["🏬 名前は知らないけど配当力は本物、中型株3選", "時価総額1000億〜1兆円 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        mc = f"{r['current_market_cap']/1e8:.0f}億円" if r["current_market_cap"] else "-"
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   スコア {_fmt_score(r['total_score'])} / 利回り {_fmt_yield(r['div_yield'])} / 時価総額 {mc}")
    rank_lines += ["", "#中型株 #高配当 #成長株 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_13(conn) -> list[str]:
    """💎 小型割安ランキング"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, ds.total_score,
               cm.div_yield, cm.pbr, cm.current_market_cap, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.current_market_cap < 100000000000 AND cm.pbr IS NOT NULL AND cm.pbr <= 1.5")}
        ORDER BY ds.total_score DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    mc_oku = top["current_market_cap"] / 1e8

    close = _price(conn, top["code"])
    sim = _sim(close, top["annual_div"], None) if close else None
    hook_lines = [
        f"{top['name']}",
        f"時価総額わずか {mc_oku:.0f}億円",
        "",
        "誰も知らないような小さな会社",
    ]
    if sim:
        hook_lines += [
            "",
            f"でも100万円買うと年間 {_fmt_man(sim['now'])}",
            f"利回り {_fmt_yield(top['div_yield'])}　PBR {top['pbr']:.2f}倍",
        ]
    hook_lines += [
        "",
        "小さくても配当は本物",
        "",
        _CTA["c"],
    ]

    rank_lines = ["💎 誰も知らないのに高配当、小型割安株3選", "時価総額1000億未満 / PBR1.5倍以下 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        mc = f"{r['current_market_cap']/1e8:.0f}億円" if r["current_market_cap"] else "-"
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   利回り {_fmt_yield(r['div_yield'])} / PBR {r['pbr']:.2f}倍 / 時価総額 {mc}")
    rank_lines += ["", "#小型株 #割安株 #高配当 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_14(conn) -> list[str]:
    """🔍 割安高配当（PBR1倍以下）"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, ds.total_score,
               cm.div_yield, cm.pbr, cm.per, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.pbr IS NOT NULL AND cm.pbr <= 1.0")}
        ORDER BY ds.total_score DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    return_pct = (1 / top["pbr"]) * 100

    close = _price(conn, top["code"])
    sim = _sim(close, top["annual_div"], None) if close else None
    hook_lines = [
        f"{top['name']}のPBRは {top['pbr']:.2f}倍",
        "",
        "今すぐ会社を解散すると",
        f"株主に {return_pct:.0f}% が返ってくる計算",
    ]
    if sim:
        hook_lines += [
            "",
            f"それでも年間 {_fmt_man(sim['now'])} の配当が出ている",
            f"（利回り {_fmt_yield(top['div_yield'])}）",
        ]
    hook_lines += [
        "",
        "解散しなくてもお得、解散してもお得",
        "",
        _CTA["b"],
    ]

    rank_lines = ["🔍 PBR1倍以下で高配当、本当に割安な株3選", "PBR1倍以下 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        per_s = f" / PER {r['per']:.1f}倍" if r["per"] else ""
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   利回り {_fmt_yield(r['div_yield'])} / PBR {r['pbr']:.2f}倍{per_s}")
    rank_lines += ["", "#割安株 #PBR #高配当 #バリュー投資 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def _sector_theme(conn, emoji, hook_prefix, title, sectors, tag, name_limit: int = 12) -> list[str]:
    placeholders = ",".join("?" * len(sectors))
    rows = conn.execute(f"""
        SELECT ds.code, st.name, st.sector, ds.total_score,
               cm.div_yield, cm.consecutive_dividend_growth_years, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE ds.scored_at = (SELECT MAX(scored_at) FROM dividend_scores)
          AND cm.div_yield >= 0.025
          AND st.sector IN ({placeholders})
        ORDER BY ds.total_score DESC
        LIMIT 3
    """, sectors).fetchall()
    top = rows[0]
    n = int(top["consecutive_dividend_growth_years"]) if top["consecutive_dividend_growth_years"] else 0
    close = _price(conn, top["code"])
    sim = _sim(close, top["annual_div"], None) if close and top["annual_div"] else None

    hook_lines = [hook_prefix.format(
        name=_short_name(top["name"], name_limit),
        code=top["code"],
        n=n,
        yield_=_fmt_yield(top["div_yield"]),
        score=_fmt_score(top["total_score"]),
    )]
    if sim:
        hook_lines += ["", f"💰 100万円で年間 {_fmt_man(sim['now'])}"]
    hook_lines += ["", _CTA["b"]]

    rank_lines = [f"{emoji} {title} 3選", "利回り2.5%以上 / 配当スコア順", ""]
    for i, r in enumerate(rows, 1):
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   スコア {_fmt_score(r['total_score'])} / 利回り {_fmt_yield(r['div_yield'])} / 連続増配 {_fmt_years(r['consecutive_dividend_growth_years'])}")
    rank_lines += ["", f"#{tag} #高配当株 #配当投資 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


def theme_15(conn) -> list[str]:
    """🏦 金融・保険セクター"""
    return _sector_theme(conn, "🏦",
        "{name}（{code}）\n{n}年連続増配 / 利回り{yield_}\n\n金融セクターの中でスコアトップ\n配当王者はここにいた",
        "金融・保険 高配当ランキング",
        ["銀行業", "保険業", "証券・商品先物取引業", "その他金融業"], "金融株")


def theme_16(conn) -> list[str]:
    """🌐 情報通信セクター"""
    return _sector_theme(conn, "🌐",
        "ITなのに{n}年連続増配\n\n{name}（{code}）が証明した\n成長×配当の両立",
        "情報通信 高配当ランキング",
        ["情報・通信業"], "IT株")


def theme_17(conn) -> list[str]:
    """🏭 製造業セクター"""
    return _sector_theme(conn, "🏭",
        "{name}（{code}）\n{n}年連続増配\n\nものづくり日本の底力",
        "製造業 高配当ランキング",
        ["機械", "電気機器", "輸送用機器", "精密機器", "鉄鋼", "非鉄金属", "金属製品"], "製造業")


def theme_18(conn) -> list[str]:
    """🛒 食料品・小売セクター"""
    return _sector_theme(conn, "🛒",
        "{name}（{code}）\n{n}年連続増配\n\n毎日の食卓から積み上がる\n配当の話",
        "食料品・小売 高配当ランキング",
        ["食料品", "小売業", "水産・農林業"], "食料品株", name_limit=8)


def theme_19(conn) -> list[str]:
    """🏗️ 建設・不動産セクター"""
    return _sector_theme(conn, "🏗️",
        "{name}（{code}）\n配当スコア{score}\n\n知名度は低くても\n数字は本物",
        "建設・不動産 高配当ランキング",
        ["建設業", "不動産業"], "建設株")


def theme_20(conn) -> list[str]:
    """🚀 モメンタムランキング"""
    rows = conn.execute("""
        SELECT ms.code, st.name, ms.total_score,
               cm.rel_ret_3m, cm.rel_ret_12m, cm.hi52_ratio
        FROM momentum_scores ms
        JOIN stocks st ON ms.code = st.code
        JOIN computed_metrics cm ON ms.code = cm.code
        WHERE ms.scored_at = (SELECT MAX(scored_at) FROM momentum_scores)
        ORDER BY ms.total_score DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]

    hi52_line = f"📊 52週高値の {top['hi52_ratio']*100:.0f}% 水準" if top["hi52_ratio"] else None
    hook_lines_clean = [
        f"{top['name']}",
        "",
        f"この3ヶ月で {_fmt_pct(top['rel_ret_3m'])} 上昇",
        f"直近12ヶ月で {_fmt_pct(top['rel_ret_12m'])} 上昇",
    ]
    if hi52_line:
        hook_lines_clean.append(hi52_line)
    hook_lines_clean += [
        "",
        "今まさに上昇トレンドの真っ只中",
        "乗り遅れる前に確認を",
        "",
        _CTA["c"],
    ]

    rank_lines = ["🚀 今まさに上昇トレンドにある銘柄3選", "モメンタムスコア順（全上場銘柄）", ""]
    for i, r in enumerate(rows, 1):
        hi52 = f" / 高値比 {r['hi52_ratio']*100:.0f}%" if r["hi52_ratio"] else ""
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   スコア {_fmt_score(r['total_score'])} / 3M {_fmt_pct(r['rel_ret_3m'])} / 12M {_fmt_pct(r['rel_ret_12m'])}{hi52}")
    rank_lines += ["", "#モメンタム投資 #成長株 #株式投資 #日本株"]

    return ["\n".join(hook_lines_clean), "\n".join(rank_lines)]


def theme_21(conn) -> list[str]:
    """💹 高ROE × 増配ランキング"""
    rows = conn.execute(f"""
        SELECT ds.code, st.name, ds.total_score,
               cm.roe, cm.div_yield, cm.consecutive_dividend_growth_years, cm.annual_div
        FROM dividend_scores ds
        JOIN stocks st ON ds.code = st.code
        JOIN computed_metrics cm ON ds.code = cm.code
        WHERE {_base_where("cm.roe IS NOT NULL AND cm.roe >= 0.15 AND cm.consecutive_dividend_growth_years >= 3")}
        ORDER BY cm.roe DESC
        LIMIT 3
    """).fetchall()
    top = rows[0]
    roe_pct = top["roe"] * 100

    close = _price(conn, top["code"])
    sim = _sim(close, top["annual_div"], None) if close else None
    hook_lines = [
        f"{top['name']}",
        "",
        f"ROE {roe_pct:.0f}%　自己資本100円で {roe_pct:.0f}円 を稼ぐ",
        "",
        f"{int(top['consecutive_dividend_growth_years'])}年連続で配当も増やしている",
    ]
    if sim:
        hook_lines += [
            "",
            f"💰 100万円で年間 {_fmt_man(sim['now'])}（利回り {_fmt_yield(top['div_yield'])}）",
        ]
    hook_lines += [
        "",
        "稼いで、還元する。その両立ランキング",
        "",
        _CTA["a"],
    ]

    rank_lines = ["💹 稼いで還元する、高ROE×増配の両立銘柄3選", "ROE15%以上 / 連続増配3年以上 / 利回り2.5%以上", ""]
    for i, r in enumerate(rows, 1):
        rank_lines.append(f"{MEDALS[i-1]} {r['name']}（{r['code']}）")
        rank_lines.append(f"   ROE {r['roe']*100:.1f}% / 利回り {_fmt_yield(r['div_yield'])} / 連続増配 {_fmt_years(r['consecutive_dividend_growth_years'])}")
    rank_lines += ["", "#ROE #増配 #優良株 #日本株"]

    return ["\n".join(hook_lines), "\n".join(rank_lines)]


# ══════════════════════════════════════════════════════
# テーマ名辞書  slug → (関数, 日本語ラベル, カテゴリ)
# ══════════════════════════════════════════════════════

THEMES: dict[str, tuple] = {
    "consecutive-growth":  (theme_01, "🌱 連続増配ランキング",             "増配・配当継続"),
    "growth-cagr":         (theme_02, "📈 増配成長率（10年CAGR）",          "増配・配当継続"),
    "no-cut":              (theme_03, "🛡️ 連続非減配ランキング",            "増配・配当継続"),
    "growth-yield":        (theme_04, "💎 増配継続×高利回り",               "増配・配当継続"),
    "growth-room":         (theme_05, "💪 増配余力（配当性向低）",           "増配・配当継続"),
    "fcf-coverage":        (theme_06, "🔄 FCF配当カバレッジ",               "増配・配当継続"),
    "long-growth":         (theme_07, "👑 長期増配の王様（10年以上）",       "増配・配当継続"),
    "growth-momentum":     (theme_08, "🌟 増配×モメンタム両取り",           "増配・配当継続"),
    "total":               (theme_09, "📊 配当スコア総合",                   "配当スコア"),
    "high-yield":          (theme_10, "💰 高利回り（3.5%以上）",             "配当スコア"),
    "large-cap":           (theme_11, "🏢 大型株（1兆円以上）",              "配当スコア"),
    "mid-cap":             (theme_12, "🏬 中型株（1000億〜1兆円）",          "配当スコア"),
    "small-value":         (theme_13, "💎 小型割安",                         "配当スコア"),
    "low-pbr":             (theme_14, "🔍 割安高配当（PBR1倍以下）",         "配当スコア"),
    "sector-finance":      (theme_15, "🏦 金融・保険セクター",               "セクター別"),
    "sector-tech":         (theme_16, "🌐 情報通信セクター",                 "セクター別"),
    "sector-mfg":          (theme_17, "🏭 製造業セクター",                   "セクター別"),
    "sector-food":         (theme_18, "🛒 食料品・小売セクター",             "セクター別"),
    "sector-construction": (theme_19, "🏗️ 建設・不動産セクター",            "セクター別"),
    "momentum":            (theme_20, "🚀 モメンタムランキング",             "モメンタム・複合"),
    "high-roe":            (theme_21, "💹 高ROE×増配",                      "モメンタム・複合"),
}


# ══════════════════════════════════════════════════════
# スケジューラー  7日 × 3投稿 = 21テーマ
# ══════════════════════════════════════════════════════

SCHEDULE: list[list[str]] = [
    ["consecutive-growth", "total",      "momentum"],            # 月
    ["growth-cagr",        "high-yield", "sector-finance"],      # 火
    ["no-cut",             "large-cap",  "sector-tech"],         # 水
    ["growth-yield",       "mid-cap",    "sector-mfg"],          # 木
    ["growth-room",        "small-value","sector-food"],         # 金
    ["fcf-coverage",       "low-pbr",    "sector-construction"], # 土
    ["long-growth",        "growth-momentum", "high-roe"],       # 日
]

SLOT_NAMES = ["朝（9:00）", "昼（12:00）", "夕（18:30）"]


def generate_by_theme(slug: str) -> list[str]:
    """テーマ名（slug）を指定して [フック, ランキング] を返す。"""
    if slug not in THEMES:
        raise ValueError(f"不明なテーマ: {slug}\n利用可能: {list(THEMES)}")
    fn, label, _ = THEMES[slug]
    conn = _conn()
    texts = fn(conn)
    conn.close()
    return texts


def today_schedule() -> list[dict]:
    """今日のスケジュール（3スロット）を返す。"""
    weekday = date.today().weekday()
    return [
        {"slot": SLOT_NAMES[i], "slug": slug, "label": THEMES[slug][1]}
        for i, slug in enumerate(SCHEDULE[weekday])
    ]


def generate(day_offset: int = 0, slot: int | None = None) -> list[dict]:
    """
    指定日のテキストを生成。

    Returns:
        [{"slot": "朝（9:00）", "slug": "...", "label": "...", "texts": ["フック", "ランキング"]}]
    """
    from datetime import timedelta
    conn = _conn()
    target = date.today() + timedelta(days=day_offset)
    weekday = target.weekday()
    slugs = SCHEDULE[weekday]

    slots = [slot] if slot is not None else [0, 1, 2]
    results = []
    for s in slots:
        slug = slugs[s]
        fn, label, _ = THEMES[slug]
        results.append({
            "slot":  SLOT_NAMES[s],
            "slug":  slug,
            "label": label,
            "texts": fn(conn),
        })

    conn.close()
    return results
