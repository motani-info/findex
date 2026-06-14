# 設計: データワークフロー

**作成日**: 2026-06-14
**関連**: [data-model.md](data-model.md) / [pre2000-data.md](pre2000-data.md) / [requirements.md](../requirements.md)

データが外部ソースから取り込まれ、正準系列に整形され、指標化・採点され、Xに投稿されるまでの全工程。
原則は一方向フロー（後段は前段テーブルだけを読む）。

---

## 0. 全体データフロー

```
[取得層 fetch]
JPX Excel ──月次→ stocks（コード/名称/市場/業種）
kabutan ──初回→ stocks.listing_date / founded_date
yfinance prices ──日次→ price_history
yfinance dividends ──半年→ dividend_events
yfinance financials ──四半期→ financial_snapshots
haitoukin/IR/手入力 ─────→ dividend_annual（source=haitoukin/ir/manual）
ZAi・各社IR ─────────────→ streak_overrides

         │ すべて RateLimitedFetcher 経由（--codes / バッチ / レジューム / バックオフ）
         ▼
[導出層 derive]
dividend_events ──build_dividend_annual──→ dividend_annual（source=events）
dividend_annual + streak_overrides + stocks.listing_date ──streaks──→ ストリーク＋打ち切り
dividend_annual + financial_snapshots + price_history ──compute──→ computed_metrics（唯一の出口）

         ▼
[評価層 score]
computed_metrics + rules.yaml ──engine──→ dividend_scores（rule_versionで版管理）

         ▼
[出力層 post]
dividend_scores + computed_metrics ──→ CLI rank / 投稿文面生成
投稿文面 ──品質ゲート──→ X（Playwright）──→ post_log
```

---

## 1. 更新サイクル（カテゴリ別TTL）

データは「変わる頻度」で3カテゴリに分け、毎日重いAPIを叩かない設計にする。

| カテゴリ | 内容 | コマンド | 頻度 | TTL | 所要 |
|---|---|---|---|---|---|
| A 価格由来 | 終値→利回り/PER/PBR/時価総額/モメンタム | `findex update` | 日次(平日) | — | 約5分 |
| B 財務諸表 | ROE/自己資本比率/EPS成長/FCF 等 | `findex update --quarterly` | 四半期 | 90日 | 約20分 |
| C 配当履歴 | 連続増配/非減配/配当CAGR/減配信頼性 | `findex update --dividends` | 半年 | 180日 | 約40分 |
| 初回/年1 | 全データ一括 | フルスキャン | 初回/年1 | — | 2〜4時間 |

**ポイント**: 毎日の更新は株価のみ。財務・配当はDBから読み出してローカル再計算するため高速。TTL未経過の銘柄はAPIをスキップする。

---

## 2. 日次ワークフロー（`findex update`）

```
1. backup_db()                       # findex_v2.db.bak-YYYYMMDD
2. PriceFetcher.run(codes)           # 最新2日分の終値を price_history に追記
   └ RateLimitedFetcher: 200銘柄/バッチ・バッチ間スリープ・チェックポイント
3. compute_price_metrics()           # per/pbr/div_yield/時価総額/mix/net_cash_per を再計算
                                     # → computed_metrics（price_computed_at 更新）
4. score()                           # computed_metrics + rules.yaml → dividend_scores
5. run_log に記録
```
財務・配当カラムはDBの既存値をそのまま使う（再取得しない）。

---

## 3. 配当の正準化（半年・最重要ロジック）

`findex update --dividends` の中核。**ここが正確性の生命線**（地雷1〜5が集中）。

### 3.1 events 取得 → dividend_annual 再構築
```
rebuild_annual_from_events(code):
  1. DividendFetcher で dividend_events を更新（権利落ち日ベースの実イベント）
  2. 会計年度で集計（fy = year if month>=4 else year-1）    # 地雷2
  3. first_complete_fy = min(集計年度) + 1                  # 期中開始年を捨てる・地雷1
  4. source='events' の既存行を削除して再INSERT
     ただし fiscal_year >= first_complete_fy の年度のみ
     既存行が source='manual'/'ir' なら上書きしない          # 優先順位
  5. fiscal_year < first_complete_fy はバックフィル行が残る
```

### 3.2 バックフィル接合（2000年以前）
```
backfill(code):  # haitoukin/IR/手入力
  - 対象: fiscal_year < first_complete_fy（シーム年度を含む）
  - 優先順位: manual > ir > haitoukin > events
  - 取り込み後に【境界異常チェック】:                        # 地雷3
      前年比 dps>prev*10 or dps<prev/10 の年があれば
      → 分割調整漏れ疑い → そのバックフィル行を削除（誤データより欠落が安全）
  - NTT/SBG/電通総研はここで弾かれる → override で対処
```
収集済み58銘柄は移行で投入済み。追加が必要なときだけ `scripts/backfill_pre2000.py`（haitoukinスクレイパー）を使う。

