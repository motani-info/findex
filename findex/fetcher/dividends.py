"""yfinance配当履歴から①②③⑮を計算するフェッチャー"""
import time
import yfinance as yf
import pandas as pd

from findex.cache import load_cache, save_cache

FETCHER = "dividends"
TTL_DAYS = 7


def _fiscal_year(date) -> int:
    return date.year if date.month >= 4 else date.year - 1


def _calc_metrics(divs: pd.Series) -> dict:
    _empty = {"consecutive_no_cut_years": 0,
              "consecutive_dividend_growth_years": 0,
              "dividend_growth_5y_cagr": None,
              "dividend_growth_10y_cagr": None,
              "dividend_reliability": 0.0,
              "dividend_cut_count_20y": 0}

    if divs.empty:
        return _empty

    fy = divs.index.map(_fiscal_year)
    annual = divs.groupby(fy).sum().sort_index()

    if len(annual) < 2:
        return _empty

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

    # ③ 5年配当成長率CAGR
    cagr_5y = None
    if len(annual) >= 6:
        v_now, v_5y = vals[-1], vals[-6]
        if v_5y > 0:
            cagr_5y = round((v_now / v_5y) ** (1 / 5) - 1, 6)

    # 減配信頼性スコア（過去20会計年度での減配回数に基づく）
    # 0回 → 1.0（満点）、1回 → 0.6（危機1回は許容）、2回以上 → 0.0
    # 連続非減配年数①が「現在の継続」を測るのに対し、
    # こちらは「歴史全体での信頼性」＝リーマン・コロナを何度乗り越えたかを測る
    recent_yrs = annual[annual.index >= (annual.index[-1] - 19)]
    recent_vals = recent_yrs.values
    cuts_20y = sum(
        1 for i in range(1, len(recent_vals)) if recent_vals[i] < recent_vals[i - 1]
    )
    if cuts_20y == 0:
        dividend_reliability = 1.0
    elif cuts_20y == 1:
        dividend_reliability = 0.6
    else:
        dividend_reliability = 0.0

    # ⑮ 10年配当成長率CAGR
    # 定義: 直近10会計年度の複利成長率 = (FY_latest / FY_10y_ago)^(1/10) - 1
    # 必要条件: 11期以上のデータ（不足 → None → 0点）
    # 異常値除外: |CAGR| > 50% は除外
    cagr_10y = None
    if len(annual) >= 11:
        v_now, v_10y = vals[-1], vals[-11]
        if v_10y > 0:
            raw = (v_now / v_10y) ** (1 / 10) - 1
            cagr_10y = round(raw, 6) if -0.50 < raw < 0.50 else None

    # 年間配当/株（直近12ヶ月の合計）
    one_year_ago = divs.index[-1] - pd.DateOffset(years=1)
    recent_divs = divs[divs.index > one_year_ago]
    annual_dividend_per_share = round(float(recent_divs.sum()), 4) if len(recent_divs) > 0 else None

    return {"consecutive_no_cut_years": no_cut,
            "consecutive_dividend_growth_years": growth,
            "dividend_growth_5y_cagr": cagr_5y,
            "dividend_growth_10y_cagr": cagr_10y,
            "dividend_reliability": dividend_reliability,
            "dividend_cut_count_20y": cuts_20y,
            "annual_dividend_per_share": annual_dividend_per_share}


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
                   "dividend_growth_5y_cagr": None,
                   "dividend_growth_10y_cagr": None,
                   "dividend_reliability": 0.0,
                   "dividend_cut_count_20y": 0}
    time.sleep(delay)
    return {"code": code, **metrics}


def fetch_dividends(codes: list[str], delay: float = 0.5,
                    workers: int = 1, refresh: bool = False) -> pd.DataFrame:
    """銘柄コードリストの配当履歴指標（①②③⑮）を取得する。キャッシュTTL=7日。"""
    if workers <= 1:
        return pd.DataFrame([_fetch_with_cache(c, delay, refresh) for c in codes])

    from concurrent.futures import ThreadPoolExecutor
    import functools
    fn = functools.partial(_fetch_with_cache, delay=delay, refresh=refresh)
    with ThreadPoolExecutor(max_workers=min(workers, 5)) as ex:
        rows = list(ex.map(fn, codes))
    return pd.DataFrame(rows)
