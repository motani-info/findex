# 設計: テーブル定義（データモデル）

**作成日**: 2026-06-14
**正本**: `findex/db/schema.sql`（このドキュメントは解説。DDLの一次情報はSQLファイル）
**関連**: [requirements.md](../requirements.md) §7 / [pre2000-data.md](pre2000-data.md) §4 / [data-workflow.md](data-workflow.md)

---

## 0. 設計原則（再掲）

1. **一方向フロー**: 取得層 → 導出層 → 評価層 → 出力層。後段は前段のテーブルだけを読む
2. **粒度別テーブル**: 年間配当（FY粒度）とイベント配当（権利落ち日粒度）を混ぜない（地雷1）
3. **計算は導出層に集約**: ストリーク・CAGR等の計算結果は `computed_metrics` にのみ書く
4. **source と更新時刻**: すべての行に「どこから来たか」「いつ更新したか」を持たせる
5. **履歴を消さない**: 財務・スコアは年度別/日付別に積む（1行上書き禁止）

### テーブル一覧と層の対応

| 層 | テーブル | 粒度 | 役割 |
|---|---|---|---|
| 取得 | `stocks` | 1銘柄1行 | 銘柄マスター（上場日・設立日を含む） |
| 取得 | `price_history` | 銘柄×日 | 調整後終値 |
| 取得 | `dividend_events` | 銘柄×権利落ち日 | 配当イベント生データ |
| 取得 | `dividend_annual` | 銘柄×会計年度 | 年間配当の正準系列 |
| 取得 | `financial_snapshots` | 銘柄×会計年度 | 財務諸表スナップショット |
| 取得 | `streak_overrides` | 1銘柄1行 | 公表値による手動補正 |
| 導出 | `computed_metrics` | 1銘柄1行 | 全派生指標の唯一の出口 |
| 評価 | `dividend_scores` | 銘柄×採点日 | スコア履歴 |
| 評価 | `rule_versions` | 1ルール1行 | rules.yaml のバージョン管理 |
| 出力 | `post_log` | 1投稿1行 | X投稿履歴（二重投稿防止） |
| 運用 | `run_log` | 1ジョブ1行 | バッチ実行ログ |
| 運用 | `schema_version` | 1行 | スキーマ世代 |

---

## 1. `stocks` — 銘柄マスター

**役割**: 全上場普通株（約3,750）の不変・準不変情報。`listing_date`/`founded_date` が2000年問題の打ち切り判定に必須。
**source**: JPX公式Excel（コード/名称/市場/業種）、kabutan（上場日・設立日）。
**更新頻度**: 月次（マスター）、初回1回（上場日・設立日は不変）。

| カラム | 型 | 説明 |
|---|---|---|
| `code` | TEXT PK | 4桁証券コード |
| `name` | TEXT | 銘柄名 |
| `market` | TEXT | プライム/スタンダード/グロース/名証 等 |
| `sector` | TEXT | 33業種 |
| `edinet_code` | TEXT | EDINETコード（財務クロスチェック用） |
| `listing_date` | TEXT | **上場年月日**（kabutan等）。打ち切り判定の独立シグナル。地雷7 |
| `founded_date` | TEXT | 設立年月日（補助） |
| `first_data_date` | TEXT | DB内最古データ日（**導出値**。単独では打ち切り判定不可） |
| `is_active` | INTEGER | 1=現役。上場廃止は0 |
| `updated_at` | TEXT | 更新時刻 |

**インデックス**: `market`, `sector`。
**地雷メモ**: `first_data_date` は「自分の持つデータの下限」であり「会社の年齢」ではない。`listing_date` と必ず併用する（旧実装は `listing_date` が0%で打ち切りに気づけなかった）。

---

## 2. `price_history` — 株価履歴

**役割**: 調整後終値。配当利回り・PER・PBR・時価総額・モメンタムの原資。
**source**: yfinance `yf.download`（将来J-Quants）。**更新頻度**: 日次（平日）。

| カラム | 型 | 説明 |
|---|---|---|
| `code` | TEXT | 証券コード |
| `date` | TEXT | 日付（YYYY-MM-DD） |
| `close` | REAL | 調整後終値 |
| `volume` | INTEGER | 出来高 |

**PK**: (`code`, `date`)。
**運用メモ**: 日次は最新2日分のみ取得して追記（全期間再取得しない）。yfinanceは2並列上限・バッチ間スリープ必須。

