"""
モメンタムスコアリングエンジン

配当スコアとは独立した「株価上昇トレンド・業績加速」の評価軸。
AI株・テーマ株のように今まさに上がっている銘柄を発見する。

スコア構成（100点満点）:
  価格モメンタム系（50点）
    ├── 12ヶ月リターン  weight 2.0  threshold +30%で満点
    ├──  3ヶ月リターン  weight 1.5  threshold +15%で満点
    └── 52週高値比率    weight 1.5  0.90以上（高値の90%以上）で満点

  業績加速系（50点）
    ├── 売上成長率      weight 2.0  +20%以上で満点
    ├── EPS成長率       weight 2.0  +20%以上で満点
    └── 出来高増加率    weight 1.0  1.5倍以上で満点
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

DB_PATH = "/Users/motani/.findex/db/findex.db"

MOMENTUM_RULES = [
    # V3: 絶対リターン→TOPIX相対リターンに変更（市場全体の上昇を除去）
    #     配当スコアのROE・営業利益率を流用（質の高い銘柄のモメンタムは持続しやすい）
    #
    # ── 価格モメンタム ──
    {"name": "3M相対リターン",   "field": "rel_ret_3m",       "direction": "high", "threshold": 0.05, "weight": 2.5, "upper_cap": 0.30},
    {"name": "52週高値比率",     "field": "hi52_ratio",        "direction": "high", "threshold": 0.85, "weight": 2.0, "upper_cap": None},
    {"name": "12M相対リターン",  "field": "rel_ret_12m",      "direction": "high", "threshold": 0.10, "weight": 1.5, "upper_cap": 0.50},
    # ── 業績モメンタム ──
    {"name": "売上成長率",       "field": "rev_growth",        "direction": "high", "threshold": 0.15, "weight": 2.0, "upper_cap": None},
    {"name": "EPS成長率",        "field": "eps_growth",        "direction": "high", "threshold": 0.15, "weight": 2.0, "upper_cap": None},
    # ── 配当スコアから流用（質フィルター）──
    {"name": "ROE",              "field": "roe",               "direction": "high", "threshold": 0.15, "weight": 1.0, "upper_cap": None},
    {"name": "営業利益率",       "field": "operating_margin",  "direction": "high", "threshold": 0.15, "weight": 1.0, "upper_cap": None},
    # ── 出来高（データ蓄積待ち）──
    {"name": "出来高増加率",     "field": "vol_ratio",         "direction": "high", "threshold": 1.50, "weight": 0.5, "upper_cap": None},
]
MAX_WEIGHTED = sum(r["weight"] * 10 for r in MOMENTUM_RULES)  # 100点換算の分母


def _score_one(val: float | None, rule: dict) -> float:
    if val is None or pd.isna(val):
        return 0.0
    if rule["threshold"] == 0:
        return 0.0
    # upper_cap: 上限超えは過熱ゾーンとして0点（例: 12M+60%超は平均回帰リスク）
    upper_cap = rule.get("upper_cap")
    if upper_cap is not None and val > upper_cap:
        return 0.0
    raw = val / rule["threshold"] * 10
    return round(min(10.0, max(0.0, raw)), 4)


def _calc_momentum_score(fields: dict) -> dict:
    detail = {}
    weighted_sum = 0.0
    for rule in MOMENTUM_RULES:
        s = _score_one(fields.get(rule["field"]), rule)
        detail[rule["name"]] = round(s, 2)
        weighted_sum += s * rule["weight"]
    total = round(weighted_sum / MAX_WEIGHTED * 100, 2)
    return {"total": total, **detail}


def _get_candidates(
    top_n: int,
    market: Optional[str],
    sector: Optional[str],
    min_div_score: Optional[float],
    large_cap: bool,
    mid_cap: bool,
    small_cap: bool,
) -> list[dict]:
    """スコアDBから候補銘柄を取得"""
    conn = sqlite3.connect(DB_PATH)
    where = ["s.rowid IN (SELECT MAX(rowid) FROM scores GROUP BY code)"]
    if market:
        where.append(f"st.market LIKE '%{market}%'")
    if sector:
        where.append(f"st.sector LIKE '%{sector}%'")
    if min_div_score:
        where.append(f"s.total_score >= {min_div_score}")
    if large_cap:
        where.append("json_extract(s.raw_json, '$.market_cap') >= 500000000000")
    if mid_cap:
        where.append("json_extract(s.raw_json, '$.market_cap') >= 100000000000")
        where.append("json_extract(s.raw_json, '$.market_cap') < 500000000000")
    if small_cap:
        where.append("json_extract(s.raw_json, '$.market_cap') < 100000000000")

    rows = conn.execute(f"""
        SELECT s.code, st.name, st.sector, s.total_score,
               json_extract(s.raw_json, '$.market_cap') as market_cap
        FROM scores s
        JOIN stocks st ON s.code = st.code
        WHERE {' AND '.join(where)}
        ORDER BY s.total_score DESC
        LIMIT 3000
    """).fetchall()

    # yfinance info から売上・EPS成長を取得済みの銘柄を優先しつつ全候補を返す
    result = [{"code": r[0], "name": r[1], "sector": r[2],
               "div_score": r[3], "market_cap": r[4]} for r in rows]
    conn.close()
    return result


def run_momentum(
    top: int = 30,
    years_price: float = 1.0,
    market: Optional[str] = None,
    sector: Optional[str] = None,
    min_div_score: Optional[float] = None,
    large_cap: bool = False,
    mid_cap: bool = False,
    small_cap: bool = False,
    out: Optional[str] = None,
) -> None:
    import click

    candidates = _get_candidates(top, market, sector, min_div_score,
                                  large_cap, mid_cap, small_cap)
    if not candidates:
        click.echo("候補銘柄なし")
        return

    codes = [c["code"] for c in candidates]
    click.echo(f"候補 {len(codes)}銘柄の株価・業績データを取得中...")

    # ── 株価モメンタム: price_history から取得（なければyfinance）──
    conn = sqlite3.connect(DB_PATH)
    today_str = date.today().isoformat()
    d3m  = (date.today() - timedelta(days=91)).isoformat()
    d12m = (date.today() - timedelta(days=366)).isoformat()

    # price_history から取得
    price_data: dict[str, dict] = {}
    for code in codes:
        rows = conn.execute("""
            SELECT date, close FROM price_history
            WHERE code=? ORDER BY date DESC LIMIT 400
        """, (code,)).fetchall()
        if len(rows) < 10:
            continue
        df_p = pd.DataFrame(rows, columns=["date", "close"]).set_index("date").sort_index()
        latest = float(df_p["close"].iloc[-1])

        # 3ヶ月前
        past3 = df_p[df_p.index <= d3m]
        ret_3m = (latest / float(past3["close"].iloc[-1]) - 1) if not past3.empty else None

        # 12ヶ月前
        past12 = df_p[df_p.index <= d12m]
        ret_12m = (latest / float(past12["close"].iloc[-1]) - 1) if not past12.empty else None

        # 52週高値比率
        hi52 = df_p[df_p.index >= d12m]["close"].max() if not past12.empty else None
        hi52_ratio = (latest / hi52) if hi52 else None

        price_data[code] = {
            "ret_3m": ret_3m,
            "ret_12m": ret_12m,
            "hi52_ratio": hi52_ratio,
        }

    conn.close()

    # ── TOPIX基準リターン取得（1306.T = TOPIX連動ETF）──────────────
    topix_ret_3m: float | None = None
    topix_ret_12m: float | None = None
    try:
        topix_raw = yf.download("1306.T", period="13mo", interval="1mo",
                                auto_adjust=True, progress=False)
        if not topix_raw.empty:
            tc = topix_raw["Close"] if "Close" in topix_raw.columns else topix_raw.iloc[:, 0]
            if hasattr(tc, "columns"):
                tc = tc.iloc[:, 0]
            tc = tc.dropna()
            if len(tc) >= 4:
                topix_ret_3m  = float(tc.iloc[-1] / tc.iloc[-4] - 1)
            if len(tc) >= 2:
                topix_ret_12m = float(tc.iloc[-1] / tc.iloc[0] - 1)
    except Exception:
        pass
    click.echo(f"  TOPIX基準: 3M={topix_ret_3m and f'{topix_ret_3m*100:+.1f}%' or 'N/A'}  "
               f"12M={topix_ret_12m and f'{topix_ret_12m*100:+.1f}%' or 'N/A'}")

    # price_historyにデータがない銘柄はyfinanceから補完
    missing = [c for c in codes if c not in price_data]
    if missing:
        click.echo(f"  price_historyにない {len(missing)}銘柄をyfinanceから取得...")
        BATCH = 100
        import time
        for i in range(0, len(missing), BATCH):
            batch_tickers = [f"{c}.T" for c in missing[i:i+BATCH]]
            raw = yf.download(batch_tickers, period="13mo", interval="1mo",
                              auto_adjust=True, progress=False, threads=False)
            if raw.empty:
                continue
            close = raw["Close"] if "Close" in raw.columns else raw
            if isinstance(close, pd.Series):
                close = close.to_frame(name=batch_tickers[0])
            for ticker in batch_tickers:
                code = ticker.replace(".T", "")
                if ticker not in close.columns:
                    continue
                col = close[ticker].dropna()
                if len(col) < 4:
                    continue
                latest = float(col.iloc[-1])
                ret_3m  = (latest / float(col.iloc[-4]) - 1) if len(col) >= 4 else None
                ret_12m = (latest / float(col.iloc[0]) - 1)
                hi52    = float(col.max())
                price_data[code] = {
                    "ret_3m": ret_3m,
                    "ret_12m": ret_12m,
                    "hi52_ratio": latest / hi52 if hi52 > 0 else None,
                }
            if i + BATCH < len(missing):
                time.sleep(5)

    # TOPIX相対リターンを計算
    for code, pd_ in price_data.items():
        pd_["rel_ret_3m"]  = ((pd_["ret_3m"]  - topix_ret_3m)
                              if pd_.get("ret_3m")  is not None and topix_ret_3m  is not None
                              else pd_.get("ret_3m"))
        pd_["rel_ret_12m"] = ((pd_["ret_12m"] - topix_ret_12m)
                              if pd_.get("ret_12m") is not None and topix_ret_12m is not None
                              else pd_.get("ret_12m"))

    # ── 業績データ: stock_fundamentals + raw_json（ROE・営業利益率）──
    conn = sqlite3.connect(DB_PATH)
    fund_rows = conn.execute("""
        SELECT code, revenue_growth_5y_cagr, eps_growth_5y
        FROM stock_fundamentals WHERE code IN ({})
    """.format(",".join(["?"] * len(codes))), codes).fetchall()

    # raw_json から ROE・営業利益率を取得（配当スコア計算時に取得済み）
    quality_rows = conn.execute("""
        SELECT code,
               json_extract(raw_json, '$.roe')              as roe,
               json_extract(raw_json, '$.operating_margin') as operating_margin
        FROM scores
        WHERE code IN ({}) AND raw_json IS NOT NULL
        GROUP BY code HAVING MAX(scored_at)
    """.format(",".join(["?"] * len(codes))), codes).fetchall()
    conn.close()

    fund_map = {r[0]: {"rev_growth": r[1], "eps_growth": r[2]} for r in fund_rows}
    quality_map = {r[0]: {"roe": r[1], "operating_margin": r[2]} for r in quality_rows}

    # ── スコア計算 ────────────────────────────────────────────────
    results = []
    for c in candidates:
        code = c["code"]
        if code not in price_data:
            continue
        fields = {
            **price_data[code],
            **fund_map.get(code, {}),
            **quality_map.get(code, {}),
            "vol_ratio": None,  # 出来高はprice_history蓄積後
        }
        score_detail = _calc_momentum_score(fields)
        mc = c["market_cap"]
        mc_str = (f"{mc/1e12:.1f}兆" if mc and mc >= 1e12
                  else f"{mc/1e8:.0f}億" if mc and mc >= 1e9 else "-")
        results.append({
            **c,
            "mc_str": mc_str,
            "momentum_score": score_detail["total"],
            **{r["name"]: score_detail[r["name"]] for r in MOMENTUM_RULES},
            **fields,
        })

    results.sort(key=lambda x: x["momentum_score"], reverse=True)
    top_results = results[:top]

    if not top_results:
        click.echo("スコア計算できる銘柄なし（price_historyが空の可能性）")
        return

    # ── 表示 ──────────────────────────────────────────────────────
    cat_parts = []
    if large_cap: cat_parts.append("大型株")
    if mid_cap:   cat_parts.append("中型株")
    if small_cap: cat_parts.append("小型株")
    if sector:    cat_parts.append(sector)
    if market:    cat_parts.append(market)
    cat = " × ".join(cat_parts) if cat_parts else "全銘柄"
    if min_div_score: cat += f"（配当スコア{min_div_score:.0f}点以上）"

    click.echo(f"\n{'━'*90}")
    click.echo(f" モメンタムランキング: {cat}  TOP{len(top_results)}")
    click.echo(f"{'━'*90}")
    click.echo(
        f"{'Rank':>4}  {'CODE':>6}  {'会社名':<20}  {'Momentum':>8}  "
        f"{'12M相対':>8}  {'3M相対':>7}  {'高値比':>6}  {'売上成長':>8}  {'ROE':>6}  {'配当Score':>9}  {'時価総額':>7}"
    )
    click.echo("-" * 90)

    for i, r in enumerate(top_results, 1):
        rel12 = f"{r['rel_ret_12m']*100:+.1f}%" if r.get("rel_ret_12m") is not None else "-"
        rel3  = f"{r['rel_ret_3m']*100:+.1f}%"  if r.get("rel_ret_3m")  is not None else "-"
        hi52  = f"{r['hi52_ratio']*100:.0f}%"   if r.get("hi52_ratio")  is not None else "-"
        rev   = f"{r['rev_growth']*100:+.1f}%"  if r.get("rev_growth")  is not None else "-"
        roe   = f"{r['roe']*100:.0f}%"           if r.get("roe")         is not None else "-"
        ds    = f"{r['div_score']:.1f}"          if r.get("div_score") else "-"
        click.echo(
            f"{i:>4}  {r['code']:>6}  {str(r['name'])[:20]:<20}  "
            f"{r['momentum_score']:>7.1f}点  "
            f"{rel12:>8}  {rel3:>7}  {hi52:>6}  {rev:>8}  {roe:>6}  {ds:>9}  {r['mc_str']:>7}"
        )

    click.echo(f"\n合計 {len(top_results)} 件 / {len(results)} 件中（価格データあり）")
    click.echo(f"{'━'*90}\n")

    # CSV出力
    if out and top_results:
        import csv
        headers = ["rank", "code", "name", "sector", "momentum_score", "div_score",
                   "ret_12m_pct", "ret_3m_pct", "hi52_ratio_pct", "rev_growth_pct",
                   "eps_growth_pct", "market_cap"]
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for i, r in enumerate(top_results, 1):
                w.writerow([
                    i, r["code"], r["name"], r["sector"],
                    round(r["momentum_score"], 2), r.get("div_score"),
                    round(r["ret_12m"] * 100, 2) if r.get("ret_12m") is not None else None,
                    round(r["ret_3m"]  * 100, 2) if r.get("ret_3m")  is not None else None,
                    round(r["hi52_ratio"] * 100, 2) if r.get("hi52_ratio") is not None else None,
                    round(r["rev_growth"] * 100, 2) if r.get("rev_growth") is not None else None,
                    round(r["eps_growth"] * 100, 2) if r.get("eps_growth") is not None else None,
                    r["market_cap"],
                ])
        click.echo(f"CSV保存: {out}")
