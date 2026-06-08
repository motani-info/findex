"""computed_metrics 計算: raw_financials + price_history + dividend_history → computed_metrics"""
from __future__ import annotations

import time
from datetime import datetime, date, timedelta

from findex.db import (
    get_db, get_raw_financials, upsert_computed_metrics,
)

# ROIC-WACC パラメータ（roic.pyから流用）
RF = 0.0265
ERP = 0.065
DEFAULT_TAX_RATE = 0.30
DEFAULT_BETA = 1.0


def _cagr(v_now: float | None, v_old: float | None, periods: int) -> float | None:
    if not v_now or not v_old or v_old <= 0 or v_now <= 0 or periods < 2:
        return None
    cagr = (v_now / v_old) ** (1 / (periods - 1)) - 1
    return round(cagr, 6) if -0.5 < cagr < 0.5 else None


def _compute_one(raw: dict, price_data: dict, div_data: dict) -> dict:
    """1銘柄の computed_metrics を計算する。"""
    now_iso = datetime.now().isoformat(timespec="seconds")
    result: dict = {}

    # ── 財務由来 ──
    ta = raw.get("total_assets")
    eq = raw.get("stockholders_equity")
    if ta and ta > 0 and eq is not None:
        result["equity_ratio"] = eq / ta

    ld = raw.get("long_term_debt") or 0
    sd = raw.get("short_term_debt") or 0
    if eq and eq > 0:
        result["debt_to_equity"] = (ld + sd) / eq

    result["eps_growth_5y"] = _cagr(
        raw.get("diluted_eps_latest"), raw.get("diluted_eps_5y_ago"),
        raw.get("diluted_eps_periods") or 0,
    )
    result["revenue_growth_5y_cagr"] = _cagr(
        raw.get("total_revenue_latest"), raw.get("total_revenue_5y_ago"),
        raw.get("total_revenue_periods") or 0,
    )

    # ROIC-WACC
    # 簡易版: raw に operating income がないので operating_margins * revenue で推定
    rev = raw.get("total_revenue_latest")
    om = raw.get("operating_margins")
    if rev and om:
        op_income = rev * om
        nopat = op_income * (1 - DEFAULT_TAX_RATE)
        invested = (eq or 0) + ld + sd
        if invested > 0:
            roic = nopat / invested
            beta = raw.get("beta") or DEFAULT_BETA
            mc = raw.get("market_cap")
            if mc and mc > 0:
                Re = RF + beta * ERP
                D = ld + sd
                V = mc + D
                if V > 0:
                    wacc = (mc / V * Re) + (D / V * 0.02 * (1 - DEFAULT_TAX_RATE))
                    rv = roic - wacc
                    if -0.5 < rv < 0.5:
                        result["roic_minus_wacc"] = round(rv, 6)

    # FCF配当カバレッジ
    fcf = raw.get("free_cashflow")
    if not fcf:
        opcf = raw.get("operating_cashflow")
        capex = raw.get("capital_expenditures")
        if opcf is not None and capex is not None:
            fcf = opcf + capex  # capex is negative
    dr = raw.get("dividend_rate")
    shares = raw.get("shares_outstanding")
    if fcf and fcf > 0 and dr and shares and dr > 0:
        annual_div_total = dr * shares
        if annual_div_total > 0:
            cov = fcf / annual_div_total
            if 0 < cov < 100:
                result["fcf_payout_coverage"] = round(cov, 4)

    # 利益剰余金配当倍率
    re = raw.get("retained_earnings")
    if re and re > 0 and dr and shares and dr > 0:
        annual_div_total = dr * shares
        if annual_div_total > 0:
            ratio = re / annual_div_total
            if 0 < ratio < 1000:
                result["retained_earnings_div_ratio"] = round(ratio, 4)

    # raw から直接持ち越す財務指標
    result["roe"] = raw.get("roe")
    result["operating_margin"] = raw.get("operating_margins")
    result["payout_ratio"] = raw.get("payout_ratio")

    result["fin_computed_at"] = now_iso

    # ── 価格由来 ──
    latest_price = price_data.get("latest_close")
    eps = raw.get("eps")
    bps = raw.get("bps")
    if latest_price and eps and eps > 0:
        result["per"] = round(latest_price / eps, 2)
    if latest_price and bps and bps > 0:
        result["pbr"] = round(latest_price / bps, 3)
    if latest_price and shares:
        result["current_market_cap"] = latest_price * shares
    if dr and latest_price and latest_price > 0:
        result["div_yield"] = dr / latest_price

    per = result.get("per")
    pbr = result.get("pbr")
    if per and pbr and per > 0 and pbr > 0:
        result["mix_coefficient"] = round(per * pbr, 2)

    # net_cash_per
    ca = raw.get("current_assets")
    tl = raw.get("total_liabilities")
    mc = raw.get("market_cap") or result.get("current_market_cap")
    if ca is not None and tl is not None and mc and mc > 0 and per:
        net_cash = ca - tl
        ncp = per * (1 - net_cash / mc)
        if -500 < ncp < 500:
            result["net_cash_per"] = round(ncp, 2)

    # モメンタム
    result["ret_3m"] = price_data.get("ret_3m")
    result["ret_12m"] = price_data.get("ret_12m")
    result["rel_ret_3m"] = price_data.get("rel_ret_3m")
    result["rel_ret_12m"] = price_data.get("rel_ret_12m")
    result["hi52_ratio"] = price_data.get("hi52_ratio")
    if any(result.get(k) is not None for k in ("ret_3m", "ret_12m", "hi52_ratio")):
        result["price_computed_at"] = now_iso

    # ── 配当由来 ──
    result["annual_div"] = div_data.get("annual_div")
    result["consecutive_no_cut_years"] = div_data.get("consecutive_no_cut_years")
    result["consecutive_dividend_growth_years"] = div_data.get("consecutive_dividend_growth_years")
    result["dividend_growth_5y_cagr"] = div_data.get("dividend_growth_5y_cagr")
    result["dividend_growth_10y_cagr"] = div_data.get("dividend_growth_10y_cagr")
    result["dividend_reliability"] = div_data.get("dividend_reliability")
    result["dividend_cut_count_20y"] = div_data.get("dividend_cut_count_20y")
    if div_data.get("annual_div") is not None:
        result["div_computed_at"] = now_iso

    return result