---

## 3. `dividend_events` — 配当イベント（生データ）

**役割**: 権利落ち日ベースの**実イベント**のみ。`dividend_annual` の events ソースを構築する原料。
**source**: yfinance `Ticker.dividends`（分割調整済み、1999年9月以降）。**更新頻度**: 半年。

| カラム | 型 | 説明 |
|---|---|---|
| `code` | TEXT | 証券コード |
| `ex_date` | TEXT | 権利落ち日 |
| `amount` | REAL | 分割調整済み1株配当 |
| `source` | TEXT | 既定 'yfinance' |

**PK**: (`code`, `ex_date`)。
**地雷メモ（最重要）**:
- **合成レコードを入れてはならない**（地雷1）。「年間配当を期末日付の偽イベント」として入れると会計年度シームで偽の減配が発生する。年間値は `dividend_annual` に直接入れる
- 同一日に複数回配当（特別配当）があるとPKで潰れる。必要ならPKに kind を足す
- 1999年以前は存在しない → 長期ストリークは `dividend_annual` のバックフィルで補う

---

## 4. `dividend_annual` — 会計年度別配当（正準系列）⭐

**役割**: **ストリーク・配当CAGRはこのテーブルだけから計算する**。findexの正確性の心臓部。
**source**: `events`（dividend_eventsから構築）/ `haitoukin`（2000年以前バックフィル）/ `ir`（各社IR）/ `manual`（手入力）。
**更新頻度**: events は半年（再構築）、backfill系は随時。

| カラム | 型 | 説明 |
|---|---|---|
| `code` | TEXT | 証券コード |
| `fiscal_year` | INTEGER | **4月始まり会計年度**（地雷2）。`fy = year if month>=4 else year-1` |
| `dps` | REAL | その年度の年間1株配当（分割調整済み） |
| `source` | TEXT | 'events'\|'haitoukin'\|'ir'\|'manual' |
| `updated_at` | TEXT | 更新時刻 |

**PK**: (`code`, `fiscal_year`)。**インデックス**: (`code`, `fiscal_year`)。
**優先順位（同一年度で競合時）**: `manual` > `ir` > `haitoukin` > `events`（手動の確定値を機械再構築で潰さない）。
**地雷メモ**:
- 暦年でなく**会計年度**で集計（決算期変更でも壊れない。地雷2）
- イベントの最初の会計年度は期中開始の可能性があるため**捨てる**（`first_complete_fy = min(events_fy)+1`。地雷1）。捨てた分はバックフィルで埋める
- 分割調整基準がソース間で不一致な銘柄（NTT/SBG/電通総研）は境界異常チェックで弾き、override で対処（地雷3）

---

## 5. `streak_overrides` — 公表値オーバーライド

**役割**: 機械計算と公表値の定義差（±1〜2年）を補正（地雷5）。**公表値 > 機械計算 のときだけ昇格**。
**source**: ダイヤモンドZAi・みんかぶ・各社IR。**更新頻度**: 随時（手動）。

| カラム | 型 | 説明 |
|---|---|---|
| `code` | TEXT PK | 証券コード |
| `growth_years` | INTEGER | 公表 連続増配年数（NULL=上書きしない） |
| `nocut_years` | INTEGER | 公表 連続非減配年数（NULL=上書きしない） |
| `as_of_fiscal_year` | INTEGER | 公表値の基準年度 |
| `source_url` | TEXT | 出典URL |
| `verified_at` | TEXT | 確認日時 |

**地雷メモ**: 古い公表値で機械計算を**下げてはいけない**（昇格のみ）。合併銘柄（三菱HC・アステラス）の過去連続性はデータ上フィクションなので必ずoverrideで扱う。現在12銘柄登録済み。

---

## 6. `financial_snapshots` — 年度別財務スナップショット

**役割**: ROE・自己資本比率・FCF・EPS等の原データを**年度別に履歴保持**（旧実装は1行上書きで履歴が消えた）。
**source**: yfinance `info`/`financials`/`balance_sheet`、EDINET（検証）。**更新頻度**: 四半期（TTL 90日）。

