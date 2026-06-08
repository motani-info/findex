"""Category A 毎日更新: 株価系フィールドのみ再取得・再スコア
yf.download() で全銘柄の終値を1リクエストで取得し、
SQLite の EPS/BPS/annual_div からローカル計算する。
所要時間: 1〜2分
"""
from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import yfinance as yf

from findex.db import (
    get_db, get_fundamentals, get_latest_raw_json,
    upsert_score_with_raw, get_or_create_rule_version,
    upsert_stocks, bulk_insert_price_history,
)
from findex.scorer.engine import load_rules, select_rules, score_one

DEFAULT_RULES = Path(__file__).parent.parent.parent / "rules.yaml"


def _safe_val(v) -> float | None:
    """NaN/None/inf を除去して float を返す"""
    try:
        f = float(v)
        return f if pd.notna(f) and abs(f) < 1e18 else None
    except (TypeError, ValueError):
        return None


def _calc_price_fields(close: float, fund: dict) -> dict:
    """終値 + stock_fundamentals から Category A フィールドを計算する。"""
    eps        = _safe_val(fund.get("eps"))
    bps        = _safe_val(fund.get("bps"))
    shares     = _safe_val(fund.get("shares"))
    annual_div = _safe_val(fund.get("annual_div"))
    net_cash   = _safe_val(fund.get("net_cash"))

    per = round(close / eps, 4) if eps and eps > 0 and close > 0 else None
    pbr = round(close / bps, 4) if bps and bps > 0 and close > 0 else None
    market_cap = int(shares * close) if shares and shares > 0 and close > 0 else None

    div_yield = None
    if annual_div and annual_div > 0 and close > 0:
        y = annual_div / close
        div_yield = round(y, 6) if 0 < y <= 0.30 else None

    mix_coefficient = round(per * pbr, 4) if per and pbr and per > 0 and pbr > 0 else None

    net_cash_per = None
    if per and net_cash is not None and market_cap and market_cap > 0:
        result = per * (1 - net_cash / market_cap)
        net_cash_per = round(result, 4) if -500 < result < 500 else None

    return {
        "per":             per,
        "pbr":             pbr,
        "market_cap":      market_cap,
        "div_yield":       div_yield,
        "mix_coefficient": mix_coefficient,
        "net_cash_per":    net_cash_per,
    }


