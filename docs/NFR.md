# Findex 非機能要件設計書

> 最終更新: 2026-05-31

---

## 1. 実行モード設計

### 1-1. モード一覧

| モードID | 名称 | 用途 | 対象銘柄 |
|---|---|---|---|
| `full-scan` | フルスキャン | 初回・DB再構築時 | 全上場銘柄（約3,800社） |
| `update-all` | 差分アップデート（全体） | 毎日〜毎週の定期更新 | 全銘柄を再取得し差分があれば更新 |
| `update-subset` | 差分アップデート（部分） | 特定グループの高頻度更新 | 条件でフィルタした銘柄群 |
| `check` | 単銘柄確認 | 個別銘柄のスコア確認 | 指定コードのみ |

### 1-2. `update-subset` の組み込みグループ定義

```yaml
# subsets.yaml（組み込みグループ）
subsets:
  nikkei225:
    label: 日経225
    source: index  # 日経225構成銘柄リストから取得
  topix100:
    label: TOPIX100
    source: index
  prime-large:
    label: プライム市場・大型株（時価総額5000億円以上）
    filter:
      market: プライム
      min_market_cap: 500000000000
  prime-dividend:
    label: プライム市場・利回り3%以上
    filter:
      market: プライム
      min_div_yield: 0.03
  sector-elec:
    label: 電気機器セクター
    filter:
      sector: 電気機器
  sector-finance:
    label: 金融セクター（銀行・保険・証券）
    filter:
      sector_group: [銀行業, 保険業, 証券・商品先物取引業]
  high-score:
    label: 直近スコア上位100社
    source: cache_top  # 前回スコア結果から上位100を再チェック
    top_n: 100
```

CLIコマンド例:
```bash
findex update-subset --group nikkei225
findex update-subset --group prime-dividend
findex update-subset --group high-score
```

---

## 2. パフォーマンス要件

### 2-1. 処理時間目標

| モード | 対象銘柄数 | 目標時間 | 許容時間 |
|---|---|---|---|
| full-scan | 3,800社 | 2時間以内 | 4時間 |
| update-all | 3,800社 | 1時間以内 | 2時間 |
| update-subset (nikkei225) | 225社 | 10分以内 | 20分 |
| update-subset (prime-large) | 〜300社 | 15分以内 | 30分 |
| check（単銘柄） | 1社 | 30秒以内 | 60秒 |

### 2-2. 並列処理設計

- **デフォルト**: シングルスレッド（APIレート制限を守るため）
- **並列オプション** `--workers N`: スレッドプールで並列取得
  - yfinance: 最大 **5並列**（非公式APIのレート制限を考慮）
  - EDINET: 最大 **3並列**（公的APIへの負荷軽減）
  - デフォルト並列数: **3**

```
# 並列数の推定効果（delay=0.3秒、3並列）
3,800社 × 0.3秒 / 3並列 ≒ 6.3分（yfinance部分のみ）
```

### 2-3. API呼び出し間隔（delay）

| ソース | デフォルト | 最小 | 理由 |
|---|---|---|---|
| yfinance | 0.3秒 | 0.1秒 | 非公式API・Ban回避 |
| EDINET | 0.5秒 | 0.3秒 | 公的APIへの礼儀 |
| J-Quants | 0.2秒 | 0.1秒 | 公式API |

---

## 3. データ永続化・キャッシュ設計

### 3-1. ストレージ構成

```
~/.findex/
├── db/
│   └── findex.db              # SQLite（銘柄マスター＋スコア履歴）
├── cache/
│   ├── fundamentals/          # yfinance財務データ（銘柄別JSON、TTL=1日）
│   │   └── {code}.json
│   ├── dividends/             # yfinance配当履歴（銘柄別JSON、TTL=1日）
│   │   └── {code}.json
│   ├── roic/                  # ROIC-WACC計算結果（銘柄別JSON、TTL=1日）
│   │   └── {code}.json
│   └── edinet/                # EDINET財務データ（銘柄別JSON、TTL=永続）
│       └── {code}.json
└── logs/
    └── findex-{YYYY-MM-DD}.log
```

### 3-2. SQLiteスキーマ

