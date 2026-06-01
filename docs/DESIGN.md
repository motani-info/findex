# Findex 設計書

> 日本株スコアリング・ランキングツール  
> 最終更新: 2026-05-31（実装アーキテクチャ追記）

---

## 1. プロジェクト概要

### 目的
全上場日本株を事前定義のスコアリングルールで評価・採点し、ランキングを生成するCLIツール。
高配当株投資において「配当の安定性・増配力・財務健全性・割安度」を定量的に評価し、持続可能な増配ポートフォリオ候補を抽出する。

### 現在の実装状況
- CLIコマンド `findex run` / `findex check` が動作する状態
- yfinanceベースの6指標が実装済み
- EDINET・yfinance配当履歴による残り6指標は未実装

---

## 2. スコアリング設計

**6カテゴリー × 12指標 × 各10点満点 × weight → 100点換算**

### 計算式

```
生スコア  = min(10, 値 / threshold × 10)   # direction: high
           = min(10, threshold / 値 × 10)   # direction: low
加重スコア = 生スコア × weight
合計      = Σ(加重スコア) / max_weighted_total × 100
```

- **データ取得不可（Null）→ 生スコア 0**（分母からは除外せずペナルティとして計上）
- weightは変更可能。変更時は `raw` スコアから再計算できる（API再取得不要）

### 基本12指標（全銘柄共通）

| # | 指標 | field名 | 閾値 | dir | weight | 根拠 | データソース | 実装 |
|---|---|---|---|---|---|---|---|---|
| ① | 連続非減配年数 | `consecutive_no_cut_years` | 17年 | high | **2.0** | リーマン・コロナ耐性の最高証拠 | yfinance配当 | ❌ |
| ② | 連続増配年数 | `consecutive_dividend_growth_years` | 17年 | high | **1.5** | 経営陣の増配コミットメント | yfinance配当 | ❌ |
| ③ | 5年増配率CAGR | `dividend_growth_5y_cagr` | 30% | high | **1.0** | 複利加速度の指標 | yfinance配当 | ❌ |
| ④ | 予想配当性向 | `payout_ratio` | 35% | low | **1.5** | 配当の安全余白 | yfinance | ✅ |
| ⑤ | EPS成長率5年 | `eps_growth_5y` | 20% | high | **1.0** | 配当原資の成長性 | yfinance | ✅ |
| ⑥ | 自己資本比率 | `equity_ratio` | 80% | high | **1.2** | 財務の要塞度 | yfinance BS | ✅ |
| ⑦ | 有利子負債比率 | `debt_to_equity` | 10% | low | **0.8** | ⑥の補完・借入依存度 | EDINET BS | ❌ |
| ⑧ | ROE | `roe` | 20% | high | **1.2** | 増配パワーの源泉 | yfinance | ✅ |
| ⑨ | ROIC－WACC | `roic_minus_wacc` | 10% | high | **1.3** | 最も理論的な付加価値指標 | yfinance | ❌ |
| ⑩ | 営業利益率 | `operating_margin` | 20% | high | **1.0** | 価格決定力・競争優位 | yfinance | ✅ |
| ⑪ | 配当利回り | `div_yield` | 4.5% | high | **1.2** | 現在の受取リターン | yfinance | ✅ |
| ⑫ | ネットキャッシュPER | `net_cash_per` | 10倍 | low | **0.8** | 割安度の精緻指標 | EDINET BS | ❌ |

### 代替指標（大型株・金融株で入れ替え）

| # | 指標 | field名 | 閾値 | dir | weight | データソース | 置き換え元 | 実装 |
|---|---|---|---|---|---|---|---|---|
| ⑬ | 利益剰余金配当倍率 | `retained_earnings_div_ratio` | 10倍 | high | **1.3** | yfinance BS+info | ⑨ | ❌ |
| ⑭ | ミックス係数（PER×PBR） | `mix_coefficient` | 22.5 | low | **0.8** | yfinance info | ⑫ | ❌ |

**⑭はfundamentals.pyで既にPER・PBRを取得済みのため追加コストほぼゼロ。**  
**⑬もyfinance balance_sheet + infoで完結。**

### 動的入れ替えルール

銘柄分類の判定基準:
- **large_cap**: `market_cap >= 1,000,000,000,000`（時価総額1兆円以上）
- **financial**: `sector in ["銀行業", "保険業", "証券・商品先物取引業", "その他金融業"]`

| シナリオ | ⑥ | ⑦ | ⑨ | ⑫ |
|---|---|---|---|---|
| 通常銘柄 | 自己資本比率 ✅ | 有利子負債比率 | ROIC-WACC | ネットキャッシュPER |
| 大型株 | 自己資本比率 ✅ | 有利子負債比率 | **⑬ 利益剰余金配当倍率** | **⑭ ミックス係数** |
| 金融株 | **⑦ 有利子負債比率**（⑥除外） | — | **⑬ 利益剰余金配当倍率** | **⑭ ミックス係数** |