def run_backfill(
    period: str = "2y",
    codes: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """
    過去株価履歴の一括取得・DB保存（初回または年1回想定）。

    フロー:
      1. yf.download(all_codes, period=period, interval='1d') で日次終値を一括取得
      2. price_history テーブルに INSERT OR IGNORE で保存（既存レコードは上書きしない）

    Args:
      period: yfinance の期間指定（"1y", "2y", "5y" など）
      codes:  対象銘柄リスト（None の場合は stock_fundamentals の全銘柄）
      dry_run: True の場合はDBへの書き込みをしない

    Returns:
      {"inserted": int, "skipped": int, "failed": int, "elapsed_sec": float}
    """
    import time
    t0 = time.time()

    conn = get_db()

    if codes is None:
        fund_df = get_fundamentals(conn)
        codes = fund_df["code"].tolist()

    if not codes:
        print("対象銘柄なし（stock_fundamentals が空）", flush=True)
        conn.close()
        return {"inserted": 0, "skipped": 0, "failed": 0, "elapsed_sec": 0}

    # TOPIXベンチマーク（1306）を先頭に追加（モメンタム相対リターン計算に必要）
    benchmark = ["1306"]
    all_codes  = benchmark + [c for c in codes if c not in benchmark]
    tickers    = [f"{c}.T" for c in all_codes]

    BATCH = 200
    total = len(tickers)
    total_inserted = 0
    total_failed = 0

    print(f"過去株価取得中: {total}銘柄（TOPIXベンチマーク含む） × {period} ({(total+BATCH-1)//BATCH}バッチ)...", flush=True)

    for i in range(0, total, BATCH):
        batch_tickers = tickers[i:i+BATCH]
        try:
            raw = yf.download(
                batch_tickers, period=period, interval="1d",
                auto_adjust=True, progress=False, threads=False,
            )
            if raw.empty:
                print(f"  バッチ{i//BATCH+1}: データなし", flush=True)
                total_failed += len(batch_tickers)
                continue

            close_df  = raw["Close"]  if "Close"  in raw.columns else raw
            volume_df = raw["Volume"] if "Volume" in raw.columns else None
            if isinstance(close_df, pd.Series):
                close_df = close_df.to_frame(name=batch_tickers[0])
            if volume_df is not None and isinstance(volume_df, pd.Series):
                volume_df = volume_df.to_frame(name=batch_tickers[0])

            records: list[tuple] = []
            for ticker in batch_tickers:
                code = ticker.replace(".T", "")
                if ticker not in close_df.columns:
                    continue
                c_col = close_df[ticker].dropna()
                v_col = volume_df[ticker] if (volume_df is not None and ticker in volume_df.columns) else None
                for dt, price in c_col.items():
                    if pd.notna(price) and float(price) > 0:
                        vol = None
                        if v_col is not None and dt in v_col.index and pd.notna(v_col[dt]):
                            vol = int(v_col[dt])
                        records.append((code, str(dt.date()), float(price), vol))

            if records and not dry_run:
                bulk_insert_price_history(conn, records)
                conn.commit()

            inserted = len(records)
            total_inserted += inserted
            print(f"  バッチ{i//BATCH+1}: {inserted}件保存（volume含む）", flush=True)

        except Exception as e:
            print(f"  バッチ{i//BATCH+1} エラー: {e}", flush=True)
            total_failed += len(batch_tickers)

        if i + BATCH < total:
            time.sleep(5)

    conn.close()
    elapsed = time.time() - t0
    print(
        f"バックフィル完了: inserted={total_inserted} failed={total_failed} elapsed={elapsed:.1f}s",
        flush=True,
    )
    return {"inserted": total_inserted, "skipped": 0, "failed": total_failed, "elapsed_sec": elapsed}


def run_daily_update(
    rules_path: Path = DEFAULT_RULES,
    codes: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """
    毎日更新メイン処理。

    フロー:
      1. yf.download(all_codes, period='2d') → 全銘柄終値を一括取得
      2. SQLite stock_fundamentals から EPS/BPS/shares/annual_div を取得
      3. Category A フィールドをローカル計算
      4. SQLite raw_json の Category A フィールドを上書き
      5. 再スコアリング → SQLite upsert

    Returns:
      {"updated": int, "skipped": int, "failed": int, "elapsed_sec": float}
    """
    import time
    t0 = time.time()

    conn       = get_db()
    rules      = load_rules(rules_path)
    rule_ver   = get_or_create_rule_version(conn, rules_path)
    today      = date.today().isoformat()
    now_iso    = datetime.now().isoformat(timespec="seconds")

    # 対象銘柄
    if codes is None:
        fund_df = get_fundamentals(conn)
        codes   = fund_df["code"].tolist()
    else:
        fund_df = get_fundamentals(conn, codes)

    if not codes:
        print("対象銘柄なし（stock_fundamentals が空）", flush=True)
        return {"updated": 0, "skipped": 0, "failed": 0, "elapsed_sec": 0}

    # ── Step 1: 全銘柄の終値・出来高を一括取得 ─────────────────────
    import time
    # TOPIXベンチマーク（1306）を先頭に追加（モメンタム相対リターン計算に必要）
    benchmark     = ["1306"]
    all_codes_ext = benchmark + [c for c in codes if c not in benchmark]
    tickers       = [f"{c}.T" for c in all_codes_ext]
    BATCH         = 200
    price_map:  dict[str, float] = {}
    volume_map: dict[str, int]   = {}
    total_tickers = len(tickers)
    print(f"株価一括取得中: {total_tickers}銘柄（TOPIXベンチマーク含む） ({(total_tickers+BATCH-1)//BATCH}バッチ)...", flush=True)

    for i in range(0, total_tickers, BATCH):
        batch = tickers[i:i+BATCH]
        try:
            raw = yf.download(batch, period="2d", auto_adjust=True,
                              progress=False, threads=False)
            if raw.empty or len(raw) == 0:
                print(f"  バッチ{i//BATCH+1}: データなし（レートリミットの可能性）", flush=True)
            else:
                close_df  = raw["Close"]  if "Close"  in raw.columns else raw
                volume_df = raw["Volume"] if "Volume" in raw.columns else None
                if isinstance(close_df, pd.Series):
                    close_df = close_df.to_frame(name=batch[0])
                if volume_df is not None and isinstance(volume_df, pd.Series):
                    volume_df = volume_df.to_frame(name=batch[0])
                close_row  = close_df.iloc[-1]
                volume_row = volume_df.iloc[-1] if volume_df is not None else None
                got = 0
                for ticker, price in close_row.items():
                    code_t = str(ticker).replace(".T", "")
                    if pd.notna(price) and float(price) > 0:
                        price_map[code_t] = float(price)
                        if volume_row is not None and ticker in volume_row.index and pd.notna(volume_row[ticker]):
                            volume_map[code_t] = int(volume_row[ticker])
                        got += 1
                print(f"  バッチ{i//BATCH+1}: {got}/{len(batch)}件取得", flush=True)
        except Exception as e:
            print(f"  バッチ{i//BATCH+1} エラー: {e}", flush=True)
        if i + BATCH < total_tickers:
            time.sleep(10)

    print(f"株価取得完了: {len(price_map)}件 / {total_tickers}件", flush=True)
    if len(price_map) == 0:
        return {"updated": 0, "skipped": 0, "failed": len(codes), "elapsed_sec": time.time()-t0}

    # ── price_history に今日分を保存（close + volume）─────────────
    if not dry_run:
        ph_records = [
            (code, today, price, volume_map.get(code))
            for code, price in price_map.items()
        ]
        bulk_insert_price_history(conn, ph_records)
        conn.commit()
        print(f"price_history 保存: {len(ph_records)}件（volume付き）", flush=True)

    # ── Step 2: stock_fundamentals を辞書化 ─────────────────────
    fund_map: dict[str, dict] = {}
    for _, row in fund_df.iterrows():
        fund_map[str(row["code"])] = row.to_dict()

    # ── Step 3〜5: 計算・スコアリング・保存 ─────────────────────
    raw_json_map = get_latest_raw_json(conn)

    updated = skipped = failed = 0
    for code in codes:
        close = price_map.get(code)
        if not close:
            skipped += 1
            continue

        fund   = fund_map.get(code, {})
        raw    = dict(raw_json_map.get(code, {}))

        # Category A を上書き
        price_fields = _calc_price_fields(close, fund)
        raw.update(price_fields)
        if not dry_run and price_fields.get("market_cap") is not None:
            conn.execute(
                "UPDATE stock_fundamentals SET market_cap = ? WHERE code = ?",
                (price_fields["market_cap"], code),
            )
        # Category B/C は stock_fundamentals から補完（raw_jsonにない場合）
        for col in [
            "equity_ratio", "debt_to_equity", "roe", "operating_margin",
            "eps_growth_5y", "revenue_growth_5y_cagr", "roic_minus_wacc",
            "fcf_payout_coverage", "retained_earnings_div_ratio", "payout_ratio",
            "consecutive_no_cut_years", "consecutive_dividend_growth_years",
            "dividend_growth_5y_cagr", "dividend_growth_10y_cagr",
            "dividend_reliability", "annual_div",
        ]:
            if col in fund and fund[col] is not None:
                raw.setdefault(col, fund[col])

        try:
            sector     = raw.get("sector")
            active     = select_rules(rules, raw.get("market_cap"), sector)
            score_j    = score_one(raw, active)

            if not dry_run:
                upsert_score_with_raw(
                    conn, code, today, rule_ver,
                    score_j, raw,
                    price_updated_at=now_iso,
                )
            updated += 1
        except Exception:
            failed += 1

    if not dry_run:
        conn.commit()
    conn.close()

    elapsed = time.time() - t0
    print(
        f"日次更新完了: updated={updated} skipped={skipped} failed={failed} "
        f"elapsed={elapsed:.1f}s",
        flush=True,
    )
    return {"updated": updated, "skipped": skipped, "failed": failed, "elapsed_sec": elapsed}
