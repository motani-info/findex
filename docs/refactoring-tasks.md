# データ層リファクタリング タスク一覧

> 設計: `docs/refactoring-data-layer.md`  
> 現状分析: `docs/data-architecture.md`  
> 最終更新: 2026-06-06

---

## 進捗ステータス

| Task | 内容 | ステータス | 完了日 |
|---|---|---|---|
| 1-A | raw_financials テーブル + フェッチャー | ✅ 完了 | 2026-06-06 |
| 1-B | computed_metrics テーブル + 計算エンジン | ✅ 完了 | 2026-06-06 |
| 1-C | dividend_scores テーブル + スコアリング | ✅ 完了 | 2026-06-06 |
| 1-D | momentum_scores テーブル + スコアリング | ✅ 完了 | 2026-06-06 |
| 2-A | 配当API切替 | ✅ 完了 | 2026-06-06 |
| 2-B | モメンタムAPI切替 | ✅ 完了 | 2026-06-06 |
| 3-A | パイプライン統合 | ✅ 完了 | 2026-06-06 |
| 3-B | UI不具合修正（raw/fields/実数値） | ✅ 完了 | 2026-06-06 |
| 4-A | 旧テーブル廃止 | 🔲 未着手 | |

### 実装済みファイル（フェーズ1）

| ファイル | 内容 |
|---|---|
| `findex/db.py` | マイグレーション v4-6 + CRUD関数（raw_financials, computed_metrics, dividend_scores, momentum_scores） |
| `findex/updater/fetch_raw.py` | `findex fetch quarterly` — yfinance生データ → raw_financials |
| `findex/updater/compute.py` | `findex compute` — raw_financials → computed_metrics 計算 |
| `findex/updater/score_dividend.py` | `findex score dividend` — computed_metrics → dividend_scores |
| `findex/updater/score_momentum.py` | `findex score momentum` — computed_metrics → momentum_scores |
| `findex/cli.py` | fetch / compute / score / pipeline コマンドグループ追加 |

### 実装済みファイル（フェーズ2-3）

| ファイル | 内容 |
|---|---|
| `findex/api/routers/dividend.py` | dividend_scores + stock_fundamentals 参照。`/check` は `raw` フィールド付き |
| `findex/api/routers/momentum.py` | momentum_scores + computed_metrics + price_history 参照。rank に実数リターン値、check に `fields` フィールド付き |
| `findex/api/db.py` | DB接続に timeout=10 追加（ロック対策） |
| `findex/cli.py` | `findex pipeline` コマンド追加（fetch → compute → score 一括実行） |
| `findex/scorer/dividend_batch.py` | 暫定バッチ（stock_fundamentals → dividend_scores）※ computed_metrics 経由が本流 |
| `findex/scorer/momentum_batch.py` | 暫定バッチ（price_history → momentum_scores）※ computed_metrics 経由が本流 |

### 検証結果（2026-06-06）

テスト用DBで `fetch → compute → score` パイプラインの統合テスト合格:
- トヨタ(7203): dividend_score=57.4点, momentum_score=80.2点
- 4テーブル全てに正常書き込み確認

### 本番DB投入結果（2026-06-06 17:19〜19:27）

**Step 1: `findex pipeline`（17:19〜18:22、合計62.6分）**

| テーブル | 件数 | 所要時間 |
|---|---|---|
| raw_financials | 3,745件成功 / 1失敗 | 62.5分（yfinance API） |
| computed_metrics | 3,746件 | 数秒 |
| dividend_scores | 3,746件 | 0.5秒 |
| momentum_scores | 3,746件 | 0.2秒 |

**Step 2: `findex update --dividends --force-all`（18:23〜19:26、合計63.5分）**

| テーブル | 件数 | 所要時間 |
|---|---|---|
| dividend_history | 3,741件成功 / 6失敗 | 63.5分（yfinance API） |

失敗した7件は全て上場廃止銘柄（"possibly delisted"）。

**Step 3: UI動作確認（Playwright、20:32）**