入れ替えてもweightが同一のため **満点は常に145点 → 100点換算**。

### 満点内訳

| カテゴリー | 指標 | 加重満点 |
|---|---|---|
| 配当安定性 | ① | 20点 |
| 増配実績 | ②③ | 15 + 10点 |
| 増配余力 | ④⑤ | 15 + 10点 |
| 財務健全性 | ⑥⑦ | 12 + 8点 |
| 競争優位性 | ⑧⑨⑩ | 12 + 13 + 10点 |
| 割安度 | ⑪⑫ | 12 + 8点 |
| **合計** | | **145点** |

### 動的入れ替えルール（将来実装）

**大型株（時価総額1兆円以上）**
| 元指標 | 代替指標 | 理由 |
|---|---|---|
| ROIC-WACC | 利益剰余金配当倍率 | 成熟企業は守備力（内部留保）を重視 |
| ネットキャッシュPER | ミックス係数（PER×PBR） | 機関投資家目線の妥当性 |

**金融銘柄（銀行・リース・保険）**
| 元指標 | 代替指標 | 理由 |
|---|---|---|
| 自己資本比率 | 有利子負債比率 | 業種特性上、自己資本比率が低く算出される |
| ROIC-WACC | 利益剰余金配当倍率 | 投下資本の定義が一般事業会社と異なる |
| ネットキャッシュPER | ミックス係数 | 銀行等でネットキャッシュ概念が成立しない |

---

## 3. データソース設計

### 3-1. 銘柄マスター

**ソース**: JPX公式Excel  
**URL**: `https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls`  
**取得フィールド**: `code`（4桁）, `name`, `market`（プライム/スタンダード/グロース）, `sector`（33業種）  
**実装**: `findex/fetcher/master.py` ✅

**補完ソース**: J-Quants API v2  
**エンドポイント**: `GET https://api.jquants.com/v2/equities/master`  
**認証**: ヘッダー `X-API-KEY: {JQUANTS_API_KEY}`  
**用途**: 市場区分の精度向上、ETF/REIT除外判定  
**APIキー**: `.env` の `JQUANTS_API_KEY`

---

### 3-2. yfinance（株価・財務速報）

**対象指標**: ④⑤⑥⑧⑩⑪ + ROIC-WACC計算材料  
**シンボル形式**: `{4桁コード}.T`（例: `7203.T`）  
**実装**: `findex/fetcher/fundamentals.py` ✅

**取得フィールド一覧**:
```python
info = yf.Ticker("7203.T").info

# 実装済み
info["payoutRatio"]          # ④ 予想配当性向
info["earningsGrowth"]       # ⑤ EPS成長率（1年）
info["returnOnEquity"]       # ⑧ ROE
info["operatingMargins"]     # ⑩ 営業利益率
info["dividendYield"]        # ⑪ 配当利回り（0〜1の小数）
balance_sheet["Stockholders Equity"]  # ⑥ 自己資本比率計算用

# ROIC-WACC計算用（未実装）
info["marketCap"]            # 時価総額
info["totalDebt"]            # 有利子負債
info["beta"]                 # β値
financials["Operating Income"]
financials["Tax Rate For Calcs"]
financials["Interest Expense Non Operating"]
balance_sheet["Stockholders Equity"]
```

**注意事項**:
- `dividendYield` が1.0超の場合は異常値として除外（実装済み）
- 大型株（トヨタ等）は `operatingIncome` が `None` になる場合あり → EDINET連携で補完

---

### 3-3. yfinance 配当履歴（①②③）

**対象指標**: ① 連続非減配年数 / ② 連続増配年数 / ③ 5年増配率CAGR  
**取得方法**:
```python
divs = yf.Ticker("7203.T").dividends  # pandas Series（日付インデックス）
```

**実績確認**:
- トヨタ: 27年分（1999〜2026）、花王: 26年分、NTT: 26年分
- 17年以上の判定が可能

**年度集計ロジック**（4月始まり日本会計年度）:
```python
fiscal_year = divs.index.map(lambda d: d.year if d.month >= 4 else d.year - 1)
annual = divs.groupby(fiscal_year).sum()
```

**連続非減配カウント**:
```python
# 直近から遡り、前年比で減っていない年数
for i in range(len(vals)-1, 0, -1):
    if vals[i] >= vals[i-1]:
        count += 1
    else:
        break
```

**5年CAGR**:
```python
cagr = (annual[-1] / annual[-6]) ** (1/5) - 1  # 5年前→現在
```

**実装先**: `findex/fetcher/dividends.py`（新規作成）

---

### 3-4. EDINET API v2（⑦⑫ + 財務精度向上）

