# データ層リファクタリング設計（目標状態）

> 前提: `docs/data-architecture.md` に現状と課題を記載  
> タスク: `docs/refactoring-tasks.md` に実装手順を記載  
> 最終更新: 2026-06-06

---

## 現状の問題

1. **取得データと計算データが同じテーブル（`stock_fundamentals`）に混在**
   - ネットから取得した生データ（eps, bps, roe等）と、計算で算出した値（equity_ratio, eps_growth_5y等）が区別できない
   - どの値が正しいソースから来たか検証不可能

2. **スコアテーブルが1つしかなく、配当スコア専用**
   - `scores` テーブルは配当スコアのみ保存
   - モメンタムスコアはテーブルが存在せず、毎回リアルタイム計算（揮発する）

3. **個別スコアがJSON文字列に閉じ込められている**
   - SQLでのフィルタ・ソート・集計が困難
   - `json_extract()` による毎回パースが必要

---

## 目指すアーキテクチャ: 3層分離

```
Layer 1: マスターデータ（Webから取得した正のデータ）
    ↓ バッチ計算
Layer 2: 算出データ（マスターから計算・集約した指標）
    ↓ スコアリング
Layer 3: スコアリングデータ（配当・モメンタムそれぞれの評価結果）
    ↓ SELECT
API（計算しない、テーブルを読むだけ）
```

---

## Layer 1: マスターデータ（取得データ）

**原則: ネットから取得したままの値。計算・加工しない。**

| テーブル | 内容 | ソース | 更新頻度 |
|---|---|---|---|
| `stocks` | 銘柄マスター（コード・名前・市場・セクター） | JPX/yfinance | 随時 |
| `price_history` | 日次終値・出来高 | yfinance download | 毎日 |
| `dividend_history` | 権利落ち日・配当額 | yfinance dividends | 半年 |
| `raw_financials` | **【新設】** yfinanceから取得した生の財務データ | yfinance info/financials/balance_sheet | 四半期 |

### `raw_financials` テーブル設計

```sql
CREATE TABLE raw_financials (
    code                TEXT PRIMARY KEY,
    -- info から直接取得（変換なし）
    eps                 REAL,    -- dilutedEPS or trailingEps
    bps                 REAL,    -- bookValue
    shares_outstanding  REAL,    -- sharesOutstanding
    roe                 REAL,    -- returnOnEquity
    operating_margins   REAL,    -- operatingMargins
    payout_ratio        REAL,    -- payoutRatio
    free_cashflow       REAL,    -- freeCashflow
    operating_cashflow  REAL,    -- operatingCashflow
    capital_expenditures REAL,   -- capitalExpenditures
    dividend_rate       REAL,    -- dividendRate
    market_cap          REAL,    -- marketCap（取得時点）
    beta                REAL,    -- beta
    -- balance_sheet から直接取得
    total_assets        REAL,
    stockholders_equity REAL,
    current_assets      REAL,
    total_liabilities   REAL,
    long_term_debt      REAL,
    short_term_debt     REAL,
    retained_earnings   REAL,
    -- financials から直接取得（配列→最新値）
    diluted_eps_latest  REAL,    -- financials["Diluted EPS"][0]
    total_revenue_latest REAL,   -- financials["Total Revenue"][0]
    -- CAGR計算用の始点（N年前の値）
    diluted_eps_5y_ago  REAL,
    total_revenue_5y_ago REAL,
    diluted_eps_periods INTEGER, -- 実際に取れた期間数
    total_revenue_periods INTEGER,
    -- メタ
    fetched_at          TEXT NOT NULL  -- 取得日時
);
```

**ポイント**: 
- yfinanceのキー名に近い命名（何を取得したか自明）
- 計算は一切しない。`equity_ratio = equity / assets` すら入れない
- `fetched_at` で「いつ取得した値か」を追跡可能

---

## Layer 2: 算出データ（計算指標）

**原則: Layer 1 のマスターデータのみを入力として計算する。**