全6ページをスクリーンショット撮影し確認。3件の問題を発見:
1. 銘柄詳細ページ — 主要指標が `-`（APIが `raw` を返していなかった）
2. モメンタムランキング — 騰落率が `-`（APIが実数値を返していなかった）
3. モメンタム詳細 — `fields` がない

→ Task 3-B で修正。全ページ正常動作確認済み（20:49）

**結論**: 全3層のデータが最新かつ正常。APIおよびUI全ページの動作確認完了。

---

## 次回やること（開発再開ガイド）

### 即座に着手可能

1. ~~**検索API移行** — `/api/stock/search` が旧 `scores` テーブルを参照しているので `dividend_scores` に切り替え~~ ✅ 完了 2026-06-06（`dividend_scores + computed_metrics` 参照に切替済み）
2. ~~**配当スコア内訳の 0.0 問題** — 7203のスコア内訳で下半分（consecutive_no_cut_years等）が 0.0。`computed_metrics` の計算ロジックを確認し、`stock_fundamentals` から正しく移植されているか検証~~ ✅ 完了 2026-06-06（`compute.py` に `roe`/`operating_margin`/`payout_ratio` を追加。3,746銘柄再計算済み）
3. **別プロセスによるファイル上書き対策** — 下記「注意事項」参照。uvicorn --reload で共存する別セッションが `dividend.py` / `momentum.py` を上書きすることがある

### 中期（安定稼働確認後）

4. **旧テーブル廃止（Task 4-A）** — 1-2週間の安定運用後に `stock_fundamentals` + `scores` を DROP
5. **暫定バッチ統合** — `scorer/dividend_batch.py` と `scorer/momentum_batch.py` を `updater/score_*.py` に統合（computed_metrics経由に一本化）
6. **出来高増加率(vol_ratio)** — モメンタム指標の未実装分。price_historyから計算してcomputed_metricsに追加

### 現在の環境

- APIサーバー: `uvicorn` on localhost:8080（`--reload` 有効）
- DB: `~/.findex/db/findex.db`（WALモード、busy_timeout=30s）
- 日次パイプライン: launchd（平日18:00）`~/Library/LaunchAgents/com.findex.daily.plist`
- 最終データ更新: 2026-06-06 19:27（pipeline + dividends 両方完了）
- TOPIX(1306): backfill済み（2年分487レコード）→ 相対リターン計算可能
- 最終UI確認: 2026-06-06 21:00（全ページ正常動作確認）

---

## 残タスク

### Task 4-A: 旧テーブル廃止（安定稼働確認後）

新パイプラインが安定稼働したことを確認した上で実施する。1-2週間様子を見る。

- [ ] `stock_fundamentals` テーブルを廃止（`raw_financials` + `computed_metrics` で代替）
- [ ] `scores` テーブルを廃止（`dividend_scores` で代替）
- [ ] `scores.raw_json` に依存していた全箇所を洗い出し・移行
  - CLI: `findex dividend rank` / `findex dividend check` （旧scoresテーブル直接参照）
  - CLI: `findex momentum rank` / `findex momentum check` （旧scores.raw_json参照）
- [ ] レガシーフォールバックコードの削除
- [ ] マイグレーションで DROP TABLE（or リネーム保持）
- [ ] `findex/scorer/dividend_batch.py` と `findex/scorer/momentum_batch.py`（暫定バッチ）を `updater/score_*.py` に統合

### 運用タスク（継続）

- [x] `findex pipeline` を定期実行に組み込む → **launchd で平日18:00に自動実行**
  - 実行スクリプト: `scripts/daily.sh`（compute + score を毎日実行。fetchは四半期のみ）
  - 設定ファイル: `~/Library/LaunchAgents/com.findex.daily.plist`
- [x] TOPIX(1306)の過去データ蓄積 → **2年分487レコード backfill済み**
- [ ] 四半期: `findex fetch quarterly`（決算シーズン後に手動実行）
- [ ] 半年: `findex update --dividends --force-all`（配当データ全更新、手動実行）

