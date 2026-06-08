# Findex — 使い方とデータの流れ

日本株スコアリング・ランキングCLIツール。全上場日本株（約3,900銘柄）を  
18指標・100点満点で採点し、増配継続株を効率よく発掘する。

---

## 日常的な使い方

### ランキングを見る（API不要・即時）

```bash
# 総合TOP30
findex rank

# 利回り4%以上 × 10年以上非減配のTOP20
findex rank --min-yield 0.04 --min-no-cut 10 --top 20

# セクター絞り込み
findex rank --sector 電気機器

# CSV出力
findex rank --top 100 --out ranking.csv
```

### スコアを最新の株価で更新する（毎日 約4〜5分）

```bash
findex update
```

内部でやること:
1. `yf.download()` で全銘柄の終値を一括取得（200銘柄/バッチ × 20バッチ）
2. SQLite に保存済みの EPS・BPS・配当 を読み出す（API呼び出しなし）
3. PER・PBR・配当利回り・時価総額 などをローカル計算
4. 再スコアリングして SQLite を更新

### 財務諸表を更新する（四半期ごと 約15〜30分）

```bash
findex update --quarterly
```

前回の更新から90日以上経過した銘柄のみ `yf.Ticker` を叩く。  
ROE・自己資本比率・EPS成長率・FCFカバレッジ などを更新し、SQLite に保存。

### 配当履歴を更新する（半年ごと 約30〜60分）

```bash
findex update --dividends
```

前回の更新から180日以上経過した銘柄のみ配当履歴を取得。  
連続非減配年数・増配CAGR・減配信頼性スコア などを更新。

---

## 初回セットアップ / 全銘柄フルスキャン

初回または半年ごとに実行。全銘柄の全データを一から取得する。

```bash
# 全銘柄フルスキャン（2〜4時間）
uv run python findex_fullscan.py

# 特定銘柄のみ確認
findex check 7203 9433 8306
```

---

## データの流れ（ライフサイクル）

```
┌─────────────────────────────────────────────────────────────────┐
│                         yfinance API                             │
│                                                                  │
│  yf.download()           yf.Ticker().info          t.dividends  │
│  ↓ 株価（全銘柄一括）      ↓ 財務諸表（銘柄ごと）       ↓ 配当履歴     │
└─────┬───────────────────────────┬──────────────────────┬────────┘
      │                           │                      │
      ▼                           ▼                      ▼
┌──────────────┐        ┌──────────────────┐   ┌──────────────────┐
│ Category A   │        │ Category B       │   │ Category C       │
│ 価格由来指標  │        │ 財務諸表指標      │   │ 配当履歴指標      │
│              │        │                  │   │                  │
│ ・配当利回り  │        │ ・ROE            │   │ ・連続非減配年数  │
│ ・PER / PBR  │        │ ・自己資本比率    │   │ ・連続増配年数    │
│ ・時価総額   │        │ ・EPS成長5y CAGR │   │ ・配当CAGR 5/10y │
│ ・ミックス係数│        │ ・FCF配当カバレッジ│   │ ・減配信頼性スコア│
│ ・ネット現金  │        │ ・ROIC-WACC      │   │                  │
│              │        │ ・売上5y CAGR    │   │ 更新頻度: 半年   │
│ 更新頻度: 毎日│        │                  │   │ TTL: 180日       │
└──────┬───────┘        │ 更新頻度: 四半期  │   └────────┬─────────┘
       │                │ TTL: 90日        │            │
       │                └────────┬─────────┘            │
       │                         │                      │
       │              ┌──────────▼──────────────────────▼──────┐
       │              │         stock_fundamentals テーブル       │
       │              │  SQLite: ~/.findex/db/findex.db          │
       │              │                                          │
       │              │  EPS, BPS, shares, annual_div,           │
       │              │  ROE, equity_ratio, roic_minus_wacc,     │
       │              │  consecutive_no_cut_years, cagr_*, ...   │
       │              └────────────────────┬────────────────────┘
       │                                   │
       └───────────────────────────────────┘
                         ↓
              ┌──────────────────────┐
              │   スコアリングエンジン  │
              │   rules.yaml の18指標  │
              │   → 197点 → 100点換算  │
              └──────────┬───────────┘
                         ↓
              ┌──────────────────────┐
              │    scores テーブル    │
              │  total_score,         │
              │  score_json,          │
              │  raw_json,            │
              │  price_updated_at     │
              └──────────────────────┘
                         ↓
                  findex rank で表示
```

---

## スコアリング指標（18指標・197点満点 → 100点換算）

### 配当継続性（最重要グループ）

