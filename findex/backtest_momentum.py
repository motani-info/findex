"""
モメンタムスコアの回帰検証

「過去時点でのモメンタムスコア」と「その後のリターン」の相関を測定する。

手法:
  1. DBからサンプル銘柄を取得
  2. yfinance で 25ヶ月分の月次株価を取得
  3. 基準日 = 12ヶ月前 として、その時点のモメンタムスコアを計算
  4. その後 12ヶ月のリターンと相関を算出
  5. 複数ルールセット（V1〜V3）を比較

改善の考え方:
  V1（現行）: 12Mリターンをそのままスコア化 → 過熱株を捕まえる逆効果
  V2（修正）: 12Mに upper_cap を設定 + 3M を重視 → 過熱を除外
  V3（加速度）: 12Mリターンを廃止し「3M加速度」を導入
               accel = ret_3m / (ret_12m/4 + ε) → 最近の勢いが加速しているか
"""
from __future__ import annotations

import sqlite3
import time
from typing import Optional

import pandas as pd
import yfinance as yf

DB_PATH = "/Users/motani/.findex/db/findex.db"

# ── ルールセット定義 ────────────────────────────────────────────────────

# V1: 現行ルール
RULES_V1 = [
    {"name": "12Mリターン",  "field": "ret_12m",    "threshold": 0.30, "weight": 2.0, "upper_cap": None},
    {"name": "3Mリターン",   "field": "ret_3m",     "threshold": 0.15, "weight": 1.5, "upper_cap": None},
    {"name": "52週高値比率", "field": "hi52_ratio", "threshold": 0.90, "weight": 1.5, "upper_cap": None},
    {"name": "売上成長率",   "field": "rev_growth", "threshold": 0.20, "weight": 2.0, "upper_cap": None},
    {"name": "EPS成長率",    "field": "eps_growth", "threshold": 0.20, "weight": 2.0, "upper_cap": None},
]

# V2: 12Mに upper_cap（過熱カット）+ 3M 重視
# 根拠: 12M+60%超は過熱ゾーン、3Mが事後リターンと無相関のためより純粋な短期モメンタム
RULES_V2 = [
    {"name": "12Mリターン",  "field": "ret_12m",    "threshold": 0.20, "weight": 1.0, "upper_cap": 0.60},
    {"name": "3Mリターン",   "field": "ret_3m",     "threshold": 0.10, "weight": 2.5, "upper_cap": 0.40},
    {"name": "52週高値比率", "field": "hi52_ratio", "threshold": 0.85, "weight": 2.0, "upper_cap": None},
    {"name": "売上成長率",   "field": "rev_growth", "threshold": 0.15, "weight": 2.0, "upper_cap": None},
    {"name": "EPS成長率",    "field": "eps_growth", "threshold": 0.15, "weight": 2.0, "upper_cap": None},
]

# V3: 加速度モデル（12M廃止、3M加速度を導入）
# accel = ret_3m / (ret_12m / 4 + 0.01)  → 直近3Mが12M平均四半期より強いか
# 高値比率も「高値から落ちていない」= ブレイクアウト状態として重視
RULES_V3 = [
    {"name": "3M加速度",     "field": "accel",      "threshold": 1.50, "weight": 3.0, "upper_cap": 5.0},
    {"name": "3Mリターン",   "field": "ret_3m",     "threshold": 0.10, "weight": 2.0, "upper_cap": 0.40},
    {"name": "52週高値比率", "field": "hi52_ratio", "threshold": 0.90, "weight": 2.0, "upper_cap": None},
    {"name": "売上成長率",   "field": "rev_growth", "threshold": 0.15, "weight": 2.0, "upper_cap": None},
    {"name": "EPS成長率",    "field": "eps_growth", "threshold": 0.15, "weight": 2.0, "upper_cap": None},
]

ALL_RULE_SETS = {
    "V1（現行）": RULES_V1,
    "V2（過熱カット）": RULES_V2,
    "V3（加速度）": RULES_V3,
}


def _score_one(val: float | None, threshold: float, weight: float,
               upper_cap: float | None) -> float:
    if val is None or (isinstance(val, float) and val != val):
        return 0.0
    if threshold == 0:
        return 0.0
    # upper_cap: 上限を超えたら0点（過熱ペナルティ）
    if upper_cap is not None and val > upper_cap:
        return 0.0
    return round(min(10.0, max(0.0, val / threshold * 10)), 4)


def _calc_score(fields: dict, rules: list) -> float:
    max_w = sum(r["weight"] * 10 for r in rules)
    weighted_sum = sum(
        _score_one(fields.get(r["field"]), r["threshold"], r["weight"], r["upper_cap"])
        * r["weight"]
        for r in rules
    )
    return round(weighted_sum / max_w * 100, 2) if max_w > 0 else 0.0