```sql
PRAGMA journal_mode = WAL;   -- 読み書き並走を許可
PRAGMA foreign_keys = ON;

-- ① 銘柄マスター
CREATE TABLE IF NOT EXISTS stocks (
    code        TEXT    PRIMARY KEY,
    name        TEXT    NOT NULL,
    market      TEXT,                        -- プライム / スタンダード / グロース
    sector      TEXT,                        -- 33業種
    edinet_code TEXT,                        -- E12345形式（EDINET実装後に埋まる）
    updated_at  TEXT    NOT NULL             -- ISO8601
);

-- ② ルールバージョン管理（rules.yaml変更を自動追跡）
CREATE TABLE IF NOT EXISTS rule_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    rules_hash  TEXT    NOT NULL UNIQUE,     -- rules.yamlのSHA256（重複登録防止）
    rules_yaml  TEXT    NOT NULL,            -- rules.yamlの内容をスナップショット
    created_at  TEXT    NOT NULL
);

-- ③ スコア履歴（日次スナップショット）
CREATE TABLE IF NOT EXISTS scores (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    code             TEXT    NOT NULL,
    scored_at        TEXT    NOT NULL,       -- YYYY-MM-DD
    rule_version_id  INTEGER NOT NULL,       -- どのルールで計算したか
    total_score      REAL    NOT NULL,       -- 100点換算
    score_json       TEXT    NOT NULL,       -- {"raw":{...}, "weighted":{...}, "total":72.4}
    raw_json         TEXT,                  -- 生の財務数値（threshold変更時のrescore用）
    FOREIGN KEY (code) REFERENCES stocks(code),
    FOREIGN KEY (rule_version_id) REFERENCES rule_versions(id),
    UNIQUE (code, scored_at, rule_version_id)
);

-- ④ 実行ログ
CREATE TABLE IF NOT EXISTS run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mode        TEXT    NOT NULL,   -- full-scan / update-all / update-subset / check / rescore
    subset      TEXT,               -- update-subset時のグループ名
    started_at  TEXT    NOT NULL,
    finished_at TEXT,               -- 異常終了時はNULL
    total       INTEGER,
    succeeded   INTEGER,
    failed      INTEGER,
    skipped     INTEGER,
    exit_code   INTEGER             -- 0=成功 1=一部失敗 2=致命的エラー
);

-- ⑤ スキーマバージョン管理
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT    NOT NULL
);
INSERT OR IGNORE INTO schema_version VALUES (2, datetime('now'));
```

**インデックス**:

```sql
-- 銘柄別履歴参照・差分判定
CREATE INDEX IF NOT EXISTS idx_scores_code_date
    ON scores (code, scored_at DESC);

-- 日付別ランキング生成
CREATE INDEX IF NOT EXISTS idx_scores_date_score
    ON scores (scored_at, total_score DESC);

-- market/sectorフィルタ（update-subset用）
CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks (market);
CREATE INDEX IF NOT EXISTS idx_stocks_sector ON stocks (sector);
```

**NULLポリシー**:

| カラム種別 | ポリシー |
|---|---|
| `stocks.code` / `name` | NOT NULL（銘柄同一性に必須） |
| `scores.total_score` | NOT NULL（計算不能な銘柄はINSERTしない） |
| `scores.score_json` | NOT NULL（raw/weightedスコアを常に保持） |
| `scores.raw_json` | NULL許容（生財務数値。rescore時に利用） |
| `run_log.finished_at` | NULL許容（異常終了時に未セット） |

**ルールバージョン管理フロー**:

```python
# findex/db.py
def get_or_create_rule_version(conn, rules_path: Path) -> int:
    content = rules_path.read_text()
    rules_hash = hashlib.sha256(content.encode()).hexdigest()
    row = conn.execute(
        "SELECT id FROM rule_versions WHERE rules_hash = ?", (rules_hash,)
    ).fetchone()
    if row:
        return row[0]   # 変更なし → 既存IDを使用
    cur = conn.execute(
        "INSERT INTO rule_versions (rules_hash, rules_yaml, created_at) "
        "VALUES (?, ?, datetime('now'))",
        (rules_hash, content)
    )
    conn.commit()
    return cur.lastrowid  # 変更あり → 新バージョンを自動登録
```

**rescoreコマンド**（weight/threshold変更後の再計算）:

```bash
findex rescore --date 2026-05-31    # 指定日を最新ルールで再計算
findex rescore --codes 7203 4452    # 特定銘柄のみ
findex rescore --all                # 全履歴を最新ルールで再計算
```

| 変更内容 | 再計算に必要なデータ | コスト |
|---|---|---|
| weightのみ変更 | `score_json.raw` から再計算 | ほぼ0（DBのみ） |
| thresholdのみ変更 | `scores.raw_json`（生財務数値）から再計算 | 軽い |
| 指標の追加・入れ替え | API再取得 | 重い |
| `run_log.finished_at` | NULL許容（異常終了時に未セット） |