**対象指標**: ⑦ 有利子負債比率 / ⑫ ネットキャッシュPER  
**エンドポイント**:
```
# 書類一覧API（指定日の提出書類一覧）
GET https://api.edinet-fsa.go.jp/api/v2/documents.json
  ?date=YYYY-MM-DD&type=2&Subscription-Key={EDINET_API_KEY}

# 書類取得API（財務CSVダウンロード）
GET https://api.edinet-fsa.go.jp/api/v2/documents/{docID}
  ?type=5&Subscription-Key={EDINET_API_KEY}
```

**認証**: クエリパラメータ `Subscription-Key`  
**APIキー**: `.env` の `EDINET_API_KEY`

**書類種別**: `docTypeCode=120`（有価証券報告書）、`csvFlag=1` のもの

**CSVデータ構造**（ZIPを展開したTSV）:
```
要素ID | 項目名 | コンテキストID | 相対年度 | 連結・個別 | 期間・時点 | ユニットID | 単位 | 値
```

**相対年度の対応**:
| コンテキストID | 意味 |
|---|---|
| `CurrentYearDuration` / `CurrentYearInstant` | 当期（最新） |
| `Prior1YearDuration` | 前期 |
| `Prior2YearDuration` | 前々期 |
| `Prior3YearDuration` | 三期前 |
| `Prior4YearDuration` | 四期前 |

**主要フィールドと要素ID（パターン）**:
```
自己資本比率: 項目名に "株主資本比率" or "自己資本比率" を含む
有利子負債:   BS中の社債・長期借入金等（有利子負債系列を合計）
1株配当額:    "１株当たり配当額"
EPS:          "基本的１株当たり利益"
ROE:          "親会社所有者帰属持分利益率" or "自己資本利益率"
営業利益:     要素ID "OperatingProfitLoss" or "OperatingIncome"
```

**ネットキャッシュPER計算式**:
```
ネットキャッシュ = 流動資産 + 投資有価証券×0.7 - 負債総額
ネットキャッシュ比率 = ネットキャッシュ / 時価総額
ネットキャッシュPER = PER × (1 - ネットキャッシュ比率)
```

**実装先**: `findex/fetcher/edinet.py`（新規作成）

**EDINETコード対応表**:
- JPX Excelには証券コードのみ→EDINETコードの対応が必要
- 対応表: `https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/download/ESE140190.csv`
- または `irbank.net/{code}` のリダイレクト先（`/E{5桁}/`）でEDINETコードを取得

---

### 3-5. ROIC-WACC 計算設計（⑨）

**計算式**:
```python
# ROIC
NOPAT = Operating Income × (1 - Tax Rate)
Invested Capital = Stockholders Equity + Total Debt
ROIC = NOPAT / Invested Capital

# WACC（CAPM）
Rf = 0.0265          # JGB10年利回り（2026年5月時点）※定期更新推奨
ERP = 0.065          # 日本株式リスクプレミアム（Damodaran 2026）
Re = Rf + β × ERP   # 株主資本コスト
Rd = Interest Expense / Total Debt  # 負債コスト
E = Market Cap
D = Total Debt
V = E + D
WACC = (E/V × Re) + (D/V × Rd × (1 - Tax Rate))

ROIC_minus_WACC = ROIC - WACC
```

**データソース**: yfinance `financials` / `balance_sheet` / `info`  
**精度**: 相対ランキング用途に適す（絶対値は±2〜3%の誤差あり）  
**実装先**: `findex/scorer/roic.py`（新規作成）

---

## 4. 実装アーキテクチャ

### 4-1. Fetcher層の統合インターフェース

**方針: 単純関数（`fetch_xxx(codes) → DataFrame`）、cli.py/runner.py側でmerge**

- 各fetcher は `fetch_xxx(codes: list[str], ...) -> pd.DataFrame` を返す統一シグネチャ
- Protocol抽象化は行わない（fetcherの種類が増える見込みがなく、過剰設計となるため）
- `runner.py` がfetcherを順に呼び出し、コードをキーにmergeする

```python
# findex/runner.py での統合イメージ
fetchers = [fetch_fundamentals, fetch_dividends, fetch_roic, fetch_edinet]
df = master
for fetch in fetchers:
    df = df.merge(fetch(codes, settings=settings), on="code", how="left")
```

---

### 4-2. キャッシュ層の実装方式

**方針: `cache.py` 共通ヘルパー関数 + 各fetcherが内部で呼び出す**

- `findex/cache.py` にキャッシュ読み書きのヘルパー関数を定義
- デコレータ方式は採用しない（TTLとキャッシュキーの粒度がfetcherごとに異なるため）
- キャッシュ保存先: `~/.findex/cache/{fetcher_name}/{code}.json`

```python
# findex/cache.py
CACHE_DIR = Path.home() / ".findex" / "cache"

def load_cache(key: str, ttl_days: int) -> dict | None:
    """キャッシュが有効期限内なら返す。期限切れまたは存在しない場合はNone"""
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    age = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days
    return json.loads(path.read_text()) if age < ttl_days else None

def save_cache(key: str, data: dict) -> None:
    path = CACHE_DIR / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, default=str))
```