| カラム | 型 | 説明 |
|---|---|---|
| `code`, `fiscal_year` | TEXT, INTEGER | PK |
| `eps`, `bps`, `shares` | REAL | 1株指標・株数 |
| `roe`, `operating_margin`, `equity_ratio`, `debt_to_equity`, `payout_ratio` | REAL | 収益性・健全性 |
| `free_cashflow`, `operating_cashflow`, `capex` | REAL | キャッシュフロー（FCFカバレッジ用） |
| `total_assets`, `stockholders_equity`, `retained_earnings` | REAL | BS項目（利益剰余金配当倍率用） |
| `revenue`, `market_cap`, `beta` | REAL | 売上・時価総額・β |
| `source` | TEXT | 既定 'yfinance' |
| `fetched_at` | TEXT | 取得時刻（TTL判定用） |

**PK**: (`code`, `fiscal_year`)。
**地雷メモ**: yfinance の info キーは不安定（EPSは dilutedEPS→trailingEps→forwardEps でフォールバック）。欠損多数を前提に、EDINETでクロスチェックする設計。

---

## 7. `computed_metrics` — 派生指標（導出層の唯一の出口）⭐

**役割**: 前段テーブルから計算した全派生指標を1銘柄1行（最新値）で保持。スコアラはここだけを読む。
**source**: 導出層（`dividend_annual`+`streak_overrides`+`financial_snapshots`+`price_history`+`stocks`）。**更新頻度**: 価格由来は日次、財務由来は四半期、配当由来は半年（カラム別の `*_computed_at` で管理）。

| 区分 | カラム |
|---|---|
| 価格由来（日次） | `per`, `pbr`, `current_market_cap`, `div_yield`, `mix_coefficient`, `net_cash_per` |
| 財務由来（四半期） | `equity_ratio`, `debt_to_equity`, `roe`, `operating_margin`, `eps_growth_5y`, `revenue_growth_5y_cagr`, `roic_minus_wacc`, `fcf_payout_coverage`, `retained_earnings_div_ratio`, `payout_ratio` |
| 配当由来（半年） | `annual_div`, `consecutive_no_cut_years`, `consecutive_dividend_growth_years`, **`streak_is_censored`**, `dividend_growth_5y_cagr`, `dividend_growth_10y_cagr`, `dividend_reliability`, `dividend_cut_count_20y` |
| 更新時刻 | `price_computed_at`, `fin_computed_at`, `div_computed_at` |

**PK**: `code`。
**最重要カラム**: `streak_is_censored`（1=「N年以上」表示）。これが立っている銘柄を裸の数字で投稿してはならない（品質ゲートで担保）。

---

## 8. `dividend_scores` — スコア履歴

**役割**: 採点結果を日付別に積む（バックテスト・推移分析）。
**source**: 評価層（`computed_metrics` + `rules.yaml`）。**更新頻度**: 日次（再スコアリング）。

| カラム | 型 | 説明 |
|---|---|---|
| `code`, `scored_at` | TEXT | PK |
| `rule_version_id` | INTEGER | `rule_versions.id` への参照 |
| `total_score` | REAL | 100点換算の総合スコア |
| `score_json` | TEXT | 指標ごとの内訳（JSON） |

**PK**: (`code`, `scored_at`)。

---

## 9. `rule_versions` / `post_log` / `run_log` / `schema_version`

| テーブル | 役割 | 主キー/要点 |
|---|---|---|
| `rule_versions` | rules.yaml の SHA256 でルール改定を版管理。スコアの再現性を担保 | `id` AUTO、`rules_sha256` UNIQUE |
| `post_log` | X投稿履歴。本文SHA256で30日窓の二重投稿防止 | `id` AUTO、`body_sha256`、`status`∈posted/failed/skipped |
| `run_log` | 日次/半年次バッチの実行記録 | `id` AUTO、`job`/`started_at`/`status` |
| `schema_version` | スキーマ世代（現在 v1） | `version` PK |

---

## 10. 関連（参照グラフ）

```
stocks ──code──┬─< price_history
               ├─< dividend_events ──build──> dividend_annual >── code ─┐
               ├─< financial_snapshots                                  │
               └─< streak_overrides ────────────────────────────────┐  │
                                                                     ▼  ▼
                                            computed_metrics (1銘柄1行・派生指標)
                                                     │
                                                     ▼
                            dividend_scores >── rule_version_id ──> rule_versions
                                                     │
                                                     ▼
                                              post_log（投稿）
```

外部キー制約は張らず（SQLite運用・移行容易性のため）、`code` で論理的に結合する。整合性は半年次の整合性チェックジョブで検証する。