### UI改善タスク（任意）

- [x] 配当スコア内訳の下半分（roe, operating_margin, payout_ratio）が 0.0 → compute.py に移植済み（fcf_payout_coverage/dividend_reliability はデータ不足のため 0.0 継続）
- [ ] 銘柄詳細ページの `時価総額` `更新日` 表示（フロントは対応済み、APIの `updated_at` フィールド要確認）

### ⚠️ 注意事項: 別プロセスによるファイル上書き

`uvicorn --reload` で API サーバーが起動しているため、別の開発セッション（別ターミナルのkiro等）が同じファイルを編集すると **API ルーターが予告なく上書きされる** 問題が発生した。

**実際に上書きされたファイル:**
- `findex/api/routers/dividend.py` — `raw` フィールド追加が消えた（修正済み）
- `findex/api/routers/momentum.py` — `computed_metrics` JOIN が消えた（修正済み）

**対策:**
1. 修正後は `curl` で実レスポンスを確認してから完了とする
2. 不審な退行があればまず `wc -l` と `grep` でファイル内容を確認
3. 将来的には API ルーターのテストを追加して退行を検知する

---

## 前提

## フェーズ1: 新テーブル作成（並行可能・相互依存なし）

各タスクは独立して着手可能。既存テーブル・処理には手を加えない。

### Task 1-A: `raw_financials` テーブル作成 + フェッチャー実装

**目的**: Webから取得した生データを保存する専用テーブルを作る

- [x] `db.py` に `raw_financials` テーブルのマイグレーション追加
- [x] `upsert_raw_financials(conn, code, data)` 関数を実装
- [x] `get_raw_financials(conn, codes)` 関数を実装
- [x] 既存 `_fetch_financials_one()` から「取得」部分のみ抽出した関数を作る
  - yfinance の info/financials/balance_sheet の生値をそのまま保存
  - 計算（equity_ratio 等）は一切行わない
- [x] `findex fetch quarterly` コマンド（新設）で raw_financials に保存

**入力**: yfinance API
**出力**: `raw_financials` テーブル
**依存**: なし

---

### Task 1-B: `computed_metrics` テーブル作成 + 計算エンジン実装

**目的**: マスターデータから計算する指標を保存する専用テーブルを作る

- [x] `db.py` に `computed_metrics` テーブルのマイグレーション追加
- [x] `upsert_computed_metrics(conn, code, data)` 関数を実装
- [x] `get_computed_metrics(conn, codes)` 関数を実装
- [x] 計算関数群の整理（既存の `_equity_ratio`, `_calc_eps_cagr` 等を流用）
  - 入力: `raw_financials` + `price_history` + `dividend_history` のみ
  - yfinance への通信は一切しない
- [x] `findex compute` コマンド（新設）で computed_metrics を更新

**入力**: `raw_financials`, `price_history`, `dividend_history` テーブル
**出力**: `computed_metrics` テーブル
**依存**: なし（テーブル定義のみ。Task 1-Aのデータがなくても空テーブルで動く）

---

### Task 1-C: `dividend_scores` テーブル作成 + スコアリング実装

**目的**: 配当株としての評価をカラム展開して保存する

- [x] `db.py` に `dividend_scores` テーブルのマイグレーション追加
- [x] `upsert_dividend_score(conn, code, scored_at, rule_version_id, total, breakdown)` 実装
- [x] `get_dividend_scores(conn, top_n, filters)` 実装
- [x] 既存 `scorer/engine.py` の `score_one()` 結果を分解してカラムに保存するロジック
- [x] `findex score dividend` コマンド（新設）で computed_metrics → dividend_scores

**入力**: `computed_metrics` テーブル + `rules.yaml`
**出力**: `dividend_scores` テーブル
**依存**: なし（テーブル定義のみ。computed_metrics が空なら全0点で保存）

---

### Task 1-D: `momentum_scores` テーブル作成 + スコアリング実装

**目的**: モメンタム株としての評価を永続化する