各fetcherでの使用例:
```python
# fetcher/dividends.py
cached = load_cache(f"div_{code}", ttl_days=1)
if cached:
    return cached
data = yf.Ticker(f"{code}.T").dividends
save_cache(f"div_{code}", {"dividends": data.to_dict()})
```

---

### 4-3. 並列処理の実装

**方針: `ThreadPoolExecutor`（デフォルト: シングルスレッド、`--workers N` で並列化）**

- asyncioは採用しない（yfinanceが非対応かつ移行コストが高いため）
- デフォルトはシングルスレッド（APIレート制限・Ban回避を優先）
- `--workers N` 指定時のみ並列化
  - yfinance: 最大5並列
  - EDINET: 最大3並列

```python
# fetcher/fundamentals.py
from concurrent.futures import ThreadPoolExecutor

def fetch_fundamentals(codes: list[str], delay: float = 0.5, workers: int = 1) -> pd.DataFrame:
    if workers == 1:
        return pd.DataFrame([_fetch_one(c, delay) for c in codes])
    with ThreadPoolExecutor(max_workers=min(workers, 5)) as ex:
        results = list(ex.map(lambda c: _fetch_one(c, delay), codes))
    return pd.DataFrame(results)
```

---

### 4-4. 実行結果オブジェクト

**方針: `RunResult` dataclass（`runner.py` で定義）**

- スコアDataFrameはスコアのみを持つ（statusフィールドを混在させない）
- 成功・失敗・スキップ銘柄は `RunResult` で管理
- `cli.py` は `RunResult` を受け取り、表示・ログ出力・終了コードをまとめて処理

```python
# findex/runner.py
from dataclasses import dataclass, field

@dataclass
class RunResult:
    scores: pd.DataFrame
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)   # code → エラーメッセージ
    skipped: list[str] = field(default_factory=list)

    @property
    def fail_rate(self) -> float:
        total = len(self.succeeded) + len(self.failed) + len(self.skipped)
        return len(self.failed) / total if total else 0.0

    def summary(self) -> str:
        return (f"完了: 成功={len(self.succeeded)} "
                f"失敗={len(self.failed)} スキップ={len(self.skipped)}")
```

失敗率が20%超の場合は終了コード1で終了（APIの異常を検知）。

---

### 4-5. 設定管理（config.toml）

**方針: `Settings.load()` でロード → Click contextで各コマンドに伝搬**

- グローバルシングルトンは採用しない（テスト時の状態リセットが困難になるため）
- 読み込み優先順位: **環境変数 > `~/.findex/config.toml` > `.env`**
- Click contextを通じてサブコマンドに設定を渡す

```python
# findex/settings.py
from dataclasses import dataclass
from pathlib import Path
import tomllib, os
from dotenv import load_dotenv

CONFIG_PATH = Path.home() / ".findex" / "config.toml"

@dataclass
class Settings:
    edinet_api_key: str = ""
    jquants_api_key: str = ""

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        cfg = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "rb") as f:
                cfg = tomllib.load(f).get("api_keys", {})
        return cls(
            edinet_api_key=os.getenv("EDINET_API_KEY", cfg.get("edinet", "")),
            jquants_api_key=os.getenv("JQUANTS_API_KEY", cfg.get("jquants", "")),
        )

# findex/cli.py
@click.group()
@click.pass_context
def cli(ctx):
    ctx.ensure_object(dict)
    ctx.obj["settings"] = Settings.load()
```

---

### 4-6. 動的指標入れ替えルール

**方針: v2以降に先送り**

- 大型株（時価総額1兆円以上）・金融銘柄の指標入れ替えロジックは初期実装に含めない
- v1.0は全銘柄を同一ルールで評価
- `rules.yaml` の末尾にコメントとして設計を保存済み（実装時に参照）

---

## 5. ディレクトリ構成

```
findex/
├── findex/
│   ├── fetcher/
│   │   ├── master.py          ✅ JPX銘柄マスター
│   │   ├── fundamentals.py    ✅ yfinance財務指標（④⑤⑥⑧⑩⑪）
│   │   ├── dividends.py       ❌ yfinance配当履歴（①②③）
│   │   └── edinet.py          ❌ EDINET財務データ（⑦⑫）
│   ├── scorer/
│   │   ├── engine.py          ✅ スコアリングエンジン
│   │   └── roic.py            ❌ ROIC-WACC計算（⑨）
│   ├── output/
│   │   └── display.py         ✅ Rich表示・CSV出力
│   ├── cache.py               ❌ キャッシュ読み書きヘルパー（§4-2）
│   ├── settings.py            ❌ 設定管理 Settings.load()（§4-5）
│   ├── runner.py              ❌ RunResult dataclass + バッチ実行ロジック（§4-4）
│   └── cli.py                 ✅ CLIエントリーポイント（→ runner.py統合後に更新）
├── rules.yaml                 ✅ スコアリングルール定義
├── .env                       ✅ APIキー（gitignore済み）
├── pyproject.toml             ✅
└── docs/
    ├── DESIGN.md              ✅ 本設計書
    └── NFR.md                 ✅ 非機能要件設計書
```