| テーブル | 内容 | 入力 | 更新タイミング |
|---|---|---|---|
| `computed_metrics` | **【新設】** 全算出指標 | raw_financials + price_history + dividend_history | バッチ実行時 |

### `computed_metrics` テーブル設計

```sql
CREATE TABLE computed_metrics (
    code                              TEXT PRIMARY KEY,
    -- 価格由来（毎日更新）
    per                               REAL,    -- close / eps
    pbr                               REAL,    -- close / bps
    current_market_cap                REAL,    -- close × shares
    div_yield                         REAL,    -- annual_div / close
    mix_coefficient                   REAL,    -- per × pbr
    net_cash_per                      REAL,    -- per × (1 - net_cash / market_cap)
    -- 財務由来（四半期更新）
    equity_ratio                      REAL,    -- stockholders_equity / total_assets
    debt_to_equity                    REAL,    -- (long_debt + short_debt) / equity
    eps_growth_5y                     REAL,    -- CAGR(eps_latest, eps_5y_ago)
    revenue_growth_5y_cagr            REAL,    -- CAGR(rev_latest, rev_5y_ago)
    roic_minus_wacc                   REAL,    -- 複合計算
    fcf_payout_coverage               REAL,    -- fcf / annual_div_total
    retained_earnings_div_ratio       REAL,    -- retained_earnings / 配当総額
    -- 配当由来（半年更新）
    annual_div                        REAL,    -- dividend_historyの直近12M集計
    consecutive_no_cut_years          INTEGER, -- dividend_historyから年次集計→逆算
    consecutive_dividend_growth_years INTEGER,
    dividend_growth_5y_cagr           REAL,
    dividend_growth_10y_cagr          REAL,
    dividend_reliability              REAL,
    dividend_cut_count_20y            INTEGER,
    -- モメンタム由来（毎日更新）
    ret_3m                            REAL,    -- price_historyから計算
    ret_12m                           REAL,
    rel_ret_3m                        REAL,    -- ret_3m - topix_ret_3m
    rel_ret_12m                       REAL,
    hi52_ratio                        REAL,
    -- 更新タイムスタンプ
    price_computed_at                 TEXT,
    fin_computed_at                   TEXT,
    div_computed_at                   TEXT
);
```

**ポイント**:
- 計算ロジックの入力は必ず `raw_financials` / `price_history` / `dividend_history` のみ
- 計算結果がおかしい場合、マスターデータを見れば原因を特定できる
- `*_computed_at` で「いつ計算した結果か」を追跡

---

## Layer 3: スコアリングデータ

**原則: Layer 2 の算出データ + ルール定義 → スコア。入力が同じなら同じ結果になる。**

| テーブル | 内容 |
|---|---|
| `dividend_scores` | **【新設】** 配当株としての評価 |
| `momentum_scores` | **【新設】** モメンタム株としての評価 |

### `dividend_scores` テーブル設計

```sql
CREATE TABLE dividend_scores (
    code              TEXT NOT NULL,
    scored_at         TEXT NOT NULL,
    rule_version_id   INTEGER NOT NULL,
    total_score       REAL NOT NULL,
    -- 個別スコア（0〜10点、カラムとして展開）
    s_consecutive_no_cut_years          REAL,
    s_consecutive_dividend_growth_years REAL,
    s_dividend_reliability              REAL,
    s_dividend_growth_10y_cagr          REAL,
    s_payout_ratio                      REAL,
    s_fcf_payout_coverage               REAL,
    s_eps_growth_5y                     REAL,
    s_revenue_growth_5y_cagr            REAL,
    s_roe                               REAL,
    s_operating_margin                  REAL,
    s_div_yield                         REAL,
    s_mix_coefficient                   REAL,
    s_net_cash_per                      REAL,
    s_roic_minus_wacc                   REAL,
    s_retained_earnings_div_ratio       REAL,
    PRIMARY KEY (code, scored_at)
);
```

### `momentum_scores` テーブル設計