def _get_price_data(conn, code: str) -> dict:
    """price_historyから価格由来指標を計算する。"""
    rows = conn.execute(
        "SELECT date, close FROM price_history WHERE code=? ORDER BY date DESC LIMIT 400",
        (code,),
    ).fetchall()
    if len(rows) < 10:
        return {}

    import pandas as pd
    df = pd.DataFrame(rows, columns=["date", "close"]).set_index("date").sort_index()
    latest = float(df["close"].iloc[-1])
    today = date.today()
    d3m = (today - timedelta(days=91)).isoformat()
    d12m = (today - timedelta(days=366)).isoformat()

    past3 = df[df.index <= d3m]
    past12 = df[df.index <= d12m]
    ret_3m = (latest / float(past3["close"].iloc[-1]) - 1) if not past3.empty else None
    ret_12m = (latest / float(past12["close"].iloc[-1]) - 1) if not past12.empty else None
    hi52_range = df[df.index >= d12m]["close"]
    hi52_ratio = (latest / float(hi52_range.max())) if not hi52_range.empty else None

    # TOPIX相対リターン（簡易: TOPIXデータがなければ絶対リターンを使用）
    return {
        "latest_close": latest,
        "ret_3m": round(ret_3m, 6) if ret_3m is not None else None,
        "ret_12m": round(ret_12m, 6) if ret_12m is not None else None,
        "rel_ret_3m": round(ret_3m, 6) if ret_3m is not None else None,
        "rel_ret_12m": round(ret_12m, 6) if ret_12m is not None else None,
        "hi52_ratio": round(hi52_ratio, 4) if hi52_ratio is not None else None,
    }