---

## 6. スキーマ設計

### 6-1. Fetcherが返すDataFrameの列定義

全fetcherは `code`（4桁文字列）を必ず返す。`runner.py` が `on="code", how="left"` でmerge。

| fetcher | 列名 | 型 | Null許容 | 対応指標 |
|---|---|---|---|---|
| **master.py** | `code` | `str` | NO | — |
| | `name` | `str` | NO | — |
| | `market` | `str` | YES | — |
| | `sector` | `str` | YES | — |
| **fundamentals.py** | `payout_ratio` | `float` | YES | ④ |
| | `eps_growth_5y` | `float` | YES | ⑤ |
| | `equity_ratio` | `float` | YES | ⑥ |
| | `roe` | `float` | YES | ⑧ |
| | `operating_margin` | `float` | YES | ⑩ |
| | `div_yield` | `float` | YES | ⑪ |
| | `per` | `float` | YES | 参考 |
| | `pbr` | `float` | YES | 参考 |
| | `market_cap` | `float` | YES | 参考（ROIC-WACCでも使用） |
| **dividends.py** | `consecutive_no_cut_years` | `int` | YES | ① |
| | `consecutive_dividend_growth_years` | `int` | YES | ② |
| | `dividend_growth_5y_cagr` | `float` | YES | ③ |
| **roic.py** | `roic_minus_wacc` | `float` | YES | ⑨ |
| **edinet.py** | `debt_to_equity` | `float` | YES | ⑦ |
| | `net_cash_per` | `float` | YES | ⑫ |

**値の単位・スケール規約**:

| 種別 | 規約 | 例 |
|---|---|---|
| 比率・利率 | 小数（1.0 = 100%） | `div_yield=0.045`、`roe=0.20` |
| 年数 | 整数 | `consecutive_no_cut_years=17` |
| CAGR | 小数 | `dividend_growth_5y_cagr=0.30` |
| 倍率（PER等） | 実数 | `per=15.2`、`net_cash_per=8.5` |
| 金額 | 円（float） | `market_cap=5000000000000` |

この規約は `rules.yaml` の `threshold` 値と整合する（`threshold: 0.045` = 4.5%）。

**異常値バリデーション**（各fetcherの責務。範囲外はNullに置き換える）:

```python
VALIDATORS = {
    "div_yield":                  lambda v: 0 < v < 0.50,
    "payout_ratio":               lambda v: 0 < v < 5.0,
    "roe":                        lambda v: -1.0 < v < 5.0,
    "equity_ratio":               lambda v: -1.0 < v < 1.0,
    "operating_margin":           lambda v: -1.0 < v < 1.0,
    "eps_growth_5y":              lambda v: -1.0 < v < 5.0,
    "per":                        lambda v: 0 < v < 500,
    "net_cash_per":               lambda v: -500 < v < 500,
    "debt_to_equity":             lambda v: 0 <= v < 100,
    "dividend_growth_5y_cagr":    lambda v: -0.5 < v < 5.0,
}
```

---

### 6-2. score_jsonの構造

`scores.score_json` に **生スコア（raw）と加重スコア（weighted）を分離して保存**する。

```json
{
  "raw": {
    "consecutive_no_cut_years":          10.0,
    "consecutive_dividend_growth_years": 10.0,
    "dividend_growth_5y_cagr":            2.6,
    "payout_ratio":                       9.1,
    "eps_growth_5y":                      4.0,
    "equity_ratio":                       5.5,
    "debt_to_equity":                     0,
    "roe":                                6.0,
    "roic_minus_wacc":                    0,
    "operating_margin":                   7.3,
    "div_yield":                          8.2,
    "net_cash_per":                       0
  },
  "weighted": {
    "consecutive_no_cut_years":          20.0,
    "consecutive_dividend_growth_years": 15.0,
    "dividend_growth_5y_cagr":            2.6,
    "payout_ratio":                      13.65,
    "eps_growth_5y":                      4.0,
    "equity_ratio":                       6.6,
    "debt_to_equity":                     0,
    "roe":                                7.2,
    "roic_minus_wacc":                    0,
    "operating_margin":                   7.3,
    "div_yield":                          9.84,
    "net_cash_per":                       0
  },
  "total": 59.1,
  "max_weighted_total": 145.0
}
```

- `raw`: 0〜10の生スコア。データ取得不可は `0`
- `weighted`: `raw × weight` の値
- `total`: `Σ(weighted) / max_weighted_total × 100`