- [x] `db.py` に `momentum_scores` テーブルのマイグレーション追加
- [x] `upsert_momentum_score(conn, code, scored_at, total, breakdown)` 実装
- [x] `get_momentum_scores(conn, top_n, filters)` 実装
- [x] 既存 `momentum.py` の `_calc_momentum_score()` 結果をカラムに保存するロジック
- [x] `findex score momentum` コマンド（新設）で computed_metrics + price_history → momentum_scores

**入力**: `computed_metrics` + `price_history` テーブル
**出力**: `momentum_scores` テーブル
**依存**: なし

---

## フェーズ2: API層の切り替え（フェーズ1完了後）

### Task 2-A: 配当API を `dividend_scores` テーブル参照に切り替え

- [x] `/api/dividend/rank` を `dividend_scores JOIN computed_metrics JOIN stocks` の SELECT のみに変更
- [x] `/api/dividend/check` を同様に変更
- [x] json_extract 呼び出しを全廃（レガシーフォールバック以外）
- [x] レスポンス形式は維持（フロント影響なし）

**依存**: Task 1-C 完了

---

### Task 2-B: モメンタムAPI を `momentum_scores` テーブル参照に切り替え

- [x] `/api/momentum/rank` を `momentum_scores JOIN computed_metrics JOIN stocks` の SELECT のみに変更
- [x] `/api/momentum/check` を同様に変更
- [x] リアルタイム計算ロジックをAPI内から削除（レガシーフォールバック以外）

**依存**: Task 1-D 完了

---

## フェーズ3: バッチパイプライン統合（フェーズ1完了後）

### Task 3-A: 統合バッチコマンド設計

- [x] `findex pipeline` コマンド（新設）: fetch → compute → score を順序制御付きで実行
- [x] 既存の `findex update` / `findex update --quarterly` / `findex update --dividends` との整合性
  - **採用**: 案1 — 旧コマンドを残し、新コマンドを並行提供 → 安定後に旧を廃止
  - API層はフォールバック付き（新テーブルが空なら旧テーブルを参照）

**依存**: Task 1-A, 1-B, 1-C, 1-D すべて完了

---

## フェーズ4: 旧テーブル廃止（全フェーズ完了後）

### Task 4-A: 旧テーブルの廃止

- [ ] `stock_fundamentals` テーブルを廃止（`raw_financials` + `computed_metrics` で代替）
- [ ] `scores` テーブルを廃止（`dividend_scores` で代替）
- [ ] `scores.raw_json` に依存していた全箇所を洗い出し・移行
- [ ] マイグレーションで DROP TABLE（or リネーム保持）

**依存**: フェーズ2, フェーズ3 完了

---

## 並行着手マップ

```
         ┌── Task 1-A (raw_financials)
         ├── Task 1-B (computed_metrics)
Phase 1 ─┤                                    ← 全部並行OK
         ├── Task 1-C (dividend_scores)
         └── Task 1-D (momentum_scores)

         ┌── Task 2-A (配当API切替)    ← 1-C完了後
Phase 2 ─┤
         └── Task 2-B (モメンタムAPI切替) ← 1-D完了後

Phase 3 ─── Task 3-A (パイプライン統合) ← Phase 1 全完了後

Phase 4 ─── Task 4-A (旧テーブル廃止)   ← Phase 2,3 全完了後
```

---

## 補足: 各タスクの見積もり（目安）

| Task | 規模 | 備考 |
|---|---|---|
| 1-A | 中 | フェッチャーのリファクタ。既存コード再利用多い |
| 1-B | 中 | 計算ロジックは既存を移植。入力元の切り替えが主 |
| 1-C | 小 | scorer/engine.py はそのまま。保存先の変更 |
| 1-D | 小 | momentum.py のスコア部分を保存に回すだけ |
| 2-A | 小 | API内の SELECT 文書き換え |
| 2-B | 小 | 同上 |
| 3-A | 中 | コマンド体系の再設計 |
| 4-A | 小 | 影響範囲の洗い出しがメイン |