### 3.3 ストリーク計算＋打ち切り判定（`derive/streaks.py`）
```
compute_streaks(annual, listing_year, override):
  1. 進行中の会計年度（支払い未確定）を除外
  2. 末尾から遡って連続年数を数える
       増配: dps > prev*1.0001 / 非減配: dps >= prev*0.999
  3. 年度が連続しない箇所（歯抜け）で打ち切り               # 地雷4
  4. ストリークが系列先頭=最古年に到達 かつ 最古年<=下限band(2002)
       → is_censored 候補
  5. listing_year < 最古年 なら打ち切り確定 / listing_year>=最古年 なら真の開始（解除）
  6. override.value > 機械計算 のときだけ公表値に昇格（is_censored 解除）  # 地雷5
  → computed_metrics に consecutive_*_years と streak_is_censored を書く
```
表示は `format_years()`：`is_censored` なら必ず「N年以上」、そうでなければ「N年」。

---

## 4. 財務の更新（四半期・`findex update --quarterly`）

```
1. TTL>90日 の銘柄のみ FinancialFetcher.run(codes)
2. yfinance info/financials/balance_sheet を取得 → financial_snapshots に年度別INSERT
   （1行上書きせず履歴を積む）
3. EDINETでクロスチェック（欠損・異常値の検出）              # 任意
4. compute_financial_metrics() → computed_metrics（fin_computed_at 更新）
     ROE / 自己資本比率 / EPS成長5y / 売上CAGR / FCFカバレッジ /
     ROIC-WACC / 利益剰余金配当倍率 / 営業利益率 / 配当性向
```

---

## 5. スコアリング（評価層）

```
1. rules.yaml を読み、SHA256 を rule_versions に登録（無ければ）
2. 各銘柄の computed_metrics を18指標ルールに通す
     - upper_cap / penalty（利回り7%超）等を適用
     - 大型株(時価総額1兆円超)・金融銘柄は動的指標入れ替え
3. 197点満点 → 100点換算 → dividend_scores に (code, scored_at, total_score, score_json)
```
ルール改定時は新 `rule_version` が発番され、過去スコアとの比較が可能。

---

## 6. X投稿ワークフロー（出力層）

```
1. テーマ選択（21テーマのローテーション）
2. dividend_scores + computed_metrics から文面生成（poster.py）
3. 【品質ゲート】← 投稿前必須・最大の安全装置
     a. golden test が全green（花王=36 等）であること
     b. 文面中の数字が streak_is_censored=1 の銘柄を裸の数字で含まないこと
     c. body_sha256 が post_log に過去30日存在しないこと（二重投稿防止）
   いずれか不合格 → status='skipped' で記録し投稿しない
4. Playwright でログイン（~/.findex/x_session.json 再利用）→ スレッド投稿
5. 成功→post_log(status='posted', tweet_id) / 失敗→status='failed'（リトライしない）
```

---

## 7. 移行ワークフロー（legacy findex.db → findex_v2.db）

収集済みデータ（218MB）の再利用。**必ず移行すべきは再現困難な2つ**: `dividend_annual`(source!='events') と `streak_overrides`。

```
migrate():
  1. backup（findex.db は読み取りのみ、コピーで作業）
  2. findex_v2.db を initdb（新スキーマ）
  3. stocks をコピー（listing_date は未取得なので NULL のまま → kabutanで後追い）
  4. dividend_annual を全 source コピー（haitoukin/ir/manual は再現困難・最優先）
  5. streak_overrides をコピー（12件）
  6. dividend_history(legacy) → dividend_events に変換コピー
  7. price_history をコピー（任意・再取得可だが時間節約）
  8. 旧 scores(27,498行) はバックテスト用途なら別テーブルで保持（任意）
  9. derive 全再計算 → computed_metrics を再構築
  10. golden test で検算（花王=36 等）→ 通ればOK
```
旧 `stock_fundamentals` / `raw_financials` / `momentum_scores` は二重パイプラインの遺物のため**移行しない**。

---

## 8. レート制限の運用フロー（横断）

全取得は `RateLimitedFetcher` を通す。開発・検証は**全銘柄でなくコホート約30社**で回す。

```
開発時:  findex update --cohort      # data/verification_cohort.csv の28社だけ
        findex update --codes 4452,9433
本番初回: フルスキャン（goldenが通ってから1回だけ）

RateLimitedFetcher.run(codes):
  - codes を batch_size で分割、バッチ間スリープ
  - 各銘柄 fetch_one()。429/401 検知 → 指数バックオフ（最大5回）
  - 成功した銘柄を checkpoint(JSON) に記録
  - 途中失敗・中断しても resume=True で続きから（取得済みはスキップ）
```

---

## 9. 整合性チェック（半年次）

```
- dividend_annual の境界異常（前年比10倍/0.1倍）が残っていないか        # 地雷3
- streak_is_censored=1 の銘柄が dividend_scores 経由で裸の数字を出していないか
- golden test（ZAiトップ20と機械計算+override）が一致するか
- first_data_date と listing_date の矛盾（listing後にデータ空白）検出
- 検出結果を run_log に記録。不合格なら X投稿を自動停止
```