**再スコアの粒度**（変更コストの低い順）:

| 変更内容 | 再計算に必要なデータ | コスト |
|---|---|---|
| weightのみ変更 | `score_json.raw` から再計算 | ほぼ0（DBのみ） |
| thresholdのみ変更 | `scores.raw_json`（生の財務数値）から再計算 | 軽い |
| 指標の追加・入れ替え | API再取得 | 重い |

---

### 6-3. キャッシュJSONの構造

保存先: `~/.findex/cache/{fetcher}/{code}.json`

**全fetcher共通エンベロープ**:

```json
{
  "version": 1,
  "fetcher": "dividends",
  "code": "4452",
  "fetched_at": "2026-05-31T07:00:00",
  "data": { ... }
}
```

`fetched_at` をファイルmtimeでなく内部に保持する理由: rsync・バックアップでmtimeがリセットされてもTTL判定が正しく機能する。

**fetcher別 `data` ペイロード**:

```json
// fundamentals
{"payout_ratio": 0.38, "eps_growth_5y": 0.12, "equity_ratio": 0.72,
 "roe": 0.18, "operating_margin": 0.15, "div_yield": 0.032,
 "per": 14.5, "pbr": 2.1, "market_cap": 5000000000000}

// dividends
{"consecutive_no_cut_years": 26, "consecutive_dividend_growth_years": 26,
 "dividend_growth_5y_cagr": 0.08}

// roic（_debugは検証用）
{"roic_minus_wacc": 0.054, "_debug": {"roic": 0.089, "wacc": 0.035, "beta": 0.82}}

// edinet（TTL=永続、doc_idを追加保持）
{"debt_to_equity": 0.04, "net_cash_per": 7.2,
 "_debug": {"interest_bearing_debt": 12000000000, "equity": 280000000000,
            "current_assets": 350000000000, "total_liabilities": 180000000000}}
```

**TTL設定**:

| fetcher | TTL | 理由 |
|---|---|---|
| fundamentals | 1日 | 四半期ごとに変化 |
| dividends | 1日 | 配当確定後に変化 |
| roic | 1日 | fundamentalsに依存 |
| edinet | 永続（`None`） | 有価証券報告書は不変 |

---

## 7. 環境変数・設定

### 開発時（.env）

```env
JQUANTS_API_KEY=your_jquants_api_key_here
EDINET_API_KEY=your_edinet_api_key_here
```

### 配布時（~/.findex/config.toml、権限 600）

```toml
[api_keys]
jquants = "..."
edinet  = "..."
```

読み込み優先順位: **環境変数 > `~/.findex/config.toml` > `.env`**（§4-5参照）

---

## 8. 実装タスク（優先順位順）

### Task 0: 基盤モジュール整備
**ファイル**: `findex/settings.py`、`findex/cache.py`、`findex/runner.py`（新規）

| ファイル | 内容 | 参照 |
|---|---|---|
| `settings.py` | `Settings.load()` / `CONFIG_PATH` | §4-5 |
| `cache.py` | `load_cache()` / `save_cache()` | §4-2 |
| `runner.py` | `RunResult` dataclass / バッチ実行ロジック | §4-4 |

`cli.py` を `Settings` と `RunResult` を使う形に更新する。

---

### Task 1: 配当履歴フェッチャー実装
**ファイル**: `findex/fetcher/dividends.py`（新規）  
**内容**:
- `fetch_dividends(codes, delay, workers) -> DataFrame` → コード単位で①②③を計算して返す
- yfinance `.dividends` から年度集計（4月始まり）→ 連続非減配・連続増配・5年CAGR
- `cache.py` で `ttl_days=1` のキャッシュを利用
- `rules.yaml` の ①②③ を `available: true` に変更

**検証済みロジック**: 本設計書 §3-3 参照

---

### Task 2: ROIC-WACC・代替指標計算実装
**ファイル**: `findex/scorer/roic.py`（新規）  
**内容**:
- `fetch_roic(codes, delay, workers) -> DataFrame` → ⑨⑬⑭を返す
  - ⑨ `roic_minus_wacc`: ROIC - WACC（CAPM）
  - ⑬ `retained_earnings_div_ratio`: 利益剰余金 / 年間配当総額
  - ⑭ `mix_coefficient`: PER × PBR（fundamentals取得済みの値を使用）
- Rf=0.0265、ERP=0.065 を定数として定義（コメントで更新時期を記載）
- `cache.py` で `ttl_days=1` のキャッシュを利用
- `rules.yaml` の ⑨ を `available: true` に変更（⑬⑭は動的ルール実装後に有効化）

**計算式**: 本設計書 §3-5 参照

---

