# 実行計画：株式分割基準ズレの根本治療

## 背景

- yfinance `close_adj` は全期間遡及的に分割調整済み（分割後基準）
- J-Quants `EPS/BPS/shares_outstanding` は決算短信の報告値そのまま（分割前基準）
- 決算as_of以降に分割が起きた銘柄で PER/PBR/配当利回り/時価総額が壊れる
- **影響範囲: 推定184銘柄（全体の5%）。低PER帯はほぼ全て汚染**
- yfinance `.splits` で分割イベント（日付＋比率）が正確に取得できることを実証済み

## 方針

derive層（compute_price_metrics_for_code）で EPS/BPS/shares を使う時点で、
**as_of以降に発生した分割の累積係数で調整**してからPER/PBR/時価総額を算出する。

DB（financial_snapshots）の生値は触らない（報告値のまま保持＝出典明示の原則）。
分割情報はsplitsテーブルに保存し、derive時に動的に補正する。

## 実装ステップ

### Step 1: splitsテーブル新設

```sql
CREATE TABLE IF NOT EXISTS stock_splits (
    code  TEXT NOT NULL,
    date  TEXT NOT NULL,   -- 分割効力日 (YYYY-MM-DD)
    ratio REAL NOT NULL,   -- 分割比率（例: 15.0 = 1:15分割）
    source TEXT NOT NULL DEFAULT 'yfinance',
    collected_at TEXT NOT NULL,
    PRIMARY KEY (code, date)
);
```

ファイル: `findex/db.py`（initdb）に追加

### Step 2: findex splits コマンド新設（fetch層）

`findex/fetch/splits.py` 新設:
- yfinance `.splits` から全銘柄の分割イベントを取得
- `stock_splits` テーブルに UPSERT
- Fetcher基底は使わず軽量実装（splitsはAPI制限が緩い・全銘柄一括でも軽い）

`findex/cli.py` に `splits` コマンド追加:
```
findex splits --all          # 全銘柄
findex splits --codes 2146   # 個別
findex splits --cohort       # コホート
```

### Step 3: derive層の分割調整ヘルパー

`findex/derive/compute.py` に追加:

```python
def _split_adjustment_factor(conn, code: str, as_of: str) -> float:
    """as_of以降に発生した分割の累積比率を返す。分割なければ1.0。"""
    rows = conn.execute(
        "SELECT ratio FROM stock_splits WHERE code=? AND date>?",
        (code, as_of),
    ).fetchall()
    factor = 1.0
    for (r,) in rows:
        factor *= r
    return factor
```

### Step 4: compute_price_metrics_for_code を改修

既存:
```python
eps, bps, shares, ... = fin
```

改修後:
```python
eps, bps, shares, ... = fin
# 分割調整: 財務as_of以降の分割でEPS/BPS/sharesの基準がclose_adjと乖離する場合を補正
factor = _split_adjustment_factor(conn, code, as_of)
if factor != 1.0:
    if eps is not None: eps = eps / factor
    if bps is not None: bps = bps / factor
    if shares is not None: shares = shares * factor
```

影響するのは price_metrics のみ。financial由来指標（ROE/配当性向/DOE等）は
EPS/BPSの絶対値を使わない（比率計算 or equity/net_income直接）ため影響なし。

### Step 5: テスト

`tests/test_split_adjustment.py` 新設:
- `_split_adjustment_factor`: 分割なし=1.0 / 1件=ratio / 複数=累積
- `compute_price_metrics_for_code`: 分割ありの銘柄でPER/PBRが補正される

既存テスト: 全94 passed を死守

### Step 6: 実行・検収

```bash
findex splits --all           # 分割イベント取得（全銘柄・推定10-20分）
findex derive --what prices --all  # 価格指標再計算（分割補正適用）
pytest -q                     # 回帰テスト
findex verify --all           # golden 18/18 死守
findex post-gallery --all     # posts.html 再生成 → 外れ値消失を目視
```

### Step 7: doc10調査ファイル更新＋ナレッジメモ更新

## ファイル変更一覧

| ファイル | 変更 |
|---------|------|
| `findex/db.py` | stock_splits テーブル DDL 追加 |
| `findex/fetch/splits.py` | **新設** — SplitsFetcher |
| `findex/cli.py` | `splits` コマンド追加 |
| `findex/derive/compute.py` | `_split_adjustment_factor` 追加 + price_metrics 改修 |
| `tests/test_split_adjustment.py` | **新設** — 回帰テスト |

## 注意事項

- **financial_snapshotsの生値は書き換えない**（報告値を保持＝出典明示・再取得時に差分検知可能）
- 分割調整はderive時のみ動的適用。score/backtest/verify等の下流は PER/PBR 経由なので自動追従
- `findex update` に `splits` を組み込む（毎回の更新で自動的に最新分割を取得）
- 配当DPS（yfinance events）は既に分割調整済み → 補正不要
- EPS growth（5年CAGR）は financial_snapshots の複数年EPSを使う → 要検討
  - ただし異なるfiscal_year間のEPSは各年の報告基準で揃っている（各年のas_of時点ではまだ分割前）
  - → 同一基準内の比率計算なので**CAGR計算に影響なし**（今年と5年前が同じ分割前基準）
  - 影響があるのは「最新EPS vs 現在株価」の比較（=PER）のみ ← これを修正する

## 工数見積

| ステップ | 時間 |
|---------|------|
| Step 1-4 実装 | 1h |
| Step 5 テスト | 30min |
| Step 6 全銘柄実行・検収 | 20-30min（splits取得時間依存） |
| 合計 | 約2h |