```sql
CREATE TABLE momentum_scores (
    code              TEXT NOT NULL,
    scored_at         TEXT NOT NULL,
    total_score       REAL NOT NULL,
    -- 個別スコア
    s_rel_ret_3m      REAL,
    s_rel_ret_12m     REAL,
    s_hi52_ratio      REAL,
    s_rev_growth      REAL,
    s_eps_growth      REAL,
    s_roe             REAL,
    s_operating_margin REAL,
    s_vol_ratio       REAL,
    PRIMARY KEY (code, scored_at)
);
```

---

## API層

**原則: 計算しない。テーブルを `SELECT` するだけ。**

```
GET /api/dividend/rank   → SELECT FROM dividend_scores JOIN stocks
GET /api/momentum/rank   → SELECT FROM momentum_scores JOIN stocks
GET /api/dividend/check  → SELECT FROM dividend_scores WHERE code=?
GET /api/momentum/check  → SELECT FROM momentum_scores WHERE code=?
```

---

## データフロー図

```
[yfinance API] ─取得─→ raw_financials     ─┐
[yfinance API] ─取得─→ price_history       ─┼─計算─→ computed_metrics ─┬─scoring─→ dividend_scores
[yfinance API] ─取得─→ dividend_history    ─┘                         └─scoring─→ momentum_scores
                                                                                       ↓
                                                                               API (SELECT only)
```

---

## 移行方針

既存テーブル（`stock_fundamentals`, `scores`）は残しつつ新テーブルを並行稼働させ、
新テーブルで問題なく動作確認後に旧テーブルを廃止する。

---

## 実装状況（2026-06-06 時点）

### ✅ 完了済み

| 項目 | 状態 |
|---|---|
| Layer 1: `raw_financials` | テーブル作成済み、3,745件のデータ投入済み |
| Layer 2: `computed_metrics` | テーブル作成済み、3,746件のデータ投入済み |
| Layer 3: `dividend_scores` | テーブル作成済み、3,746件スコアリング済み |
| Layer 3: `momentum_scores` | テーブル作成済み、3,746件スコアリング済み |
| API層: 配当 | `dividend_scores` + `computed_metrics` + `raw_financials` 参照。`raw` フィールド付き |
| API層: モメンタム | `momentum_scores` + `computed_metrics` 参照。rank に実数リターン値、check に `fields` 付き |
| パイプライン | `findex pipeline` コマンドで一括実行可能 |
| 日次自動実行 | launchd（平日18:00）`scripts/daily.sh` で compute + score 自動実行 |
| TOPIX backfill | 1306の2年分(487レコード)を投入済み。相対リターン計算可能 |
| UI | 全6ページ正常動作確認済み（Playwright + curl）|

### ⚠️ 制限事項・既知の差異

| 項目 | 設計との差異 | 理由 |
|---|---|---|
| `momentum_scores` に `rule_version_id` なし | テーブル作成時に省略 | モメンタムルールは固定のため不要と判断 |
| 暫定バッチ (`scorer/`) が残存 | `stock_fundamentals` 直接参照のバッチ | `computed_metrics` 経由のバッチ (`updater/score_*.py`) が本流。統合予定 |
| `dividend_scores` にPER/PBR保存なし | 設計書の `computed_metrics` カラムとして定義 | APIが `computed_metrics` + `raw_financials` から動的参照で対応 |
| 別プロセスによるファイル上書き | uvicorn --reload 環境で他セッションが API ファイルを上書き | `refactoring-tasks.md` の注意事項参照 |

### コマンド体系

```bash
# 新パイプライン（推奨）
findex pipeline                          # fetch → compute → score 一括

# 個別実行
findex fetch quarterly                   # raw_financials 更新（yfinance）
findex compute                           # computed_metrics 再計算
findex score dividend                    # dividend_scores 再スコアリング
findex score momentum                    # momentum_scores 再スコアリング

# 旧コマンド（まだ動作する）
findex update                            # 株価 + 配当スコア
findex update --quarterly                # 財務 → stock_fundamentals
findex update --dividends --force-all    # 配当履歴 → dividend_history
```