| # | 指標 | 重み | 満点条件 | 意味 |
|---|---|---|---|---|
| ① | 連続非減配年数 | 2.0 | 17年以上 | リーマン・コロナ耐性の最高証拠 |
| ② | 減配信頼性スコア | 1.5 | 過去20年0回 | 危機時の行動が将来を予測する |
| ③ | 連続増配年数 | 1.5 | 17年以上 | 経営陣の能動的増配コミットメント |
| ④ | 配当成長5年CAGR | 1.0 | 30%以上 | 複利加速度（①②と情報重複あり） |
| ⑮ | 配当成長10年CAGR | 1.2 | 8%以上 | 長期実績の信頼性（5年より重い） |

### 配当安全性（高優先グループ）

| # | 指標 | 重み | 満点条件 | 意味 |
|---|---|---|---|---|
| ⑤ | EPS成長5年CAGR | 1.0 | 15%以上 | 配当原資の成長性 |
| ⑯ | FCF配当カバレッジ | 1.5 | FCF÷配当が2倍以上 | 増配持続の根幹（利益より実態を反映）|
| ⑰ | 売上高5年CAGR | 1.0 | 7%以上 | EPS成長が本物かどうかの裏付け |
| ④ | 予想配当性向 | 1.5 | 35%以下 | 利益半減でも無配にならない安全余白 |

### 財務健全性

| # | 指標 | 重み | 満点条件 | 意味 |
|---|---|---|---|---|
| ⑥ | 自己資本比率 | 1.2 | 80%以上 | 財務の要塞度 |
| ⑦ | 有利子負債比率 | 0.8 | 10%以下 | 借入依存度の確認 |
| ⑧ | ROE | 1.2 | 20%以上 | 自己資本の収益効率 |
| ⑨ | ROIC-WACC | 1.3 | 10%以上 | 最も理論的な付加価値指標 |
| ⑩ | 営業利益率 | 1.0 | 20%以上 | 価格決定力・競争優位の代理 |

### バリュエーション

| # | 指標 | 重み | 満点条件 | 備考 |
|---|---|---|---|---|
| ⑪ | 配当利回り | 1.2 | 3〜7% | 7%超はペナルティ（利回りの罠対策）|
| ⑫ | ネットキャッシュPER | 0.8 | 10倍以下 | 現金調整済みの割安度 |
| ⑬ | 利益剰余金配当倍率 | 1.3 | 10倍以上 | 10年分の配当を内部留保で賄える |
| ⑭ | ミックス係数 | 0.8 | PER15×PBR1.5以下 | バフェット目安の複合バリュー |

---

## ファイル構成

```
findex/
├── cli.py                    # CLIエントリ（rank / update / check / run / setup）
├── scorer/
│   └── engine.py             # スコアリングエンジン（upper_cap対応）
├── updater/
│   ├── daily.py              # Category A 毎日更新
│   ├── quarterly.py          # Category B 四半期更新
│   └── dividends.py          # Category C 半年更新
├── fetcher/
│   ├── fetch_all.py          # 1銘柄全指標を1Ticker取得（Level1並列）
│   ├── fundamentals.py       # 財務指標計算（FCF, 売上CAGR, EPS CAGR）
│   ├── dividends.py          # 配当履歴（10年CAGR, 減配信頼性）
│   ├── roic.py               # ROIC-WACC, 利益剰余金配当倍率
│   └── jquants/              # J-Quants V2フェッチャー（将来の株価ソース候補）
│       ├── client.py
│       ├── metrics.py
│       └── fetch.py
└── db.py                     # SQLite（stock_fundamentals + scores テーブル）

rules.yaml                    # 18指標スコアリングルール（197点換算）
findex_fullscan.py            # 全市場フルスキャン（パイプライン並列）
migrate_to_fundamentals.py    # 初回データ移行スクリプト
```

---

## SQLiteテーブル構造

```
~/.findex/db/findex.db

stocks                 銘柄マスター（code, name, market, sector）
  └── 3,932件

stock_fundamentals     Category B/C の安定値を保持
  ├── eps, bps, shares, annual_div
  ├── roe, equity_ratio, roic_minus_wacc, operating_margin
  ├── eps_growth_5y, revenue_growth_5y_cagr, fcf_payout_coverage
  ├── consecutive_no_cut_years, consecutive_dividend_growth_years
  ├── dividend_growth_5y_cagr, dividend_growth_10y_cagr
  ├── dividend_reliability, payout_ratio
  └── fin_updated_at, div_updated_at（TTL管理用）

scores                 スコア履歴（日付ごとに蓄積）
  ├── total_score（100点換算）
  ├── score_json（指標ごとの内訳）
  ├── raw_json（全フィールドの生値）
  └── price_updated_at, fin_updated_at, div_updated_at
```

---

## 運用スケジュール（推奨）

| 頻度 | コマンド | 所要時間 |
|---|---|---|
| 毎日（平日）| `findex update` | 約5分 |
| 四半期に1回 | `findex update --quarterly` | 約20分 |
| 半年に1回 | `findex update --dividends` | 約40分 |
| 年1回 or 初回 | `uv run python findex_fullscan.py` | 約2〜4時間 |
