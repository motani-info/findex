"""J-Quantsデータから各スコアリング指標を計算する。
yfinanceの計算関数と同等の出力を返す（フィールド名を統一）。
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

# WACC定数（roic.pyと統一）
RF               = 0.0265
ERP              = 0.065
DEFAULT_TAX_RATE = 0.30
DEFAULT_BETA     = 1.0

# 会計年度（4月始まり）
def _fiscal_year(date_str: str) -> int:
    try:
        d = pd.to_datetime(date_str)
        return d.year if d.month >= 4 else d.year - 1
    except Exception:
        return 0


def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _latest_annual(stmts: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """通期決算（CurPerType=FY）の実績値を直近n期返す。
    J-Quants V2 fins/summary のフィールド構造に対応。
    DocTypeが FYFinancialStatements* のものを優先。
    """
    if stmts.empty:
        return pd.DataFrame()

    # 通期実績のみ（CurPerType=FY、かつFYFinancialStatementsを含む）
    annual = stmts[
        (stmts.get("CurPerType", pd.Series(dtype=str)) == "FY") &
        stmts.get("DocType", pd.Series(dtype=str)).str.contains(
            "FYFinancialStatements", na=False
        )
    ].copy()

    if annual.empty:
        # フォールバック: CurPerType=FYのみで絞る
        annual = stmts[stmts.get("CurPerType", pd.Series(dtype=str)) == "FY"].copy()

    if annual.empty:
        return pd.DataFrame()

    # 同一会計年度の重複は最新開示を優先
    date_col = "DiscDate" if "DiscDate" in annual.columns else "DisclosedDate"
    per_col  = "CurPerEn" if "CurPerEn" in annual.columns else "CurPerType"
    if date_col in annual.columns:
        annual = annual.sort_values(date_col, ascending=False)
    if per_col in annual.columns:
        annual = annual.drop_duplicates(subset=[per_col], keep="first")
        annual = annual.sort_values(per_col, ascending=True)

    return annual.tail(n)


# ── 配当系指標 ────────────────────────────────────────────────────
def calc_dividend_metrics(div_df: pd.DataFrame) -> dict:
    """
    ①  consecutive_no_cut_years
    ②  consecutive_dividend_growth_years
    ③  dividend_growth_5y_cagr
    ⑮  dividend_growth_10y_cagr
        dividend_reliability
        dividend_cut_count_20y
    """
    empty = {
        "consecutive_no_cut_years": 0,
        "consecutive_dividend_growth_years": 0,
        "dividend_growth_5y_cagr": None,
        "dividend_growth_10y_cagr": None,
        "dividend_reliability": 0.0,
        "dividend_cut_count_20y": 0,
        "annual_dividend_per_share": None,
    }
    if div_df.empty:
        return empty

    # 配当金額フィールドを自動検出
    div_col = next(
        (c for c in ["AnnualDividendPerShare", "DividendPerShare", "Dividend"] if c in div_df.columns),
        None,
    )
    date_col = next(
        (c for c in ["RecordDate", "ExDate", "PayableDate", "Date"] if c in div_df.columns),
        None,
    )
    if not div_col or not date_col:
        return empty

    df = div_df[[date_col, div_col]].copy()
    df[div_col]  = pd.to_numeric(df[div_col], errors="coerce")
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna()
    df = df[df[div_col] > 0]
    if df.empty:
        return empty

    # 会計年度ごとに集計
    df["fy"] = df[date_col].apply(lambda d: d.year if d.month >= 4 else d.year - 1)
    annual = df.groupby("fy")[div_col].sum().sort_index()
    latest_div = float(annual.iloc[-1])

    if len(annual) < 2:
        return {**empty, "annual_dividend_per_share": latest_div}

    vals = annual.values

    # ① 連続非減配年数
    no_cut = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] >= vals[i - 1]:
            no_cut += 1
        else:
            break

    # ② 連続増配年数
    growth = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] > vals[i - 1]:
            growth += 1
        else:
            break

    # ③ 5年CAGR
    cagr_5y = None
    if len(annual) >= 6:
        v_now, v_5y = vals[-1], vals[-6]
        if v_5y > 0:
            raw = (v_now / v_5y) ** (1 / 5) - 1
            cagr_5y = round(raw, 6) if -0.5 < raw < 0.5 else None

    # ⑮ 10年CAGR
    cagr_10y = None
    if len(annual) >= 11:
        v_now, v_10y = vals[-1], vals[-11]
        if v_10y > 0:
            raw = (v_now / v_10y) ** (1 / 10) - 1
            cagr_10y = round(raw, 6) if -0.5 < raw < 0.5 else None

    # 減配信頼性（過去20年）
    recent = annual[annual.index >= (annual.index[-1] - 19)].values
    cuts_20y = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])
    reliability = 1.0 if cuts_20y == 0 else (0.6 if cuts_20y == 1 else 0.0)

    return {
        "consecutive_no_cut_years": no_cut,
        "consecutive_dividend_growth_years": growth,
        "dividend_growth_5y_cagr": cagr_5y,
        "dividend_growth_10y_cagr": cagr_10y,
        "dividend_reliability": reliability,
        "dividend_cut_count_20y": cuts_20y,
        "annual_dividend_per_share": latest_div,
    }


# ── 財務系指標 ────────────────────────────────────────────────────
def calc_financial_metrics(
    annual: pd.DataFrame,
    close_price: float | None,
    market_cap: float | None,
    annual_div_per_share: float | None,
    beta: float | None = None,
) -> dict:
    """財務諸表から全スコアリング指標を計算する。"""

    def col(name, df=annual):
        """最新期の値を安全に取得。V2 fins/summary フィールド名を優先。"""
        # V2 fins/summary フィールド: Sales,OP,NP,EPS,BPS,TA,Eq など短縮形
        aliases = {
            "NetSales":             ["Sales", "NetSales", "TotalRevenue"],
            "OperatingProfit":      ["OP", "OperatingProfit", "OperatingIncome"],
            "NetIncome":            ["NP", "NetIncome", "Profit"],
            "TotalAssets":          ["TA", "TotalAssets"],
            "Equity":               ["Eq", "Equity", "NetAssets", "StockholdersEquity"],
            "RetainedEarnings":     ["RetainedEarnings", "RE"],
            "EPS":                  ["EPS", "EarningsPerShare", "BasicEarningsPerShare"],
            "BPS":                  ["BPS", "BookValuePerShare"],
            "SharesOutstanding":    ["SharesOutstanding", "NumberOfShares",
                                     "IssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock"],
            "InterestBearingDebt":  ["InterestBearingDebt", "TotalDebt", "BorrowingsAndBonds"],
            "OperatingCF":          ["CFO", "OperatingCF", "CashFlowsFromOperatingActivities"],
            "InvestingCF":          ["CFI", "InvestingCF", "CashFlowsFromInvestingActivities"],
            "CashAndEquivalents":   ["Cash", "CashAndCashEquivalents", "CashAndEquivalents"],
            "TaxRate":              ["EffectiveTaxRate"],
        }
        candidates = aliases.get(name, [name])
        for c in candidates:
            if c in df.columns:
                v = _safe_float(df[c].iloc[-1]) if not df.empty else None
                if v is not None:
                    return v
        return None

    def col_series(name):
        """複数期の値をSeriesで取得"""
        aliases = {
            "NetSales": ["NetSales", "TotalRevenue", "Sales"],
            "EPS":      ["EarningsPerShare", "BasicEarningsPerShare", "EPS"],
        }
        candidates = aliases.get(name, [name])
        for c in candidates:
            if c in annual.columns:
                s = pd.to_numeric(annual[c], errors="coerce").dropna()
                if len(s) > 0:
                    return s
        return pd.Series(dtype=float)

    net_income  = col("NetIncome")
    equity      = col("Equity")
    total_assets = col("TotalAssets")
    op_profit   = col("OperatingProfit")
    net_sales   = col("NetSales")
    interest_bearing_debt = col("InterestBearingDebt") or 0.0
    op_cf       = col("OperatingCF")
    inv_cf      = col("InvestingCF")
    retained    = col("RetainedEarnings")
    eps_latest  = col("EPS")
    bps_latest  = col("BPS")
    tax_rate    = col("TaxRate") or DEFAULT_TAX_RATE

    # ④ 配当性向（純利益ベース）
    payout_ratio = None
    if net_income and net_income > 0 and annual_div_per_share and eps_latest and eps_latest > 0:
        payout_ratio = annual_div_per_share / eps_latest
        if not (0 < payout_ratio <= 2.0):
            payout_ratio = None

    # ⑤ EPS成長率 CAGR（3〜5年）
    eps_series = col_series("EPS")
    eps_growth_5y = None
    if len(eps_series) >= 2:
        n = min(len(eps_series), 5)
        v_now, v_old = float(eps_series.iloc[-1]), float(eps_series.iloc[-n])
        if v_old > 0 and v_now > 0:
            raw = (v_now / v_old) ** (1 / (n - 1)) - 1
            eps_growth_5y = round(raw, 6) if -0.5 < raw < 0.5 else None

    # ⑥ 自己資本比率
    equity_ratio = None
    if equity is not None and total_assets and total_assets > 0:
        equity_ratio = equity / total_assets

    # ⑦ 有利子負債比率
    debt_to_equity = None
    if equity and equity > 0:
        debt_to_equity = interest_bearing_debt / equity

    # ⑧ ROE
    roe = None
    if net_income is not None and equity and equity > 0:
        roe = net_income / equity

    # ⑨ ROIC-WACC
    roic_minus_wacc = None
    if op_profit and equity and market_cap and market_cap > 0:
        nopat = op_profit * (1 - tax_rate)
        invested_capital = (equity or 0) + interest_bearing_debt
        if invested_capital > 0:
            roic = nopat / invested_capital
            b    = beta or DEFAULT_BETA
            Re   = RF + b * ERP
            D, E = interest_bearing_debt, market_cap
            V    = E + D
            if V > 0:
                # 支払利息は推定（有利子負債 × 2%）
                Rd   = 0.02
                wacc = (E / V * Re) + (D / V * Rd * (1 - tax_rate))
                result = roic - wacc
                roic_minus_wacc = round(result, 6) if -0.5 < result < 0.5 else None

    # ⑩ 営業利益率
    operating_margin = None
    if op_profit is not None and net_sales and net_sales > 0:
        operating_margin = op_profit / net_sales

    # ⑪ 配当利回り
    div_yield = None
    if annual_div_per_share and close_price and close_price > 0:
        y = annual_div_per_share / close_price
        div_yield = y if 0 < y <= 0.30 else None

    # ⑫ ネットキャッシュPER
    net_cash_per = None
    cash = col("CashAndEquivalents")
    if (cash is not None and total_assets is not None and market_cap and market_cap > 0
            and close_price and eps_latest and eps_latest > 0):
        per = close_price / eps_latest
        total_liab = total_assets - (equity or 0)
        net_cash   = (cash or 0) - total_liab
        result     = per * (1 - net_cash / market_cap)
        net_cash_per = result if -500 < result < 500 else None

    # ⑬ 利益剰余金配当倍率
    retained_earnings_div_ratio = None
    if retained and retained > 0 and annual_div_per_share:
        shares = col("SharesOutstanding")
        if not shares and bps_latest and close_price and close_price > 0:
            # 株数を推定: market_cap / close_price
            shares = market_cap / close_price if market_cap else None
        if shares and shares > 0:
            annual_div_total = annual_div_per_share * shares
            if annual_div_total > 0:
                r = retained / annual_div_total
                retained_earnings_div_ratio = round(r, 4) if 0 < r < 1000 else None

    # ⑭ ミックス係数 (PER × PBR)
    mix_coefficient = None
    if close_price and eps_latest and eps_latest > 0 and bps_latest and bps_latest > 0:
        per = close_price / eps_latest
        pbr = close_price / bps_latest
        if per > 0 and pbr > 0:
            mix_coefficient = per * pbr

    # FCF配当カバレッジ
    fcf_payout_coverage = None
    if op_cf is not None and inv_cf is not None:
        fcf = op_cf + inv_cf  # 投資CFは負値
        if fcf > 0 and annual_div_per_share:
            shares = col("SharesOutstanding")
            if not shares and market_cap and close_price and close_price > 0:
                shares = market_cap / close_price
            if shares and shares > 0:
                annual_div = annual_div_per_share * shares
                if annual_div > 0:
                    r = fcf / annual_div
                    fcf_payout_coverage = round(r, 4) if 0 < r < 100 else None

    # 売上高5年CAGR
    revenue_growth_5y_cagr = None
    rev_series = col_series("NetSales")
    if len(rev_series) >= 2:
        n = min(len(rev_series), 5)
        v_now, v_old = float(rev_series.iloc[-1]), float(rev_series.iloc[-n])
        if v_old > 0 and v_now > 0:
            raw = (v_now / v_old) ** (1 / (n - 1)) - 1
            revenue_growth_5y_cagr = round(raw, 6) if -0.5 < raw < 0.5 else None

    # PER / PBR（参考値）
    per = close_price / eps_latest if (close_price and eps_latest and eps_latest > 0) else None
    pbr = close_price / bps_latest if (close_price and bps_latest and bps_latest > 0) else None

    return {
        "payout_ratio":                payout_ratio,
        "eps_growth_5y":               eps_growth_5y,
        "equity_ratio":                equity_ratio,
        "debt_to_equity":              debt_to_equity,
        "roe":                         roe,
        "roic_minus_wacc":             roic_minus_wacc,
        "operating_margin":            operating_margin,
        "div_yield":                   div_yield,
        "net_cash_per":                net_cash_per,
        "retained_earnings_div_ratio": retained_earnings_div_ratio,
        "mix_coefficient":             mix_coefficient,
        "fcf_payout_coverage":         fcf_payout_coverage,
        "revenue_growth_5y_cagr":      revenue_growth_5y_cagr,
        "per":                         per,
        "pbr":                         pbr,
        "market_cap":                  market_cap,
        "total_debt":                  interest_bearing_debt,
        "beta":                        beta,
    }
