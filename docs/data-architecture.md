# データアーキテクチャ（現状）

> 最終更新: 2026-06-06  
> 対象: findex データベース `~/.findex/db/findex.db`  
> ステータス: **3層分離リファクタリング完了**（旧テーブルは廃止待ち）

---

## 1. 概要

findex は日本株約3,747銘柄を対象に、2軸でスコアリングを行う:

| 軸 | 評価観点 | 指標数 |
|---|---|---|
| 配当スコア | 高配当株としての総合力（安定性・余力・割安度） | 14指標 |
| モメンタムスコア | 株価上昇トレンド・業績加速 | 8指標 |

---

## 2. 現行テーブル構成

### 2-1. テーブル一覧（新アーキテクチャ）

| テーブル | 行数 | レイヤー | 用途 | 状態 |
|---|---|---|---|---|
| `stocks` | 3,747 | Master | 銘柄マスター | ✅ 稼働中 |
| `price_history` | ~900,000 | Layer 1 | 日次終値・出来高 | ✅ 稼働中 |
| `dividend_history` | ~87,000 | Layer 1 | 配当金額（権利落ち日ベース） | ✅ 稼働中 |
| `raw_financials` | 3,745 | Layer 1 | yfinance生データ（加工なし） | ✅ 新設・稼働中 |
| `computed_metrics` | 3,746 | Layer 2 | 算出指標（Layer 1から計算） | ✅ 新設・稼働中 |
| `dividend_scores` | 3,746 | Layer 3 | 配当スコア（カラム展開） | ✅ 新設・稼働中 |
| `momentum_scores` | 3,746 | Layer 3 | モメンタムスコア（カラム展開） | ✅ 新設・稼働中 |
| `rule_versions` | 少数 | Meta | ルール定義のスナップショット | ✅ 稼働中 |
| `run_log` | 少数 | Meta | バッチ実行履歴 | ✅ 稼働中 |
| `schema_version` | 6 | Meta | マイグレーション管理 | ✅ 稼働中 |

### 2-2. レガシーテーブル（廃止予定）

| テーブル | 行数 | 問題 | 移行先 |
|---|---|---|---|
| `stock_fundamentals` | ~3,900 | 取得値と計算値が混在 | `raw_financials` + `computed_metrics` |
| `scores` | ~3,900/日 | JSONに全データ格納 | `dividend_scores` |

### 2-2. `stock_fundamentals` の内容分析

このテーブルには性質の異なる3種類のデータが混在している:

| 分類 | カラム例 | 取得元 | 性質 |
|---|---|---|---|
| **Web取得値（生データ）** | `eps`, `bps`, `shares`, `net_cash`, `roe`, `operating_margin`, `payout_ratio` | yfinance info / balance_sheet | 外部APIから直接取得した値 |
| **バッチ計算値** | `equity_ratio`, `debt_to_equity`, `eps_growth_5y`, `revenue_growth_5y_cagr`, `roic_minus_wacc`, `fcf_payout_coverage`, `retained_earnings_div_ratio` | 上記の生データから計算 | 算出ロジック依存 |
| **配当集計値** | `annual_div`, `consecutive_no_cut_years`, `consecutive_dividend_growth_years`, `dividend_growth_*_cagr`, `dividend_reliability` | dividend_historyから年次集計 | 算出ロジック依存 |

**問題**: 値がおかしい場合に「取得が壊れたのか」「計算が壊れたのか」を判別できない。

### 2-3. `scores` テーブルの内容分析

```sql
-- 配当スコアのみ保存。モメンタムスコアは保存されない。
total_score  = 78.5                    -- 配当スコア合計
score_json   = '{"raw":{...},...}'     -- 指標別スコア（JSON文字列）
raw_json     = '{"eps":150,"per":12.5,"div_yield":0.035,...}'  -- 全生データ（JSON文字列）
```

**問題**:
- 個別スコアにアクセスするには毎回 `json_extract()` が必要
- SQLでのフィルタ・ソートが非効率
- モメンタムスコアの保存先が存在しない

---

## 3. 現行データフロー

### 3-1. 新パイプライン（`findex pipeline`）— 現在のメイン