def _get_dividend_data(conn, code: str) -> dict:
    """dividend_historyから配当由来指標を計算する。"""
    rows = conn.execute(
        "SELECT ex_date, amount FROM dividend_history WHERE code=? ORDER BY ex_date DESC",
        (code,),
    ).fetchall()
    if not rows:
        return {}

    from collections import defaultdict
    today = date.today()
    one_year_ago = (today - timedelta(days=365)).isoformat()

    # 直近12ヶ月配当合計
    annual_div = sum(r[1] for r in rows if r[0] >= one_year_ago)

    # 年別集計
    yearly: dict[int, float] = defaultdict(float)
    for ex_date, amount in rows:
        year = int(ex_date[:4])
        yearly[year] += amount

    if len(yearly) < 2:
        return {"annual_div": annual_div if annual_div > 0 else None}

    # 当年が未完（支払回数が前年より少ない）の場合はストリーク計算から除外
    yearly_count: dict[int, int] = defaultdict(int)
    for ex_date, _ in rows:
        yearly_count[int(ex_date[:4])] += 1

    all_years = sorted(yearly.keys(), reverse=True)
    current_year = today.year
    if all_years[0] == current_year and len(all_years) >= 2:
        if yearly_count[current_year] < yearly_count[all_years[1]]:
            streak_years = all_years[1:]
        else:
            streak_years = all_years
    else:
        streak_years = all_years
    years_sorted = all_years  # CAGR・cut_count は全年で計算

    # 連続非減配（当年未確定を除いた年で計算）
    no_cut = 0
    for i in range(len(streak_years) - 1):
        if yearly[streak_years[i]] >= yearly[streak_years[i + 1]] * 0.95:
            no_cut += 1
        else:
            break

    # 連続増配
    growth = 0
    for i in range(len(streak_years) - 1):
        if yearly[streak_years[i]] > yearly[streak_years[i + 1]] * 1.001:
            growth += 1
        else:
            break

    # 配当CAGR
    n5 = min(len(years_sorted), 6)
    cagr_5y = None
    if n5 >= 2 and yearly[years_sorted[0]] > 0 and yearly[years_sorted[n5 - 1]] > 0:
        cagr_5y = (yearly[years_sorted[0]] / yearly[years_sorted[n5 - 1]]) ** (1 / (n5 - 1)) - 1
        if not (-0.5 < cagr_5y < 1.0):
            cagr_5y = None

    n10 = min(len(years_sorted), 11)
    cagr_10y = None
    if n10 >= 2 and yearly[years_sorted[0]] > 0 and yearly[years_sorted[n10 - 1]] > 0:
        cagr_10y = (yearly[years_sorted[0]] / yearly[years_sorted[n10 - 1]]) ** (1 / (n10 - 1)) - 1
        if not (-0.5 < cagr_10y < 1.0):
            cagr_10y = None

    # 20年減配回数
    cut_count = 0
    for i in range(len(years_sorted) - 1):
        if yearly[years_sorted[i]] < yearly[years_sorted[i + 1]] * 0.95:
            cut_count += 1

    # 配当信頼性（非減配率）
    total_pairs = len(years_sorted) - 1
    reliability = (total_pairs - cut_count) / total_pairs if total_pairs > 0 else None

    return {
        "annual_div": annual_div if annual_div > 0 else None,
        "consecutive_no_cut_years": no_cut,
        "consecutive_dividend_growth_years": growth,
        "dividend_growth_5y_cagr": round(cagr_5y, 6) if cagr_5y else None,
        "dividend_growth_10y_cagr": round(cagr_10y, 6) if cagr_10y else None,
        "dividend_reliability": round(reliability, 4) if reliability else None,
        "dividend_cut_count_20y": cut_count,
    }


def run_compute(codes: list[str] | None = None) -> dict:
    """computed_metrics 計算メイン処理。"""
    t0 = time.time()
    conn = get_db()

    # 対象: raw_financials に存在する銘柄
    if codes:
        placeholders = ",".join("?" * len(codes))
        rows = conn.execute(
            f"SELECT code FROM raw_financials WHERE code IN ({placeholders})", codes
        ).fetchall()
    else:
        rows = conn.execute("SELECT code FROM raw_financials").fetchall()
    target = [r[0] for r in rows]

    if not target:
        print("compute: 対象銘柄なし（raw_financials が空）", flush=True)
        return {"updated": 0, "skipped": 0, "elapsed_sec": 0}

    print(f"computed_metrics計算対象: {len(target)}銘柄", flush=True)

    # raw_financials を一括取得
    raw_df = get_raw_financials(conn, target)
    raw_map = {r["code"]: r for _, r in raw_df.iterrows()}

    updated = skipped = 0
    for i, code in enumerate(target):
        raw = raw_map.get(code)
        if raw is None:
            skipped += 1
            continue

        price_data = _get_price_data(conn, code)
        div_data = _get_dividend_data(conn, code)
        metrics = _compute_one(dict(raw), price_data, div_data)
        upsert_computed_metrics(conn, code, metrics)
        updated += 1

        if (i + 1) % 500 == 0 or (i + 1) == len(target):
            conn.commit()
            print(f"  [{i+1}/{len(target)}]", flush=True)

    conn.commit()
    conn.close()
    elapsed = time.time() - t0
    print(f"computed_metrics計算完了: updated={updated} elapsed={elapsed:.1f}s", flush=True)
    return {"updated": updated, "skipped": skipped, "elapsed_sec": elapsed}