**マイグレーション方針**:

`schema_version` テーブルで現在バージョンを管理し、`db.py` の `migrate()` が起動時に自動適用する。

```python
# findex/db.py
MIGRATIONS = {
    1: ["CREATE TABLE IF NOT EXISTS stocks (...)", ...],
    # 2: ["ALTER TABLE scores ADD COLUMN score_new_field REAL"],
}

def migrate(conn):
    cur = conn.execute("SELECT MAX(version) FROM schema_version")
    current = cur.fetchone()[0] or 0
    for version, stmts in sorted(MIGRATIONS.items()):
        if version > current:
            for stmt in stmts:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_version VALUES (?, datetime('now'))", (version,)
            )
    conn.commit()
```

DBアクセスはORMを使わず、`findex/db.py` に生SQLのCRUDヘルパーを集約する。

### 3-3. キャッシュTTL

| fetcher | TTL | 理由 |
|---|---|---|
| 銘柄マスター（JPX） | 7日 | 上場・廃止は頻繁でない |
| fundamentals | 1日 | 四半期ごとに変化 |
| dividends | 1日 | 配当確定後に変化 |
| roic | 1日 | fundamentalsに依存 |
| edinet | 永続（`None`） | 有価証券報告書は不変 |

キャッシュのTTL基準時刻はファイルmtimeではなく、JSONエンベロープ内の `fetched_at` フィールドで管理する（rsync・バックアップでmtimeがリセットされても正しく動作するため）。

### 3-4. 差分判定ロジック（update-all / update-subset）

```python
# 同一銘柄の当日スコアが既に存在すればスキップ
existing = db.query("SELECT id FROM scores WHERE code=? AND scored_at=?", code, today)
if existing:
    continue  # スキップ

# キャッシュが有効期限内ならAPI呼び出しをスキップ
data = load_cache(fetcher="fundamentals", code=code, ttl_days=1)
if data is None:
    data = fetch_from_api(code)
    save_cache(fetcher="fundamentals", code=code, data=data)
```

---

## 4. 信頼性・エラーハンドリング設計

### 4-1. リトライ戦略

```python
@retry(
    max_attempts=3,
    wait=[1, 5, 15],   # 指数バックオフ（秒）
    on_exception=[ConnectionError, Timeout, HTTPError(429)]
)
def fetch_with_retry(code):
    ...
```

| エラー種別 | 挙動 |
|---|---|
| ネットワークタイムアウト | 3回リトライ、その後スキップして次へ |
| HTTP 429 Too Many Requests | 60秒待機後リトライ |
| HTTP 5xx | 3回リトライ |
| HTTP 4xx（404等） | 即スキップ（リトライしない） |
| データ欠損（None返却） | スコア計算から当該指標を除外して継続 |
| EDINET ZIP解析エラー | ログに記録してスキップ |

### 4-2. 部分失敗の許容

- **方針**: 1銘柄の失敗がバッチ全体を止めない
- 失敗銘柄はログに記録し、実行完了後にサマリー表示
- 失敗率が **20%超** の場合はエラーコード1で終了（APIの異常を検知）

```
[完了] 3,800銘柄処理
  成功: 3,742
  失敗:    45  ← findex run --retry-failed で再実行可能
  スキップ:  13（当日取得済み）
```

### 4-3. データ品質チェック

取得データに以下の異常値チェックを実施し、問題あればその指標をNullとして扱う:

```python
VALIDATORS = {
    "div_yield":       lambda v: 0 < v < 0.5,    # 0〜50%
    "payout_ratio":    lambda v: 0 < v < 5.0,    # 0〜500%
    "roe":             lambda v: -1.0 < v < 5.0, # -100%〜500%
    "equity_ratio":    lambda v: -1.0 < v < 1.0, # -100%〜100%
    "operating_margin":lambda v: -1.0 < v < 1.0,
    "per":             lambda v: 0 < v < 500,    # 0〜500倍
}
```

---

## 5. スケジューラー・自動実行設計

### 5-1. cronモード

```bash
# crontab への登録例
# 毎営業日 07:00 に差分アップデート（全体）
0 7 * * 1-5 findex update-all --cron >> ~/.findex/logs/cron.log 2>&1

# 毎週日曜 02:00 にフルスキャン
0 2 * * 0 findex full-scan --cron >> ~/.findex/logs/cron.log 2>&1

# 毎営業日 07:30 に日経225の差分アップデート
30 7 * * 1-5 findex update-subset --group nikkei225 --cron
```

