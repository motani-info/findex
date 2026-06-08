# データライフサイクル設計

Findex のデータ取得は3つのカテゴリに分類される。
カテゴリごとに更新頻度・取得方法・並列化戦略が異なる。

---

## カテゴリ一覧

| Category | 内容 | 更新頻度 | コマンド | TTL |
|---|---|---|---|---|
| **A** 価格由来 | 配当利回り / PER / PBR / 時価総額 | 毎日 | `findex update` | なし（毎回再計算） |
| **B** 財務諸表 | ROE / 自己資本比率 / EPS成長 / FCFカバレッジ | 四半期 | `findex update --quarterly` | 90日 |
| **C** 配当履歴 | 連続非減配 / 増配CAGR / 減配信頼性 | 半年 | `findex update --dividends` | 180日 |

---

## Category A — 価格由来指標（毎日更新）

### 取得方法

```
yf.download(全銘柄, period="2d", threads=False)
  → 終値（Close）を全銘柄分一括取得（1リクエスト/バッチ）
```

### 計算フロー

```
終値（API）+ EPS/BPS/shares/annual_div（SQLite） → ローカル計算
  ├── div_yield        = annual_div / close
  ├── per              = close / eps
  ├── pbr              = close / bps
  ├── market_cap       = close × shares
  ├── mix_coefficient  = per × pbr
  └── net_cash_per     = per × (1 - net_cash / market_cap)
```

### 並列化

| 項目 | 設定値 |
|---|---|
| バッチサイズ | 200銘柄/バッチ |
| バッチ間待機 | 10秒 |
| スレッド | `threads=False`（yfinance内部SQLite競合回避） |
| 所要時間 | 約5分（3,900銘柄） |

### 注意

- `threads=False` は必須。`threads=True` にすると yfinance の TZキャッシュ用 SQLite に複数スレッドが同時アクセスして `OperationalError` が発生する
- quarterly / dividends と**同時実行禁止**。レートリミットを共有するため後半バッチが大量スキップされる

---

## Category B — 財務諸表（四半期更新）

### 取得方法

```
yf.Ticker(code).info          → ROE / 配当性向 / 営業利益率 など
yf.Ticker(code).financials    → EPS成長（5年CAGR）/ 売上CAGR
yf.Ticker(code).balance_sheet → 自己資本比率 / 有利子負債比率 / ネット現金
```

### 取得指標

| フィールド | ソース | 充足率 |
|---|---|---|
| roe | info.returnOnEquity | ~93% |
| equity_ratio | balance_sheet | ~99% |
| debt_to_equity | balance_sheet | ~99% |
| operating_margin | info.operatingMargins | ~98% |
| payout_ratio | info.payoutRatio | ~98% |
| eps_growth_5y | financials["Diluted EPS"]（5年CAGR） | ~69% |
| revenue_growth_5y_cagr | financials["Total Revenue"]（5年CAGR） | ~97% |
| roic_minus_wacc | info + financials + balance_sheet | ~79% |
| fcf_payout_coverage | FCF ÷ 年間配当総額（詳細は下記） | ~44% |
| eps / bps / shares / net_cash | info + balance_sheet | ~95%+ |

### FCFカバレッジの計算詳細

```python
# Step1: freeCashflow を優先取得
fcf = info.get("freeCashflow")

# Step2: 取れない場合は営業CF - 設備投資で代替（フォールバック）
if not fcf:
    op_cf = info.get("operatingCashflow")
    capex = info.get("capitalExpenditures")  # yfinanceでは負値で返る
    if op_cf and capex:
        fcf = op_cf + capex  # capexは負値なので加算でFCFになる

# FCF ≤ 0 または取得不可 → None（充足率44%の主因）
if not fcf or fcf <= 0:
    return None

result = fcf / annual_div_total
# 異常値（0以下 or 100倍超）は除外
return result if 0 < result < 100 else None
```

充足率44%の主因は **freeCashflow も operatingCashflow も yfinance から取れない銘柄が多い**こと（特に小型株・金融株）。

### EPS成長・売上CAGRの計算詳細

```python
# EPS成長5年CAGR（_calc_eps_cagr）
# 1. "Diluted EPS" → 取れなければ "Basic EPS" でフォールバック
# 2. 直近〜最大5年前のデータでCAGR計算（データが少なければ期間を短縮）
# 3. 始点・終点のどちらかが ≤ 0（赤字）→ None
# 4. |CAGR| > 50% は異常値として None（急成長・急落銘柄の除外）

# 売上高5年CAGR（_calc_revenue_cagr）
# 1. "Total Revenue" から取得
# 2. 同じく |CAGR| > 50% は None
```

EPS成長の充足率69%の主因は**赤字企業（始点がマイナス）でCAGR計算不能**になるケース。

### 並列化

| 項目 | 設定値 |
|---|---|
| 銘柄間並列数（WORKERS） | **2**（4以上で401多発） |
| バースト後待機（BURST_DELAY） | 1.0秒 |
| TTL | 90日（`fin_updated_at` で管理） |
| 所要時間 | 約100分（3,900銘柄・全更新時） |
| 通常運用 | TTL超過分のみ → 約25分/四半期 |

### TTL の仕組み

```sql
-- fin_updated_at が 90日以上前の銘柄のみ取得対象
WHERE fin_updated_at IS NULL OR fin_updated_at < (now - 90days)
```

初回または全更新時は `--force-all` フラグで TTL を無視する。

---

## Category C — 配当履歴（半年更新）

### 取得方法

```
yf.Ticker(code).dividends → 全配当履歴（上場来）
  → 年次集計して以下を計算
```

### 取得指標

