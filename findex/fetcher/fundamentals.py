"""yfinanceで財務指標を取得する（Findexの12指標スコアリング向け）"""
import time
import yfinance as yf
import pandas as pd

from findex.cache import load_cache, save_cache

FETCHER = "fundamentals"
TTL_DAYS = 7


def _calc_div_yield(info: dict) -> float | None:
    div_rate = info.get("dividendRate")
    price    = info.get("regularMarketPrice") or info.get("currentPrice")
    if div_rate and price and div_rate > 0 and price > 0:
        yld = div_rate / price
        if 0 < yld <= 0.30:
            return yld
    trailing = info.get("trailingAnnualDividendYield")
    if trailing and 0 < trailing <= 0.30:
        return trailing
    return None


def _safe(d: dict, key, default=None):
    v = d.get(key)
    return v if v not in (None, "N/A", float("inf"), float("-inf")) else default


def _bs_value(bs: pd.DataFrame, *keys) -> float | None:
    for key in keys:
        try:
            v = bs.loc[key].iloc[0]
            if v is not None and not pd.isna(v):
                return float(v)
        except Exception:
            continue
    return None


def _equity_ratio(bs: pd.DataFrame) -> float | None:
    equity = _bs_value(bs, "Stockholders Equity", "Common Stock Equity")
    assets = _bs_value(bs, "Total Assets")
    if equity is not None and assets:
        return equity / assets
    return None


def _debt_to_equity(bs: pd.DataFrame) -> float | None:
    long_debt  = _bs_value(bs, "Long Term Debt", "Long Term Debt And Capital Lease Obligation") or 0.0
    short_debt = _bs_value(bs, "Current Debt", "Current Debt And Capital Lease Obligation", "Short Term Debt") or 0.0
    equity = _bs_value(bs, "Stockholders Equity", "Common Stock Equity")
    total_debt = long_debt + short_debt
    if equity and equity > 0:
        return total_debt / equity
    return None


def _net_cash_per(bs: pd.DataFrame, info: dict) -> float | None:
    current_assets    = _bs_value(bs, "Current Assets")
    total_liabilities = _bs_value(bs, "Total Liabilities Net Minority Interest", "Total Liabilities")
    market_cap = _safe(info, "marketCap")
    per        = _safe(info, "trailingPE")
    if None in (current_assets, total_liabilities, market_cap, per):
        return None
    if market_cap <= 0 or per <= 0:
        return None
    net_cash = current_assets - total_liabilities
    result = per * (1 - net_cash / market_cap)
    return result if -500 < result < 500 else None


def _mix_coefficient(info: dict) -> float | None:
    per = _safe(info, "trailingPE")
    pbr = _safe(info, "priceToBook")
    if per and pbr and per > 0 and pbr > 0:
        return per * pbr
    return None


def _fetch_one(code: str) -> dict:
    """1銘柄の財務データを取得して辞書で返す"""
    symbol = f"{code}.T"
    t    = yf.Ticker(symbol)
    info = t.info
    bs   = t.balance_sheet
    return {
        "code":             code,
        "payout_ratio":     _safe(info, "payoutRatio"),
        "eps_growth_5y":    _safe(info, "earningsGrowth"),
        "equity_ratio":     _equity_ratio(bs),
        "debt_to_equity":   _debt_to_equity(bs),
        "roe":              _safe(info, "returnOnEquity"),
        "operating_margin": _safe(info, "operatingMargins"),
        "div_yield":        _calc_div_yield(info),
        "net_cash_per":     _net_cash_per(bs, info),
        "mix_coefficient":  _mix_coefficient(info),
        "per":              _safe(info, "trailingPE"),
        "pbr":              _safe(info, "priceToBook"),
        "market_cap":       _safe(info, "marketCap"),
        "total_debt":       (_safe(info, "totalDebt") or 0.0),
        "beta":             _safe(info, "beta"),
    }


def _fetch_with_cache(code: str, delay: float, refresh: bool) -> dict:
    if not refresh:
        cached = load_cache(FETCHER, code, ttl_days=TTL_DAYS)
        if cached:
            return {"code": code, **cached}
    try:
        row  = _fetch_one(code)
        data = {k: v for k, v in row.items() if k != "code"}
        save_cache(FETCHER, code, data)
        time.sleep(delay)
        return row
    except Exception:
        time.sleep(delay)
        return {"code": code}


def fetch_fundamentals(codes: list[str], delay: float = 0.5,
                       workers: int = 1, refresh: bool = False) -> pd.DataFrame:
    """銘柄コードリストの財務指標を取得する。キャッシュTTL=1日。
    workers > 1 で ThreadPoolExecutor による並列取得。
    """
    if workers <= 1:
        return pd.DataFrame([_fetch_with_cache(c, delay, refresh) for c in codes])

    from concurrent.futures import ThreadPoolExecutor
    import functools
    fn = functools.partial(_fetch_with_cache, delay=delay, refresh=refresh)
    with ThreadPoolExecutor(max_workers=min(workers, 5)) as ex:
        rows = list(ex.map(fn, codes))
    return pd.DataFrame(rows)