```
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: findex fetch quarterly  (四半期・手動)                   │
│    yfinance info/financials/balance_sheet → raw_financials       │
│    ※ 生データのみ保存。計算しない                                 │
├─────────────────────────────────────────────────────────────────┤
│  Step 2: findex compute  (毎日自動 via launchd)                  │
│    raw_financials + price_history + dividend_history             │
│      → computed_metrics（PER/PBR/利回り/成長率/リターン等）       │
├─────────────────────────────────────────────────────────────────┤
│  Step 3: findex score dividend + findex score momentum           │
│    computed_metrics + rules.yaml → dividend_scores              │
│    computed_metrics + price_history → momentum_scores            │
└─────────────────────────────────────────────────────────────────┘

日次自動実行: launchd（平日18:00）
  スクリプト: scripts/daily.sh
  設定: ~/Library/LaunchAgents/com.findex.daily.plist
  内容: findex update (株価取得) → findex compute → findex score dividend → findex score momentum
```

### 3-2. 旧バッチ（まだ動作する）

```
findex update                     → price_history + scores（旧テーブル）
findex update --quarterly         → stock_fundamentals（旧テーブル）
findex update --dividends         → dividend_history + stock_fundamentals配当集計
```

### 3-3. API参照（新アーキテクチャ）

```
/api/dividend/rank   → dividend_scores JOIN stock_fundamentals JOIN stocks（SELECT のみ）
/api/dividend/check  → dividend_scores JOIN computed_metrics JOIN raw_financials JOIN stocks（raw フィールド付き）
/api/momentum/rank   → momentum_scores JOIN computed_metrics JOIN stock_fundamentals JOIN stocks（ret_12m, ret_3m, rel_ret_12m, rel_ret_3m, hi52_ratio 実数値付き）
/api/momentum/check  → momentum_scores JOIN computed_metrics JOIN stocks（fields フィールド付き, div_score 付き）
/api/stock/search    → stocks JOIN scores（レガシー、要移行）
```

---

## 4. 各指標のデータソースと計算式

### 4-1. 配当スコア指標（14指標）

| # | 指標名 | field | 取得元 | 計算式 | 更新頻度 |
|---|---|---|---|---|---|
| 1 | 連続非減配年数 | `consecutive_no_cut_years` | dividend_history | 年次集計→直近から遡り減配なし年数カウント | 半年 |
| 2 | 連続増配年数 | `consecutive_dividend_growth_years` | dividend_history | 同上→増配カウント | 半年 |
| 3 | 減配信頼性 | `dividend_reliability` | dividend_history | 過去20年の減配回数→1.0/0.6/0.0 | 半年 |
| 4 | 10年増配CAGR | `dividend_growth_10y_cagr` | dividend_history | (直近年配当/10年前配当)^(1/10)-1 | 半年 |
| 5 | 配当性向 | `payout_ratio` | yfinance info | `info["payoutRatio"]` そのまま | 四半期 |
| 6 | FCFカバレッジ | `fcf_payout_coverage` | yfinance info | freeCashflow / (dividendRate × shares) | 四半期 |
| 7 | EPS成長5年 | `eps_growth_5y` | yfinance financials | CAGR(Diluted EPS, 5年) | 四半期 |
| 8 | 売上高CAGR | `revenue_growth_5y_cagr` | yfinance financials | CAGR(Total Revenue, 5年) | 四半期 |
| 9 | 自己資本比率 | `equity_ratio` | yfinance balance_sheet | Stockholders Equity / Total Assets | 四半期 |
| 10 | ROE | `roe` | yfinance info | `info["returnOnEquity"]` そのまま | 四半期 |
| 11 | 営業利益率 | `operating_margin` | yfinance info | `info["operatingMargins"]` そのまま | 四半期 |
| 12 | ROIC-WACC | `roic_minus_wacc` | yfinance info+fin+bs | NOPAT/IC - WACC（複合計算） | 四半期 |
| 13 | 配当利回り | `div_yield` | price_history + stock_fundamentals | annual_div / close | 毎日 |
| 14 | ネットキャッシュPER | `net_cash_per` | price_history + stock_fundamentals | PER × (1 - net_cash/market_cap) | 毎日 |

### 4-2. モメンタムスコア指標（8指標）

| # | 指標名 | field | 取得元 | 計算式 | 更新頻度 |
|---|---|---|---|---|---|
| 1 | 3M相対リターン | `rel_ret_3m` | price_history | (銘柄3Mリターン) - (TOPIX 3Mリターン) | 毎日 |
| 2 | 52週高値比率 | `hi52_ratio` | price_history | 現在値 / 52週高値 | 毎日 |
| 3 | 12M相対リターン | `rel_ret_12m` | price_history | (銘柄12Mリターン) - (TOPIX 12Mリターン) | 毎日 |
| 4 | 売上成長率 | `rev_growth` | computed_metrics | `revenue_growth_5y_cagr` | 四半期 |
| 5 | EPS成長率 | `eps_growth` | computed_metrics | `eps_growth_5y` | 四半期 |
| 6 | ROE | `roe` | computed_metrics | raw_financials.roe を流用 | 四半期 |
| 7 | 営業利益率 | `operating_margin` | computed_metrics | raw_financials.operating_margin を流用 | 四半期 |
| 8 | 出来高増加率 | `vol_ratio` | price_history | 直近20日平均 / 60日平均（未実装） | 毎日 |

