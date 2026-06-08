"""10年配当履歴から増配継続見込み銘柄をランキングする"""
import json
import pandas as pd
from pathlib import Path

CACHE_DIR = Path.home() / ".findex" / "cache"
CSV_PATH  = Path("findex_all_20260601.csv")

def _fiscal_year(date) -> int:
    return date.year if date.month >= 4 else date.year - 1

def load_dividend_history(code: str) -> dict | None:
    p = CACHE_DIR / "dividends" / f"{code}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())["data"]
    except Exception:
        return None

def calc_10y_metrics(code: str) -> dict:
    """キャッシュの集計済みデータを使いつつ、10年CAGRは別途計算"""
    # dividendsキャッシュはすでに集計済み指標のみ保存 → 生データはない
    # fundamentalsキャッシュからdividendRateを使うしかない
    # → 代わりにCSVのno_cut_years / growth_yearsを使い、スコアを組み合わせる
    return {}

def main():
    df = pd.read_csv(CSV_PATH)
    print(f"総銘柄数: {len(df)}")

    # 利用可能なカラム確認
    div_cols = [c for c in df.columns if "div" in c.lower() or "consec" in c.lower() or "cagr" in c.lower()]
    print(f"配当関連カラム: {div_cols}")

    # --- フィルタ条件 ---
    # 1. 配当利回り 1%以上
    # 2. 連続非減配 5年以上（10年データの最低ライン）
    # 3. 配当性向 80%以下（持続可能）

    df_filt = df.copy()
    df_filt = df_filt[df_filt["div_yield"].notna() & (df_filt["div_yield"] >= 0.01)]
    df_filt = df_filt[df_filt["consecutive_no_cut_years"] >= 5]
    df_filt = df_filt[df_filt["payout_ratio"].isna() | (df_filt["payout_ratio"] <= 0.80)]

    print(f"\nフィルタ後: {len(df_filt)}銘柄")

    # --- 増配継続スコア（将来増配見込み指標）---
    # 考え方: 長期非減配 × 増配継続年数 × 増配CAGR × 財務健全性（余力）
    df_filt = df_filt.copy()

    # 正規化
    def norm(s):
        mn, mx = s.min(), s.max()
        return (s - mn) / (mx - mn) if mx > mn else s * 0

    # ①連続非減配年数（長期安定性の代理）
    no_cut_score = norm(df_filt["consecutive_no_cut_years"])

    # ②連続増配年数
    growth_score = norm(df_filt["consecutive_dividend_growth_years"])

    # ③5年CAGR（増配ペース）
    cagr_score = norm(df_filt["dividend_growth_5y_cagr"].fillna(0).clip(0, 0.20))

    # ④配当利回り（水準）
    yield_score = norm(df_filt["div_yield"].clip(0.01, 0.10))

    # ⑤財務余力（配当性向の逆数 = 増配余地）
    payout = df_filt["payout_ratio"].fillna(0.5).clip(0.01, 1.0)
    room_score = norm(1 - payout)

    # 総合スコア（ウェイト）
    df_filt["growth_prospect_score"] = (
        no_cut_score  * 3.0 +   # 長期継続性が最重要
        growth_score  * 2.5 +   # 増配継続年数
        cagr_score    * 2.0 +   # 増配ペース
        yield_score   * 1.5 +   # 利回り水準
        room_score    * 1.0     # 増配余地
    ) / 10.0 * 100

    df_filt = df_filt.sort_values("growth_prospect_score", ascending=False)

    # TOP30表示
    show_cols = [
        "code", "name", "sector",
        "consecutive_no_cut_years", "consecutive_dividend_growth_years",
        "dividend_growth_5y_cagr", "div_yield", "payout_ratio",
        "growth_prospect_score", "score"
    ]
    show_cols = [c for c in show_cols if c in df_filt.columns]

    top30 = df_filt[show_cols].head(30)

    pd.set_option("display.max_rows", 40)
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda x: f"{x:.3f}" if abs(x) < 1000 else f"{x:.0f}")

    print("\n=== 増配継続見込みTOP30 ===")
    print(top30.to_string(index=False))

    # 連続非減配年数の分布確認
    print("\n--- 連続非減配年数 分布（フィルタ後）---")
    print(df_filt["consecutive_no_cut_years"].describe())
    print("\n--- 連続増配年数 TOP値 ---")
    print(df_filt["consecutive_dividend_growth_years"].value_counts().head(10))

    # 10年以上連続増配の銘柄数
    n_10y = (df_filt["consecutive_no_cut_years"] >= 10).sum()
    n_15y = (df_filt["consecutive_no_cut_years"] >= 15).sum()
    n_20y = (df_filt["consecutive_no_cut_years"] >= 20).sum()
    print(f"\n10年以上連続非減配: {n_10y}銘柄")
    print(f"15年以上連続非減配: {n_15y}銘柄")
    print(f"20年以上連続非減配: {n_20y}銘柄")

    print("\n=== 連続増配20年以上の銘柄 ===")
    legend = df_filt[df_filt["consecutive_no_cut_years"] >= 20][show_cols]
    print(legend.to_string(index=False))

if __name__ == "__main__":
    main()
