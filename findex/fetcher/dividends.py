"""yfinance配当履歴から①②③を計算するフェッチャー"""
import time
import yfinance as yf
import pandas as pd

from findex.cache import load_cache, save_cache

FETCHER = "dividends"
TTL_DAYS = 7


def _fiscal_year(date) -> int:
    return date.year if date.month >= 4 else date.year - 1


def _calc_metrics(divs: pd.Series) -> dict:
    if divs.empty:
        return {"consecutive_no_cut_years": 0,
                "consecutive_dividend_growth_years": 0,
                "dividend_growth_5y_cagr": None}

    fy = divs.index.map(_fiscal_year)
    annual = divs.groupby(fy).sum().sort_index()

    if len(annual) < 2:
        return {"consecutive_no_cut_years": 0,
                "consecutive_dividend_growth_years": 0,
                "dividend_growth_5y_cagr": None}

    vals = annual.values

    no_cut = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] >= vals[i - 1]:
            no_cut += 1
        else:
            break

    growth = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] > vals[i - 1]:
            growth += 1
        else:
            break

    cagr = None
    if len(annual) >= 6:
        v_now, v_5y = vals[-1], vals[-6]
        if v_5y > 0:
            cagr = round((v_now / v_5y) ** (1 / 5) - 1, 6)

    return {"consecutive_no_cut_years": no_cut,
            "consecutive_dividend_growth_years": growth,
            "dividend_growth_5y_cagr": cagr}


def _fetch_with_cache(code: str, delay: float, refresh: bool) -> dict:
    if not refresh:
        cached = load_cache(FETCHER, code, ttl_days=TTL_DAYS)
        if cached:
            return {"code": code, **cached}
    try:
        divs    = yf.Ticker(f"{code}.T").dividends
        metrics = _calc_metrics(divs)
        save_cache(FETCHER, code, metrics)
    except Exception:
        metrics = {"consecutive_no_cut_years": 0,
                   "consecutive_dividend_growth_years": 0,
                   "dividend_growth_5y_cagr": None}
    time.sleep(delay)
    return {"code": code, **metrics}


def fetch_dividends(codes: list[str], delay: float = 0.5,
                    workers: int = 1, refresh: bool = False) -> pd.DataFrame:
    """銘柄コードリストの配当履歴指標（①②③）を取得する。キャッシュTTL=1日。"""
    if workers <= 1:
        return pd.DataFrame([_fetch_with_cache(c, delay, refresh) for c in codes])

    from concurrent.futures import ThreadPoolExecutor
    import functools
    fn = functools.partial(_fetch_with_cache, delay=delay, refresh=refresh)
    with ThreadPoolExecutor(max_workers=min(workers, 5)) as ex:
        rows = list(ex.map(fn, codes))
    return pd.DataFrame(rows)