def spearman(a: list, b: list) -> float:
    df = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(df) < 10:
        return float("nan")
    return round(float(df["a"].rank().corr(df["b"].rank())), 4)


def run_momentum_backtest(
    sample_n: int = 200,
    lookback_months: int = 12,
    forward_months: int = 12,
    market: Optional[str] = None,
    sector: Optional[str] = None,
    out: Optional[str] = None,
) -> None:
    import click

    click.echo(f"\n{'━'*72}")
    click.echo(f" モメンタムスコア 回帰検証（マルチバージョン比較）")
    click.echo(f" 基準日: {lookback_months}ヶ月前  事後期間: {forward_months}ヶ月")
    click.echo(f"{'━'*72}\n")

    # ── 1. サンプル銘柄取得 ───────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    where = ["s.rowid IN (SELECT MAX(rowid) FROM scores GROUP BY code)"]
    if market:
        where.append(f"st.market LIKE '%{market}%'")
    if sector:
        where.append(f"st.sector LIKE '%{sector}%'")

    rows = conn.execute(f"""
        SELECT s.code, st.name,
               json_extract(s.raw_json, '$.revenue_growth_5y_cagr') as rev_growth,
               json_extract(s.raw_json, '$.eps_growth_5y') as eps_growth
        FROM scores s
        JOIN stocks st ON s.code = st.code
        WHERE {' AND '.join(where)}
        ORDER BY RANDOM()
        LIMIT {sample_n * 2}
    """).fetchall()
    conn.close()

    if not rows:
        click.echo("候補銘柄なし")
        return

    codes = [r[0] for r in rows]
    fund_map = {r[0]: {"rev_growth": r[2], "eps_growth": r[3]} for r in rows}
    click.echo(f"候補 {len(codes)}銘柄から株価データ取得中...")

    # ── 2. 月次株価取得 ───────────────────────────────────────────
    price_store: dict[str, pd.Series] = {}
    BATCH = 100
    for i in range(0, len(codes), BATCH):
        batch_codes = codes[i:i + BATCH]
        tickers = [f"{c}.T" for c in batch_codes]
        try:
            raw = yf.download(tickers, period="3y", interval="1mo",
                              auto_adjust=True, progress=False, threads=False)
            if raw.empty:
                continue
            close = raw["Close"] if "Close" in raw.columns else raw
            if isinstance(close, pd.Series):
                close = close.to_frame(name=tickers[0])
            for ticker in tickers:
                code = ticker.replace(".T", "")
                if ticker not in close.columns:
                    continue
                col = close[ticker].dropna()
                if len(col) >= lookback_months + forward_months // 2:
                    price_store[code] = col
        except Exception as e:
            click.echo(f"  バッチエラー: {e}")
        if i + BATCH < len(codes):
            time.sleep(5)
        click.echo(f"  {min(i+BATCH, len(codes))}/{len(codes)}件 (価格あり: {len(price_store)}件)")

    click.echo(f"\n価格データ取得完了: {len(price_store)}銘柄")

    # ── 3. 各銘柄のフィールド計算 ────────────────────────────────
    records = []
    for code, price_series in price_store.items():
        price_series = price_series.sort_index()
        n = len(price_series)

        base_idx = n - lookback_months - 1
        if base_idx < 3:
            continue

        base_price = float(price_series.iloc[base_idx])
        current_price = float(price_series.iloc[-1])
        forward_ret = current_price / base_price - 1

        # 12Mリターン（基準日の1年前→基準日）
        if base_idx >= 12:
            ret_12m = base_price / float(price_series.iloc[base_idx - 12]) - 1
        else:
            ret_12m = None

        # 3Mリターン
        ret_3m = base_price / float(price_series.iloc[base_idx - 3]) - 1 if base_idx >= 3 else None

        # 52週高値比率
        window = price_series.iloc[max(0, base_idx - 12): base_idx + 1]
        hi52 = float(window.max())
        hi52_ratio = base_price / hi52 if hi52 > 0 else None

        # 加速度: 直近3Mが12M平均四半期より強いか
        accel = None
        if ret_12m is not None and ret_3m is not None:
            avg_q = ret_12m / 4 + 0.01  # ε で0除算防止
            accel = ret_3m / avg_q

        fund = fund_map.get(code, {})
        fields = {
            "ret_12m":    ret_12m,
            "ret_3m":     ret_3m,
            "hi52_ratio": hi52_ratio,
            "accel":      accel,
            "rev_growth": fund.get("rev_growth"),
            "eps_growth": fund.get("eps_growth"),
        }
        records.append({"code": code, "forward_ret": forward_ret, **fields})

    if len(records) < 20:
        click.echo("検証可能な銘柄が少なすぎます")
        return

    df = pd.DataFrame(records)
    click.echo(f"検証銘柄数: {len(df)}件\n")

    # ── 4. 各ルールセットのスコア計算・比較 ──────────────────────
    summary_rows = []
    for version, rules in ALL_RULE_SETS.items():
        df[f"score_{version}"] = df.apply(lambda r: _calc_score(r.to_dict(), rules), axis=1)

    click.echo(f"{'─'*72}")
    click.echo(f" {'バージョン':<16}  {'ρ(総合)':>8}  {'Q1avg':>7}  {'Q2avg':>7}  {'Q3avg':>7}  {'Q4avg':>7}  {'TOP-BOT':>8}")
    click.echo(f"{'─'*72}")

    best_version = None
    best_rho = -99.0

    for version, rules in ALL_RULE_SETS.items():
        score_col = f"score_{version}"
        scores = df[score_col].tolist()
        fwd = df["forward_ret"].tolist()
        rho = spearman(scores, fwd)

        # 四分位
        df_s = df.sort_values(score_col)
        n = len(df_s)
        q = n // 4
        q_avgs = [
            df_s.iloc[:q]["forward_ret"].mean() * 100,
            df_s.iloc[q:2*q]["forward_ret"].mean() * 100,
            df_s.iloc[2*q:3*q]["forward_ret"].mean() * 100,
            df_s.iloc[3*q:]["forward_ret"].mean() * 100,
        ]
        top_bot = (df_s.nlargest(20, score_col)["forward_ret"].mean()
                   - df_s.nsmallest(20, score_col)["forward_ret"].mean()) * 100

        click.echo(
            f" {version:<16}  {rho:>+8.3f}  "
            f"{q_avgs[0]:>+6.1f}%  {q_avgs[1]:>+6.1f}%  "
            f"{q_avgs[2]:>+6.1f}%  {q_avgs[3]:>+6.1f}%  {top_bot:>+7.1f}%"
        )
        summary_rows.append({"version": version, "rho": rho, "top_bot": top_bot, "q4_avg": q_avgs[3]})

        if rho > best_rho:
            best_rho = rho
            best_version = version

    click.echo(f"{'─'*72}")
    click.echo(f"\n✅ 最良バージョン: {best_version}  ρ = {best_rho:+.3f}\n")

    # ── 5. 最良バージョンの詳細 ──────────────────────────────────
    click.echo(f"【{best_version} 詳細分析】")
    score_col = f"score_{best_version}"
    df_s = df.sort_values(score_col)
    n = len(df_s)
    q = n // 4

    click.echo(f"\n  四分位分析（各 {q}銘柄）:")
    click.echo(f"  {'区分':<10}  {'スコア範囲':>14}  {'平均リターン':>12}  {'中央値':>8}  {'プラス率':>8}")
    click.echo(f"  {'─'*56}")
    labels = ["Q1（低）", "Q2", "Q3", "Q4（高）"]
    for qi, label in enumerate(labels):
        qdf = df_s.iloc[qi*q:(qi+1)*q]
        avg = qdf["forward_ret"].mean() * 100
        med = qdf["forward_ret"].median() * 100
        pos = (qdf["forward_ret"] > 0).mean() * 100
        smin = qdf[score_col].min()
        smax = qdf[score_col].max()
        click.echo(f"  {label:<10}  {smin:>5.1f}〜{smax:>5.1f}点  {avg:>+11.1f}%  {med:>+7.1f}%  {pos:>7.1f}%")

    # 各指標単体のρ
    click.echo(f"\n  指標単体のρ:")
    for field in ["ret_12m", "ret_3m", "accel", "hi52_ratio", "rev_growth", "eps_growth"]:
        rho_f = spearman(df[field].tolist(), df["forward_ret"].tolist())
        if not (rho_f != rho_f):  # NaN check
            click.echo(f"    {field:<16}: {rho_f:>+.3f}")

    click.echo(f"\n  全体平均リターン: {df['forward_ret'].mean()*100:+.1f}%  "
               f"プラス率: {(df['forward_ret']>0).mean()*100:.1f}%")
    click.echo(f"\n{'━'*72}\n")

    # ── 6. CSV出力 ────────────────────────────────────────────────
    if out:
        out_df = df[["code", "forward_ret", "ret_12m", "ret_3m", "accel", "hi52_ratio"]].copy()
        for version in ALL_RULE_SETS:
            out_df[f"score_{version}"] = df[f"score_{version}"]
        out_df.to_csv(out, index=False, encoding="utf-8-sig")
        click.echo(f"CSV保存: {out}")