### Task 3: EDINET フェッチャー実装
**ファイル**: `findex/fetcher/edinet.py`（新規）  
**内容**:
- `fetch_edinet(codes, settings, delay, workers) -> DataFrame` → ⑦⑫を返す
- `fetch_edinet_code_map()` → 証券コード↔EDINETコード対応表の取得・キャッシュ
- `find_latest_doc_id(edinet_code)` → 書類一覧APIで最新の有価証券報告書docIDを取得
- `fetch_financial_csv(doc_id)` → ZIPダウンロード・TSV解析
- EDINETキャッシュは `ttl_days=永続`（有価証券報告書は変更されない）
- `rules.yaml` の ⑦⑫ を `available: true` に変更

**EDINET API仕様**: 本設計書 §3-4 参照

---

### Task 4: runner.py / cli.py 統合・動的ルール実装
**ファイル**: `findex/runner.py`、`findex/cli.py`、`findex/scorer/engine.py`  
**内容**:
- `runner.py` にバッチ実行ロジックを集約（Task 0〜3のfetcherを順に呼び出し・merge）
- `cli.py` は `runner.py` を呼び出すだけのシンな構造に整理
- **動的ルール選択ロジック**: 銘柄ごとに `large_cap` / `financial` を判定し適用ルールを切り替え
  - `market_cap >= 1兆円` → ⑨→⑬、⑫→⑭
  - `sector in 金融業種リスト` → ⑥→⑦（除外）、⑨→⑬、⑫→⑭
- `rules.yaml` の ⑬⑭ を `available: true` に変更
- `--no-edinet` / `--workers N` / `--refresh` フラグ追加
- `rich.progress` で銘柄取得の進行状況を表示

---

## 9. モジュール詳細設計

### 9-1. scorer/engine.py 改修仕様

**改修ポイント**:

| 項目 | 旧仕様 | 新仕様 |
|---|---|---|
| Null処理 | スキップ（分母除外） | **0点として計上** |
| weight | なし | `rule["weight"]` を乗算 |
| 動的ルール | なし | `market_cap` / `sector` で適用ルールを切り替え |
| 出力 | `total_score` 列 | `score_json`（raw/weighted/total）を生成 |

**公開API**:

```python
FINANCIAL_SECTORS = {"銀行業", "保険業", "証券・商品先物取引業", "その他金融業"}

def select_rules(rules: list[dict], market_cap: float | None, sector: str | None) -> list[dict]:
    """銘柄属性に応じて適用ルールセットを返す。
    - large_cap（1兆円以上）: ⑨→⑬、⑫→⑭
    - financial: ⑥除外、⑨→⑬、⑫→⑭
    - available=false のルールは常に除外
    """

def score_one(raw: dict, rules: list[dict]) -> dict:
    """1銘柄のスコアを計算。Null → 0点。
    Returns: {"raw": {...}, "weighted": {...}, "total": 72.4, "max_weighted_total": 145.0}
    """

def score(df: pd.DataFrame, rules: list[dict]) -> pd.DataFrame:
    """DataFrameの全銘柄をスコアリング。
    行ごとに select_rules() → score_one() を呼び出し、
    total_score 降順にソートして返す。
    """
```

**動的ルール選択ロジック**:

```python
def select_rules(rules, market_cap, sector):
    is_large_cap = market_cap and market_cap >= 1_000_000_000_000
    is_financial = sector in FINANCIAL_SECTORS

    replaced_fields = set()
    active = []

    # Step1: 代替指標を評価（applies_toが一致するもの）
    for rule in rules:
        if not rule.get("available", True): continue
        applies_to = rule.get("applies_to", [])
        if not applies_to: continue
        if (is_large_cap and "large_cap" in applies_to) or \
           (is_financial  and "financial"  in applies_to):
            active.append(rule)
            replaced_fields.add(rule["replaces"])

    # Step2: 基本指標（置き換えられていないものを追加）
    for rule in rules:
        if not rule.get("available", True): continue
        if rule.get("applies_to"): continue
        if rule["field"] in replaced_fields: continue
        if is_financial and rule["field"] == "equity_ratio": continue
        active.append(rule)

    return active
```

---

### 9-2. db.py CRUD API

**ファイル**: `findex/db.py`

