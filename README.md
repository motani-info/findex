# Findex 📈

日本の全上場株式（約3,900銘柄）を **18指標・100点満点** でスコアリングし、  
長期的に増配を続けている銘柄を効率よく発掘するCLIツール。

---

## コンセプト

- **増配継続株に特化したスコアリング** — 配当利回りの高さではなく、増配を続ける財務的な実力を評価する
- **毎日5分で最新ランキング** — 重いデータ（財務・配当履歴）は一度取得したら再利用。毎日の更新は株価だけ
- **全銘柄カバー** — プライム・スタンダード・グロース・名証など約3,900銘柄を網羅

---

## インストール

```bash
git clone https://github.com/yourname/findex
cd findex
uv sync
```

**依存関係**: Python 3.13+, [uv](https://github.com/astral-sh/uv)

---

## クイックスタート

```bash
# TOP30ランキングを見る（DBがあれば即時表示）
findex rank

# 利回り4%以上 × 10年以上非減配に絞る
findex rank --min-yield 0.04 --min-no-cut 10

# 毎日の株価更新（約5分）
findex update

# 結果をCSVに出力
findex rank --top 100 --out ranking.csv
```

---

## コマンドリファレンス

### `findex rank` — ランキング表示

```
findex rank [OPTIONS]

Options:
  --top INTEGER        表示件数（デフォルト: 30）
  --market TEXT        市場フィルタ（例: プライム）
  --sector TEXT        業種フィルタ（例: 電気機器）
  --min-yield FLOAT    最低配当利回り（例: 0.04 = 4%）
  --min-no-cut INTEGER 最低連続非減配年数
  --out PATH           CSV出力先
```

### `findex update` — データ更新・スコア再計算

```
findex update [OPTIONS]

Options:
  （なし）              Category A: 毎日更新（株価のみ、約5分）
  --quarterly          Category B: 四半期更新（財務諸表、約60分）
  --dividends          Category C: 半年更新（配当履歴、約30分）
  --codes TEXT         カンマ区切りで銘柄を指定（例: 7203,9433）
  --dry-run            DBへの書き込みを行わない
```

### `findex check` — 個別銘柄の詳細確認

```bash
findex check 7203 9433 8306
```

### `findex setup` — APIキー設定

```bash
findex setup
# → ~/.findex/config.toml に保存（chmod 600）
```

---

## スコアリング指標（18指標）

100点満点は「理想の増配株」を意味する。平均的な優良株は40〜60点程度。

### 配当継続性（最重要）

| 指標 | 重み | 満点条件 |
|---|:---:|---|
| ① 連続非減配年数 | **2.0** | 17年以上（リーマン・コロナ耐性） |
| ② 減配信頼性スコア | **1.5** | 過去20年で減配0回 |
| ③ 連続増配年数 | **1.5** | 17年以上 |
| ⑮ 配当成長10年CAGR | 1.2 | 年8%以上（10年で2倍超） |
| ④ 配当成長5年CAGR | 1.0 | 年30%以上 |

### 配当安全性

| 指標 | 重み | 満点条件 |
|---|:---:|---|
| ⑯ FCF配当カバレッジ | **1.5** | FCFが配当総額の2倍以上 |
| 予想配当性向 | **1.5** | 35%以下（利益半減でも無配にならない水準） |
| ⑤ EPS成長5年CAGR | 1.0 | 年15%以上 |
| ⑰ 売上高5年CAGR | 1.0 | 年7%以上 |

### 財務健全性

| 指標 | 重み | 満点条件 |
|---|:---:|---|
| ⑨ ROIC-WACC | **1.3** | 10%以上（超過リターン） |
| ⑧ ROE | 1.2 | 20%以上 |
| ⑥ 自己資本比率 | 1.2 | 80%以上 |
| ⑩ 営業利益率 | 1.0 | 20%以上 |
| ⑦ 有利子負債比率 | 0.8 | 10%以下 |

### バリュエーション

| 指標 | 重み | 満点条件 |
|---|:---:|---|
| ⑬ 利益剰余金配当倍率 | **1.3** | 10倍以上 |
| ⑪ 配当利回り | 1.2 | 3〜7%（7%超は利回りの罠としてペナルティ） |
| ⑭ ミックス係数 | 0.8 | PER×PBR ≤ 22.5（バフェット目安） |
| ⑫ ネットキャッシュPER | 0.8 | 10倍以下 |

---

## データのライフサイクル

```
yfinance API
  │
  ├── yf.download()（全銘柄一括）
  │     └── 株価（終値）                      → 毎日更新
  │
  ├── yf.Ticker().info + financials
  │     └── ROE / 自己資本比率 / EPS成長 /    → 四半期更新（TTL 90日）
  │         FCFカバレッジ / 売上CAGR など
  │
  └── yf.Ticker().dividends
        └── 連続非減配 / 増配CAGR /           → 半年更新（TTL 180日）
            減配信頼性スコア など

                    ↓ すべて SQLite に保存
              ~/.findex/db/findex.db
                    ↓
              スコアリングエンジン（rules.yaml）
                    ↓
                findex rank
```

**毎日の更新は株価のみ**。財務・配当履歴はSQLiteから読み出してローカル計算するため、約5分で完了。

---

## 推奨運用スケジュール

| 頻度 | コマンド | 所要時間 |
|---|---|:---:|
| 毎日（平日） | `findex update` | 約5分 |
| 四半期に1回 | `findex update --quarterly` | 約60分 |
| 半年に1回 | `findex update --dividends` | 約30分 |
| 初回 / 年1回 | `uv run python findex_fullscan.py` | 約2〜4時間 |

---

## ファイル構成

```
findex/
├── cli.py                  # CLIエントリポイント
├── scorer/engine.py        # スコアリングエンジン
├── updater/
│   ├── daily.py            # 毎日更新（株価）
│   ├── quarterly.py        # 四半期更新（財務諸表）
│   └── dividends.py        # 半年更新（配当履歴）
├── fetcher/
│   ├── fetch_all.py        # 全指標一括取得
│   ├── fundamentals.py     # 財務指標計算
│   ├── dividends.py        # 配当履歴計算
│   └── jquants/            # J-Quants V2フェッチャー
└── db.py                   # SQLite管理

rules.yaml                  # スコアリングルール定義
findex_fullscan.py          # 全銘柄フルスキャン
USAGE.md                    # 詳細な使い方・データフロー図
```

---

## データソース

- **[yfinance](https://github.com/ranaroussi/yfinance)** — 株価・財務データ（メイン）
- **[J-Quants API](https://jpx-jquants.com/)** — 日本株価データ（実装済み・オプション）
- **SQLite** — ローカルDB（`~/.findex/db/findex.db`）

---

## ライセンス

MIT
