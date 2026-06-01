"""1銘柄につきyf.Tickerを1回だけ生成し、全指標を一括取得するフェッチャー。
fundamentals / dividends / roic を個別に叩く代わりにこれを使う。
"""
import time
import yfinance as yf
import pandas as pd

from findex.cache import load_cache, save_cache
from findex.fetcher.fundamentals import (
    _calc_div_yield, _safe, _bs_value,
    _equity_ratio, _debt_to_equity, _net_cash_per, _mix_coefficient,
)
from findex.fetcher.dividends import _calc_metrics
from findex.fetcher.roic import (
    _calc_roic_wacc, _calc_retained_earnings_div_ratio, _safe_float,
)

TTL_DAYS = 7


def _fetch_one_all(code: str) -> dict:
    """1銘柄の全指標をyf.Ticker1回で取得する"""
    symbol = f"{code}.T"
    t          = yf.Ticker(symbol)
    info       = t.info
    bs         = t.balance_sheet
    financials = t.financials
    divs       = t.dividends

    div_metrics = _calc_metrics(divs)

    data = {
        # ④ 予想配当性向
        "payout_ratio":     _safe(info, "payoutRatio"),
        # ⑤ EPS成長率
        "eps_growth_5y":    _safe(info, "earningsGrowth"),
        # ⑥ 自己資本比率
        "equity_ratio":     _equity_ratio(bs),
        # ⑦ 有利子負債比率
        "debt_to_equity":   _debt_to_equity(bs),
        # ⑧ ROE
        "roe":              _safe(info, "returnOnEquity"),
        # ⑨ ROIC-WACC
        "roic_minus_wacc":  _calc_roic_wacc(info, financials, bs),
        # ⑩ 営業利益率
        "operating_margin": _safe(info, "operatingMargins"),
        # ⑪ 配当利回り
        "div_yield":        _calc_div_yield(info),
        # ⑫ ネットキャッシュPER
        "net_cash_per":     _net_cash_per(bs, info),
        # ⑬ 利益剰余金配当倍率
        "retained_earnings_div_ratio": _calc_retained_earnings_div_ratio(info, bs),
        # ⑭ ミックス係数
        "mix_coefficient":  _mix_coefficient(info),
        # ①②③ 配当履歴
        **div_metrics,
        # 参考情報
        "per":        _safe(info, "trailingPE"),
        "pbr":        _safe(info, "priceToBook"),
        "market_cap": _safe(info, "marketCap"),
        "total_debt": (_safe(info, "totalDebt") or 0.0),
        "beta":       _safe(info, "beta"),
    }

    # 3つのキャッシュに分けて保存（既存fetcherとの互換性維持）
    save_cache("fundamentals", code, {
        k: data[k] for k in [
            "payout_ratio", "eps_growth_5y", "equity_ratio", "debt_to_equity",
            "roe", "operating_margin", "div_yield", "net_cash_per",
            "mix_coefficient", "per", "pbr", "market_cap", "total_debt", "beta",
        ]
    })
    save_cache("dividends", code, {
        k: data[k] for k in [
            "consecutive_no_cut_years", "consecutive_dividend_growth_years",
            "dividend_growth_5y_cagr",
        ]
    })
    save_cache("roic", code, {
        k: data[k] for k in [
            "roic_minus_wacc", "retained_earnings_div_ratio",
        ]
    })

    return data


def _all_cached(code: str) -> dict | None:
    """3つのキャッシュが全て揃っていれば統合して返す"""
    f = load_cache("fundamentals", code, ttl_days=TTL_DAYS)
    d = load_cache("dividends",    code, ttl_days=TTL_DAYS)
    r = load_cache("roic",         code, ttl_days=TTL_DAYS)
    if f is None or d is None or r is None:
        return None
    return {**f, **d, **r}


def fetch_all(codes: list[str], delay: float = 0.3,
              refresh: bool = False) -> pd.DataFrame:
    """全銘柄の全指標を取得する。キャッシュ済みはスキップ。進捗を表示する。"""
    total   = len(codes)
    cached  = sum(1 for c in codes if not refresh and _all_cached(c) is not None)
    missing = total - cached
    print(f"キャッシュ済み: {cached}件 / 新規取得: {missing}件", flush=True)

    rows = []
    done = 0
    for code in codes:
        if not refresh:
            hit = _all_cached(code)
            if hit:
                rows.append({"code": code, **hit})
                continue

        try:
            data = _fetch_one_all(code)
            rows.append({"code": code, **data})
        except Exception as e:
            rows.append({"code": code})

        done += 1
        # 50件ごとに進捗表示
        if done % 50 == 0 or done == missing:
            pct = done / missing * 100 if missing else 100
            print(f"  [{done}/{missing}] {pct:.0f}% 取得中...", flush=True)

        time.sleep(delay)

    return pd.DataFrame(rows)