| フィールド | 計算方法 | 充足率 |
|---|---|---|
| consecutive_no_cut_years | 直近から遡って非減配が続いた年数 | 100% |
| consecutive_dividend_growth_years | 直近から遡って増配が続いた年数 | 100% |
| dividend_reliability | 過去20年の減配回数 → 0回=1.0 / 1回=0.6 / 2回+=0.0 | ~100% |
| dividend_growth_5y_cagr | 5年前と直近の年間配当でCAGR計算 | ~72% |
| dividend_growth_10y_cagr | 10年前と直近の年間配当でCAGR計算（11期以上必要） | ~63% |
| annual_div（年間配当/株） | 直近12ヶ月の配当合計 | ~80% |

### 各指標の計算詳細

```python
# 年次集計: 四半期配当 → 暦年（1〜12月）に集計
# 連続非減配: 最新年から1年ずつ遡り、前年比で減配した時点でカウント停止
# 連続増配:   同様に増配が続いた年数をカウント

# dividend_reliability（減配信頼性スコア）
recent_20y = 直近20年分の年次配当データ
cuts = 前年より配当が下がった年の回数
score = 1.0 if cuts == 0 else (0.6 if cuts == 1 else 0.0)

# CAGR共通ルール
# ・始点が 0 以下 → None（無配当期間があった場合）
# ・|CAGR| > 50% → None（異常値除外）
# ・10年CAGRは11期以上のデータが必要（充足率63%の主因）
```

配当CAGR系の充足率が低い主因は**配当歴が短い銘柄**（上場5〜10年未満）および**無配当銘柄**（約770件）。

### 並列化

| 項目 | 設定値 |
|---|---|
| 銘柄間並列数（WORKERS） | **2** |
| バースト後待機（BURST_DELAY） | 1.0秒 |
| TTL | 180日（`div_updated_at` で管理） |
| 所要時間 | 約75分（3,900銘柄・全更新時） |
| 通常運用 | TTL超過分のみ → 約38分/半年 |

---

## データ保存先

### SQLite: `~/.findex/db/findex.db`

```
stock_fundamentals          Category B / C の安定値を保持
  ├── eps, bps, shares      → Category A のローカル計算に使用
  ├── annual_div            → div_yield 計算に使用
  ├── roe, equity_ratio ... → Category B 指標
  ├── consecutive_*         → Category C 指標
  ├── fin_updated_at        → Category B の TTL 管理
  └── div_updated_at        → Category C の TTL 管理

scores                      スコア履歴（日付ごとに蓄積）
  ├── total_score           → 100点換算スコア
  ├── raw_json              → 全フィールドの生値（スコア計算の入力）
  └── price_updated_at      → Category A の最終更新日時
```

### JSON キャッシュ: `~/.findex/cache/`

フルスキャン時のみ使用。TTL 7日。  
通常の `findex update` では使用しない（SQLite から直接読み取る）。

---

## データ充足率の現状（2026-06-02時点）

| 指標 | 充足率 | ステータス |
|---|---|---|
| ①連続非減配 / ②減配信頼性 / ③連続増配 | 99〜100% | ✅ |
| ⑥自己資本 / ⑦有利子負債 / ⑧ROE / ⑩営業利益率 | 93〜99% | ✅ |
| ⑰売上CAGR / 予想配当性向 | 97〜98% | ✅ |
| ⑭ミックス係数 / ⑬利益剰余金倍率 / ⑫ネットキャッシュPER | 80〜89% | ✅ |
| ⑨ROIC-WACC | 79% | ⚠️ |
| ④配当5年CAGR / ⑮配当10年CAGR | 63〜72% | ⚠️ 短期配当履歴の銘柄が多い |
| ⑤EPS成長5年 | 69% | ⚠️ 赤字・データなし銘柄 |
| ⑯FCFカバレッジ | 44% | ⚠️ yfinanceのFCFデータ精度の限界 |
| **⑪配当利回り** | **2%** | ❌ daily update 要実行 |

---

## 実行順序の制約

**必ずシリアル実行**（同時実行禁止）。  
quarterly / dividends / daily を並走させるとレートリミットを共有し、後半バッチが大量スキップされる。

### 日次自動実行（launchd、平日18:00）

```bash
# scripts/daily.sh の内容:
findex update                    # price_history 更新
findex compute                   # computed_metrics 再計算
findex score dividend            # dividend_scores 更新
findex score momentum            # momentum_scores 更新
```

設定: `~/Library/LaunchAgents/com.findex.daily.plist`

### 手動実行（四半期・半年）

```
推奨実行順:
  1. findex fetch quarterly       （四半期に1回。yfinance → raw_financials）
  2. findex update --dividends    （半年に1回。yfinance → dividend_history）
  3. findex compute               （上記完了後に再計算）
  4. findex score dividend        （スコア再計算）
  5. findex score momentum        （スコア再計算）
```

### 一括実行（初回セットアップ or フル更新）

```bash
findex pipeline                  # fetch → compute → score を全自動実行（約63分）
```

---

## yfinance レートリミットについて

| 症状 | 原因 | 対策 |
|---|---|---|
| バッチ後半でスキップ増加 | 同時実行によるIP帯域消費 | シリアル実行を徹底 |
| `OperationalError: unable to open database file` | `threads=True` によるSQLite競合 | `threads=False`（設定済み） |
| `401 Unauthorized` | 2プロセス以上で crumb 競合 | WORKERS=2 上限を守る |
| `possibly delisted` | 実際の上場廃止銘柄 | 正常（無視してよい） |

yfinance は非公式 API のため、レートリミットの閾値は非公開。  
安全な目安: **1銘柄あたり約1秒、同時接続2以下**。