```python
# 接続・初期化
def get_db(settings: Settings) -> sqlite3.Connection:
    """DB接続を返す。初回はmigrate()を実行"""

def migrate(conn) -> None:
    """MIGRATIONSを順に適用してスキーマを最新化"""

# rule_versions
def get_or_create_rule_version(conn, rules_path: Path) -> int:
    """rules.yamlのSHA256で検索。なければINSERT。IDを返す"""

# stocks
def upsert_stocks(conn, df: pd.DataFrame) -> None:
    """銘柄マスターをINSERT OR REPLACE"""

def get_stock_codes(conn, market=None, sector=None) -> list[str]:
    """条件フィルタ済みの銘柄コード一覧を返す"""

# scores（書き込み）
def insert_score(conn, code: str, scored_at: str,
                 rule_version_id: int, score_json: dict, raw_json: dict) -> None:
    """スコアをINSERT。UNIQUE制約違反は無視（差分スキップ）"""

def score_exists(conn, code: str, scored_at: str, rule_version_id: int) -> bool:
    """当日・同ルールのスコアが既存か確認（差分スキップ用）"""

# scores（読み込み）
def get_latest_scores(conn, scored_at: str, top_n: int = None) -> pd.DataFrame:
    """指定日のスコア一覧をtotal_score降順で返す"""

def get_score_history(conn, code: str) -> pd.DataFrame:
    """銘柄の全スコア履歴を返す"""

# rescore用
def get_records_for_rescore(conn, scored_at: str = None,
                             codes: list[str] = None) -> list[dict]:
    """(id, code, scored_at, score_json, raw_json) のリストを返す"""

def update_score(conn, record_id: int, rule_version_id: int,
                 score_json: dict, total_score: float) -> None:
    """rescoreで再計算したスコアで上書き"""

# run_log
def start_run(conn, mode: str, subset: str = None) -> int:
    """run_logにINSERT。run_idを返す"""

def finish_run(conn, run_id: int, result: "RunResult", exit_code: int) -> None:
    """run_logのfinished_at・集計値を更新"""
```

---

### 9-3. findex rescore 詳細フロー

**コマンド**:
```bash
findex rescore --date 2026-05-31   # 指定日を最新ルールで再計算
findex rescore --codes 7203 4452   # 特定銘柄のみ
findex rescore --all               # 全履歴を最新ルールで再計算
```

**処理フロー**:

```
① rules.yaml を読み込み、get_or_create_rule_version() で新バージョンID取得

② get_records_for_rescore() で対象レコードを取得

③ 旧バージョンと新バージョンの rules.yaml を比較して変更種別を判定:
   ┌─ weightのみ変更
   │    → score_json["raw"] から再計算（raw_json不要・DBのみで完結）
   └─ threshold変更 or 指標追加
        → raw_json の財務数値から再計算
        └─ raw_json が NULL のレコードはスキップ（次回 findex run で取得）

④ score_one() で再計算

⑤ update_score() で新バージョンIDとともに上書き保存
   （旧スコアは旧 rule_version_id で保持され消えない）

⑥ 完了サマリーを表示:
   [rescore完了] 対象: 3,800件  成功: 3,756件  スキップ: 44件（raw_jsonなし）
   新ルールバージョン: v3
```

**変更種別の判定方法**:

```python
def detect_change_type(old_yaml: str, new_yaml: str) -> str:
    """'weight_only' | 'threshold' | 'field_change' のいずれかを返す"""
    old_rules = {r["field"]: r for r in yaml.safe_load(old_yaml)["rules"]}
    new_rules = {r["field"]: r for r in yaml.safe_load(new_yaml)["rules"]}

    if set(old_rules) != set(new_rules):
        return "field_change"   # 指標の追加・削除
    for field, new_r in new_rules.items():
        old_r = old_rules[field]
        if old_r.get("threshold") != new_r.get("threshold"):
            return "threshold"  # thresholdが変わった
    return "weight_only"        # weightのみの変更
```

---

## 10. CLIの使い方（実装完了後）

```bash
# プライム市場の高配当株ランキング（上位50社）
uv run findex run --market プライム --no-etf --top 50

# 特定銘柄のスコア詳細確認
uv run findex check 7203 4452 9432

# 全指標有効でCSV出力
uv run findex run --market プライム --no-etf --out ranking.csv

# EDINETスキップ（高速モード）
uv run findex run --market プライム --no-etf --no-edinet --top 30

# 電気機器セクターのみ
uv run findex run --sector 電気機器 --top 20

# 並列取得（3並列）でキャッシュをリフレッシュ
uv run findex run --market プライム --no-etf --workers 3 --refresh
```

---

## 11. 既知の制約・注意事項

| 項目 | 内容 |
|---|---|
| yfinance レート制限 | `--delay 0.5`（デフォルト）で1銘柄0.5秒待機。全銘柄（約3800社）で約30分 |
| 大型株のfundamentals欠損 | トヨタ等は `operatingIncome` がNullになる場合あり。EDINETで補完 |
| 配当履歴の株式分割 | yfinanceは分割調整済みの配当額を返すため、連続増配判定に注意 |
| EDINET XBRL形式 | IFRS適用企業と日本基準で要素ID（field名）が異なる |
| 一過性利益による歪み | 資産売却益等で配当性向が一時的に低下する銘柄は過大評価される場合あり |
| 金融銘柄の特殊性 | 銀行・保険は自己資本比率が低くスコアが歪む → 動的入れ替えルール（v2以降） |
| EDINET APIキー | 金融庁Azureポータルで発行。Safariで取得成功（Chromeは白画面になる場合あり） |
