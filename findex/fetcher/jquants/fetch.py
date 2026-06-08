"""J-Quants メインフェッチャー
一括APIで全銘柄のデータを取得し、yfinanceと同じDataFrame形式で返す。

TTL戦略（種類別キャッシュ）:
  statements  : TTL=90日（四半期決算ごとに更新）
  dividend    : TTL=30日
  prices      : TTL=1日（株価は毎日変動）
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from findex.cache import CACHE_DIR
from .client import JQuantsClient
from .metrics import calc_dividend_metrics, calc_financial_metrics, _latest_annual

# キャッシュTTL（種類別）
TTL = {
    "jq_statements": 90,
    "jq_dividend":   30,
    "jq_prices":      1,
}

CACHE_NS = {k: CACHE_DIR / k for k in TTL}


def _cache_path(ns: str, key: str) -> Path:
    return CACHE_NS[ns] / f"{key}.json"


def _load_bulk_cache(ns: str) -> pd.DataFrame | None:
    """全銘柄一括キャッシュ（bulk.json）を読み込む"""
    p = _cache_path(ns, "bulk")
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        fetched_at = datetime.fromisoformat(d["fetched_at"])
        if (datetime.now() - fetched_at).days >= TTL[ns]:
            return None
        return pd.DataFrame(d["data"])
    except Exception:
        return None


def _save_bulk_cache(ns: str, df: pd.DataFrame):
    CACHE_NS[ns].mkdir(parents=True, exist_ok=True)
    (_cache_path(ns, "bulk")).write_text(json.dumps({
        "fetched_at": datetime.now().isoformat(),
        "data":       df.to_dict(orient="records"),
    }, ensure_ascii=False, default=str))


# ── データ取得（一括）────────────────────────────────────────────
def _get_trading_dates(date_from: datetime, date_to: datetime) -> list[str]:
    """平日（月〜金）の日付リストを生成（日本市場の営業日近似）"""
    dates = []
    cur = date_from
    while cur <= date_to:
        if cur.weekday() < 5:  # 月〜金
            dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return dates


def _fetch_statements(client: JQuantsClient, refresh: bool) -> pd.DataFrame:
    """財務サマリー（/v2/fins/summary）を全銘柄・直近2年分一括取得。
    1日ごとにdate指定して全銘柄の開示を収集（= 約500営業日 × 平均100件/日）。
    """
    if not refresh:
        cached = _load_bulk_cache("jq_statements")
        if cached is not None:
            print("  財務サマリー: キャッシュ使用", flush=True)
            return cached

    # プランの許可範囲（直近2年）
    date_from = datetime.now() - timedelta(days=365 * 2)
    date_to   = datetime.now()
    dates = _get_trading_dates(date_from, date_to)
    print(f"  財務サマリー: {len(dates)}営業日分を取得中...", flush=True)

    rows: list[dict] = []
    for i, d in enumerate(dates):
        try:
            chunk = client.fins_summary(date=d)
            rows.extend(chunk)
        except Exception:
            pass  # 開示なしの日は空 → スキップ
        if (i + 1) % 100 == 0:
            print(f"    [{i+1}/{len(dates)}] {len(rows)}件収集済み", flush=True)
        time.sleep(0.05)  # 50ms（レート制限対策）

    df = pd.DataFrame(rows)
    if not df.empty:
        # FY（通期）実績のみ保持してサイズを削減
        fy_mask = (
            df.get("CurPerType", pd.Series(dtype=str)).eq("FY") &
            df.get("DocType", pd.Series(dtype=str)).str.contains("FYFinancialStatements", na=False)
        )
        df = df[fy_mask].copy()
        _save_bulk_cache("jq_statements", df)
    print(f"  財務サマリー: {len(df)}件（通期実績）取得完了", flush=True)
    return df


def _fetch_dividends(client: JQuantsClient, refresh: bool) -> pd.DataFrame:
    """配当情報（/v2/fins/dividend）を全銘柄・直近12年分取得"""
    if not refresh:
        cached = _load_bulk_cache("jq_dividend")
        if cached is not None:
            print("  配当データ: キャッシュ使用", flush=True)
            return cached

    print("  配当データ: 取得中（全銘柄・直近12年）...", flush=True)
    rows: list[dict] = []
    current = datetime.now() - timedelta(days=365 * 13)
    end     = datetime.now()
    while current < end:
        chunk_end = min(current + timedelta(days=365), end)
        chunk = client.fins_dividend(
            date_from=current.strftime("%Y-%m-%d"),
            date_to=chunk_end.strftime("%Y-%m-%d"),
        )
        rows.extend(chunk)
        current = chunk_end + timedelta(days=1)
        time.sleep(0.3)

    df = pd.DataFrame(rows)
    if not df.empty:
        _save_bulk_cache("jq_dividend", df)
    print(f"  配当データ: {len(df)}件取得", flush=True)
    return df


def _fetch_prices(client: JQuantsClient, refresh: bool) -> pd.DataFrame:
    """株価（/v2/equities/bars/daily）を全銘柄・直近5営業日分取得して最新値を残す"""
    if not refresh:
        cached = _load_bulk_cache("jq_prices")
        if cached is not None:
            print("  株価: キャッシュ使用", flush=True)
            return cached

    print("  株価: 取得中（全銘柄・直近10日）...", flush=True)
    date_from = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    date_to   = datetime.now().strftime("%Y-%m-%d")
    rows = client.equities_bars_daily(date_from=date_from, date_to=date_to)
    df = pd.DataFrame(rows)
    if not df.empty:
        # V2フィールド: C=終値, AdjC=調整済み終値, Date=日付
        date_col = "Date" if "Date" in df.columns else df.columns[0]
        code_col = "Code" if "Code" in df.columns else df.columns[1]
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.sort_values(date_col).groupby(code_col).last().reset_index()
        _save_bulk_cache("jq_prices", df)
    print(f"  株価: {len(df)}銘柄取得", flush=True)
    return df


# ── コードの正規化 ───────────────────────────────────────────────
def _norm_code(code: str) -> str:
    """J-QuantsコードとFindexコードの対応。
    J-Quantsは5桁（例: '72030'）、Findexは4桁（例: '7203'）。
    """
    return code.rstrip("0") if len(code) == 5 else code


# ── 1銘柄の指標を計算 ────────────────────────────────────────────
def _calc_one(
    code4: str,                  # 4桁コード
    stmts_df:  pd.DataFrame,
    div_df:    pd.DataFrame,
    price_row: pd.Series | None,
    beta_map:  dict[str, float],
) -> dict:
    code5 = code4 + "0"

    # 財務諸表: このコードの行だけ抽出
    code_col = next((c for c in ["Code", "LocalCode"] if c in stmts_df.columns), None)
    if code_col:
        s = stmts_df[stmts_df[code_col].isin([code4, code5])].copy()
    else:
        s = pd.DataFrame()

    annual = _latest_annual(s) if not s.empty else pd.DataFrame()

    # 配当: fins/summaryのDivAnnを使う（fins/dividendはプラン制限のため）
    # fins/summaryの年次実績からDivAnn（年間配当）を抽出して配当履歴を再構築
    div_df_code = pd.DataFrame()
    if not annual.empty and "DivAnn" in annual.columns:
        div_records = []
        date_col = "CurPerEn" if "CurPerEn" in annual.columns else "DiscDate"
        for _, row in annual.iterrows():
            val = pd.to_numeric(row.get("DivAnn"), errors="coerce")
            dt  = row.get(date_col, "")
            if pd.notna(val) and val > 0 and dt:
                div_records.append({"RecordDate": str(dt), "AnnualDividendPerShare": float(val)})
        if div_records:
            div_df_code = pd.DataFrame(div_records)

    div_metrics = calc_dividend_metrics(div_df_code)

    # 株価（V2: AdjC=調整済み終値）
    close_price = None
    market_cap  = None
    if price_row is not None and not price_row.empty:
        close_price = float(price_row.get("AdjC") or price_row.get("C") or
                            price_row.get("AdjustmentClose") or 0) or None
        # 時価総額 = 終値 × 発行済株数（fins/summaryのShOutFYから取得）
        shares = None
        if not annual.empty and "ShOutFY" in annual.columns:
            sv = pd.to_numeric(annual["ShOutFY"], errors="coerce").dropna()
            if len(sv) > 0:
                shares = float(sv.iloc[-1])
        if shares and close_price:
            market_cap = shares * close_price

    beta = beta_map.get(code4) or beta_map.get(code5)
    fin_metrics = calc_financial_metrics(
        annual,
        close_price=close_price,
        market_cap=market_cap,
        annual_div_per_share=div_metrics.get("annual_dividend_per_share"),
        beta=beta,
    )

    return {**div_metrics, **fin_metrics}


# ── メインエントリポイント ────────────────────────────────────────
def fetch_all_jquants(
    codes:   list[str],
    client:  JQuantsClient,
    refresh: bool = False,
) -> pd.DataFrame:
    """全銘柄の指標を一括取得してDataFrameで返す。
    yfinance版 fetch_all() と同じ列構成を返す。

    所要時間の目安:
      初回（API取得）: 2〜5分（一括ダウンロード）
      2回目以降:       数秒（キャッシュ）
    """
    t0 = time.time()
    print("=== J-Quants 一括取得開始 ===", flush=True)

    stmts_df = _fetch_statements(client, refresh)
    div_df   = _fetch_dividends(client, refresh)
    price_df = _fetch_prices(client, refresh)

    print(f"データ取得完了: {time.time()-t0:.1f}秒", flush=True)

    # 株価をコードでインデックス化
    price_map: dict[str, pd.Series] = {}
    if not price_df.empty:
        p_code_col = next((c for c in ["Code", "LocalCode"] if c in price_df.columns), None)
        if p_code_col:
            for _, row in price_df.iterrows():
                c = str(row[p_code_col])
                price_map[c] = row
                price_map[_norm_code(c)] = row

    # Betaは現時点ではデフォルト（J-Quantsにbetaなし）
    beta_map: dict[str, float] = {}

    print(f"指標計算中 ({len(codes)}件)...", flush=True)
    rows = []
    for i, code in enumerate(codes):
        price_row = price_map.get(code) or price_map.get(code + "0")
        metrics   = _calc_one(code, stmts_df, div_df, price_row, beta_map)
        rows.append({"code": code, **metrics})
        if (i + 1) % 500 == 0:
            print(f"  [{i+1}/{len(codes)}] {(i+1)/len(codes)*100:.0f}%", flush=True)

    elapsed = time.time() - t0
    print(f"=== 完了: {elapsed:.1f}秒 ({elapsed/60:.1f}分) ===", flush=True)
    return pd.DataFrame(rows)
