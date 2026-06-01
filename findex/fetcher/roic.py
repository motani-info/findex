"""yfinanceからROIC-WACC（⑨）と利益剰余金配当倍率（⑬）を計算するフェッチャー"""
import time
import yfinance as yf
import pandas as pd

from findex.cache import load_cache, save_cache

FETCHER = "roic"
TTL_DAYS = 7

RF  = 0.0265   # JGB10年利回り（2026年5月時点）
ERP = 0.065    # 日本株式リスクプレミアム（Damodaran 2026）
DEFAULT_TAX_RATE = 0.30
DEFAULT_BETA     = 1.0


def _safe_float(df: pd.DataFrame, key: str) -> float | None:
    try:
        v = df.loc[key].iloc[0]
        return float(v) if v is not None and not pd.isna(v) else None
    except Exception:
        return None


def _calc_roic_wacc(info: dict, financials: pd.DataFrame, bs: pd.DataFrame) -> float | None:
    op_income = _safe_float(financials, "Operating Income") or info.get("operatingIncome")
    if not op_income:
        return None
    tax_rate = _safe_float(financials, "Tax Rate For Calcs") or DEFAULT_TAX_RATE
    nopat    = op_income * (1 - tax_rate)

    equity     = _safe_float(bs, "Stockholders Equity") or _safe_float(bs, "Common Stock Equity")
    total_debt = info.get("totalDebt") or 0.0
    invested_capital = (equity or 0.0) + total_debt
    if invested_capital <= 0:
        return None
    roic = nopat / invested_capital

    beta       = info.get("beta") or DEFAULT_BETA
    market_cap = info.get("marketCap")
    if not market_cap:
        return None
    Re = RF + beta * ERP
    D, E = total_debt, market_cap
    V = E + D
    if V <= 0:
        return None
    try:
        interest = abs(_safe_float(financials, "Interest Expense") or
                       _safe_float(financials, "Interest Expense Non Operating") or 0.0)
        Rd = interest / D if D > 0 else 0.0
    except Exception:
        Rd = 0.0
    wacc   = (E / V * Re) + (D / V * Rd * (1 - tax_rate))
    result = roic - wacc
    return round(result, 6) if -0.5 < result < 0.5 else None


def _calc_retained_earnings_div_ratio(info: dict, bs: pd.DataFrame) -> float | None:
    retained  = _safe_float(bs, "Retained Earnings")
    if retained is None or retained <= 0:
        return None
    div_rate = info.get("dividendRate")
    shares   = info.get("sharesOutstanding")
    if not div_rate or not shares or div_rate <= 0:
        return None
    annual_div = div_rate * shares
    if annual_div <= 0:
        return None
    result = retained / annual_div
    return round(result, 4) if 0 < result < 1000 else None


def _fetch_with_cache(code: str, delay: float, refresh: bool) -> dict:
    if not refresh:
        cached = load_cache(FETCHER, code, ttl_days=TTL_DAYS)
        if cached:
            return {"code": code, **cached}
    try:
        t          = yf.Ticker(f"{code}.T")
        info       = t.info
        financials = t.financials
        bs         = t.balance_sheet
        data = {
            "roic_minus_wacc":             _calc_roic_wacc(info, financials, bs),
            "retained_earnings_div_ratio": _calc_retained_earnings_div_ratio(info, bs),
        }
        save_cache(FETCHER, code, data)
    except Exception:
        data = {"roic_minus_wacc": None, "retained_earnings_div_ratio": None}
    time.sleep(delay)
    return {"code": code, **data}


def fetch_roic(codes: list[str], delay: float = 0.5,
               workers: int = 1, refresh: bool = False) -> pd.DataFrame:
    """⑨ roic_minus_wacc と ⑬ retained_earnings_div_ratio を取得する。キャッシュTTL=1日。"""
    if workers <= 1:
        return pd.DataFrame([_fetch_with_cache(c, delay, refresh) for c in codes])

    from concurrent.futures import ThreadPoolExecutor
    import functools
    fn = functools.partial(_fetch_with_cache, delay=delay, refresh=refresh)
    with ThreadPoolExecutor(max_workers=min(workers, 5)) as ex:
        rows = list(ex.map(fn, codes))
    return pd.DataFrame(rows)