`--cron` フラグの効果:
- 進捗バーを非表示（リッチUIを無効化、プレーンテキストで出力）
- 終了コードで成功/失敗を通知（0=成功, 1=一部失敗, 2=致命的エラー）
- 完了サマリーをログファイルに記録

### 5-2. 組み込みスケジューラー（オプション）

`findex schedule` サブコマンドで設定を保存し、バックグラウンドで実行:

```bash
findex schedule set update-all --at "07:00" --weekdays
findex schedule set full-scan  --at "02:00" --weekly sunday
findex schedule list
findex schedule run now  # 即時実行
```

---

## 6. セキュリティ設計

### 6-1. APIキー管理

| レベル | 方法 | 推奨 |
|---|---|---|
| 開発 | `.env` ファイル（gitignore済み） | ✅ 現在の実装 |
| 配布時 | 初回起動時に対話的に入力、`~/.findex/config.toml` に保存 | ✅ |
| CI/CD | 環境変数（`FINDEX_EDINET_API_KEY` 等） | ✅ |

```toml
# ~/.findex/config.toml（パーミッション 600）
[api_keys]
jquants  = "..."
edinet   = "..."
```

### 6-2. 配布時の注意事項

- `config.toml` には `chmod 600` を自動設定
- `.env` をプロジェクトルートに置く場合は必ず `.gitignore` に含める（実装済み）
- APIキーをログ・エラーメッセージに出力しない

---

## 7. 可観測性設計

### 7-1. ログ設計

```
2026-05-31 07:00:01 INFO  [run] mode=update-all target=3800
2026-05-31 07:00:05 INFO  [fetch] code=1301 source=yfinance ok
2026-05-31 07:00:05 WARN  [fetch] code=1305 div_yield=361.0 → 異常値除外
2026-05-31 07:00:06 ERROR [fetch] code=1308 ConnectionTimeout retry=1/3
2026-05-31 07:12:33 INFO  [run] done total=3800 ok=3742 fail=45 skip=13
```

ログレベル: `DEBUG` / `INFO` / `WARN` / `ERROR`  
`--verbose` フラグでDEBUGレベルを有効化

### 7-2. 進捗表示（インタラクティブ実行時）

```
Findex update-all [プライム市場]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1,842/3,800  48%  ETA 08:23
 現在処理中: 6758 ソニーグループ (yfinance)
 成功: 1,835  失敗: 7  スキップ: 0
```

---

## 8. 配布・インストール設計

### 8-1. 対象環境

| 項目 | 要件 |
|---|---|
| OS | macOS 13+, Linux（Ubuntu 22.04+） |
| Python | 3.11+ |
| パッケージ管理 | `uv`（推奨）または `pip` |
| 必要ディスク容量 | 〜500MB（SQLite DB + キャッシュ含む） |

### 8-2. インストール手順（配布想定）

```bash
# uvx で直接実行（ローカルインストール不要）
uvx findex run --help

# または pip でインストール
pip install findex-jp
findex --version

# 初回セットアップ（APIキー設定）
findex setup
# → EDINET API Key: （入力）
# → J-Quants API Key: （入力）
# → ~/.findex/config.toml を作成しました
```

### 8-3. PyPI 配布を見据えた設計

- パッケージ名: `findex-jp`（`findex` は既存パッケージのため）
- `pyproject.toml` に `[tool.uv.package] = true` を設定済み
- `findex setup` コマンドで初回セットアップを自動化
- デフォルトデータ保存先: `~/.findex/`（プロジェクトディレクトリに依存しない）

---

## 9. 非機能要件サマリー

| カテゴリ | 要件 | 目標値 |
|---|---|---|
| **性能** | 全銘柄バッチ処理 | 2時間以内 |
| **性能** | 日経225差分更新 | 10分以内 |
| **性能** | 単銘柄スコア確認 | 30秒以内 |
| **信頼性** | 単銘柄失敗の影響 | バッチ継続（スキップ） |
| **信頼性** | リトライ | 最大3回・指数バックオフ |
| **信頼性** | 異常値除外 | 指標ごとに範囲チェック |
| **データ鮮度** | 財務データキャッシュTTL | 1日 |
| **データ鮮度** | スコア更新頻度（cron） | 毎営業日 |
| **セキュリティ** | APIキー保存 | `~/.findex/config.toml`（600） |
| **可観測性** | ログ | 日次ファイル・構造化テキスト |
| **配布性** | インストール | `pip install findex-jp` 一発 |
| **配布性** | 初回設定 | `findex setup` で対話的に完結 |