---

## 5. 課題と対応状況

### 課題A: 取得データと計算データの混在 → ✅ 解決

`raw_financials`（生データ）と `computed_metrics`（計算値）に分離。

### 課題B: モメンタムスコアが揮発する → ✅ 解決

`momentum_scores` テーブルに永続化。過去のスコアも保持される。

### 課題C: スコア内訳がJSONに閉じ込められている → ✅ 解決

`dividend_scores` / `momentum_scores` ともにカラム展開。SQLでのフィルタ・ソートが高速。

### 課題D: APIが計算を行っている → ✅ 解決

APIは `SELECT` のみ。計算はバッチで事前実行してテーブルに保存。

### 残存課題

| 課題 | 内容 | 影響 |
|---|---|---|
| 旧テーブル残存 | `stock_fundamentals`, `scores` がまだ残っている | ディスク容量のみ。機能影響なし |
| 検索API | `/api/stock/search` がレガシー `scores` テーブルを参照 | 検索結果のスコアが古い可能性 |
| 配当スコア0.0問題 | 一部指標（consecutive_no_cut_years等）が0.0 | computed_metricsの計算ロジック確認要 |
| 別プロセス上書き | uvicorn --reload環境で他セッションがAPIファイルを上書き | テスト追加で対策予定 |

---

## 6. アーキテクチャ図

```
[yfinance API] ─取得─→ raw_financials     ─┐
[yfinance API] ─取得─→ price_history       ─┼─計算─→ computed_metrics ─┬─scoring─→ dividend_scores
[yfinance API] ─取得─→ dividend_history    ─┘                         └─scoring─→ momentum_scores
                                                                                       ↓
                                                                               API (SELECT only)
                                                                                       ↓
                                                                               React SPA (localhost:8080)
```

---

## 7. APIレスポンス仕様（フロントエンド契約）

### GET /api/momentum/rank

```json
{
  "items": [{
    "code": "7203",
    "name": "トヨタ自動車",
    "sector": "輸送用機器",
    "momentum_score": 80.2,
    "scored_at": "2026-06-06",
    "ret_12m": 29.4,         // 12M絶対リターン (%)
    "ret_3m": 5.2,           // 3M絶対リターン (%)
    "rel_ret_12m": 12.1,     // 12M相対リターン (%)
    "rel_ret_3m": 18.9,      // 3M相対リターン (%)
    "hi52_ratio": 100,       // 52週高値比率 (%)
    "rev_growth": 10.9,      // 売上CAGR 5年 (%)
    "eps_growth": 18.1,      // EPS CAGR 5年 (%)
    "market_cap": 40000000000000,
    "breakdown": { "rel_ret_3m": 8.5, "rel_ret_12m": 7.0, ... }
  }],
  "total": 30
}
```

### GET /api/momentum/check/{code}

```json
{
  "code": "7203",
  "name": "トヨタ自動車",
  "sector": "輸送用機器",
  "momentum_score": 80.2,
  "scored_at": "2026-06-06T...",
  "div_score": 57.4,
  "market_cap": 40000000000000,
  "fields": {
    "ret_12m": 10.8,
    "ret_3m": -17.7,
    "hi52_ratio": 73,
    "rev_growth": 10.9,
    "eps_growth": 18.1
  },
  "breakdown": { "rel_ret_3m": 8.5, ... }
}
```

### GET /api/dividend/check/{code}

```json
{
  "code": "7203",
  "name": "トヨタ自動車",
  "dividend_score": 57.4,
  "scored_at": "2026-06-06",
  "raw": {
    "div_yield": 0.031,
    "per": 10.5,
    "pbr": 1.2,
    "roe": 0.12,
    "equity_ratio": 0.38,
    "payout_ratio": 0.30,
    "consecutive_no_cut_years": 5,
    "consecutive_dividend_growth_years": 3,
    "dividend_growth_5y_cagr": 0.08,
    "market_cap": 40000000000000,
    ...
  },
  "breakdown": { "div_yield": 6.5, "per": 8.0, ... }
}
```

→ 設計詳細は `docs/refactoring-data-layer.md` を参照  
→ タスク進捗は `docs/refactoring-tasks.md` を参照
