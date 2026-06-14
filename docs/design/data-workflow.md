# 設計: データワークフロー（D7改訂版）

**作成日**: 2026-06-14（D7でD2.5〜D4.5の確定を反映して全面改訂）
**親**: [charter](00-charter-and-data-integrity.md) / [data-model](data-model.md)（D3）/ [indicator-system](04-indicator-system.md)（D4）/ [indicator-calibration](04_5-indicator-calibration.md)（D4.5）
**範囲**: 外部ソース取得 → 来歴付き保管 → 導出（status付き）→ v4採点 → 出力までの全工程。原則は**一方向フロー**（後段は前段テーブルだけを読む）。

---

## 0. 全体データフロー（D2.5実測のソース分担を反映）

```
[取得層 fetch]  ※すべて RateLimitedFetcher 経由（--codes/バッチ/レジューム/バックオフ）
JPX Excel ─────────月次→ stocks（コード/名称/市場/sector33）
EDINETコードリスト ─月次→ stocks（edinet_code/決算期末月/連結）★zipで全社・即時
kabutan ───────────初回→ stocks.listing_date（打ち切り判定の鍵・現0%）
J-Quants /equities ─日次→ price_history（直近・2024-03〜の契約窓）
yfinance prices ───初回→ price_history（2000年まで遡及。pre-2000は不能）
J-Quants /fins/summary ─四半期→ financial_snapshots（現在〜2年：売上/営業益/純益/EPS/TA/Eq/Cash/CFO/配当/予想）
EDINET 有報XBRL ───四半期→ financial_snapshots（深いBS：投資有価証券/有利子負債/支払利息/利益剰余金/流動資産/capex）★会計基準別パース
haitoukin/IR/手入力 ─────→ dividend_annual（source=haitoukin/ir/manual：2000年以前backfill）
ZAi・みんかぶ・各社IR ────→ result_overrides（公表"結果"：連続増配年数 等・汎用）

         ▼
[導出層 derive]  ※各値に status を付与（ok/zero_legit/missing/insufficient/censored）
dividend_events ──build──→ dividend_annual（source=events）
beta ← price_history × TOPIX 回帰（自前算出。fetchしない）
dividend_annual + result_overrides + stocks.listing_date ──streaks──→ 連続年数＋is_censored
  （合成順序: 機械計算 →(昇格のみ)override →(不足)N+）
dividend_annual + price_history ──→ YoC（取得利回り）＋dividend_multiple＋増配の質(EPS牽引度)
financial_snapshots ──→ ROE/自己資本比率/FCF/ROIC/DOE/営業益率 等
全部 ──→ computed_metrics（唯一の出口・指標値＋status＋claim別グレード）

         ▼
[評価層 score]  ※v4・status-based Nullポリシー
computed_metrics + rules.yaml(v4) ──engine──→ dividend_scores（rule_versionで版管理）

         ▼
[出力層 post]
dividend_scores + computed_metrics + claim別グレード ──→ CLI rank / 投稿文面
投稿文面 ──品質ゲート（grade/status/censored/golden）──→ X（Playwright）──→ post_log
```

---

## 1. 更新サイクル（カテゴリ別TTL）

| カテゴリ | 内容 | コマンド | 頻度 | TTL | 主ソース |
|---|---|---|---|---|---|
| A 価格由来 | 終値→利回り/PER/PBR/時価総額/モメンタム/YoC | `findex update` | 日次(平日) | — | J-Quants（直近）|
| B 財務諸表 | ROE/自己資本比率/EPS成長/FCF/DOE/ROIC | `findex update --quarterly` | 四半期 | 90日 | J-Quants＋EDINET |
| C 配当履歴 | 連続増配/非減配/配当倍率/減配信頼性 | `findex update --dividends` | 半年 | 180日 | events＋backfill＋override |
| マスター | edinet_code/会計メタ/上場日 | `findex update --master` | 月次/初回 | — | JPX/EDINETリスト/kabutan |
| 初回/年1 | 全データ一括（株価2000遡及含む） | フルスキャン | 初回/年1 | — | 全ソース |

毎日叩くのは株価のみ。財務・配当はDBから読みローカル再計算。TTL未経過はAPIスキップ。

---

## 2. 日次ワークフロー（`findex update`）

```
1. backup_db()                       # findex_v2.db.bak-YYYYMMDD
2. PriceFetcher.run(codes)           # J-Quantsで最新終値を price_history に追記
3. compute_price_metrics()           # per/pbr/div_yield/時価総額/mix/net_cash_per/YoC を再計算
                                     # → computed_metrics（price_computed_at 更新・各値にstatus）
4. score()                           # computed_metrics + rules.yaml(v4) → dividend_scores
5. run_log に記録
```
財務・配当カラムはDBの既存値を使う（再取得しない）。

---

## 3. 配当の正準化（半年・最重要・地雷集中）

`findex update --dividends` の中核。**正確性の生命線**。

### 3.1 events → dividend_annual 再構築
```
rebuild_annual_from_events(code):
  1. dividend_events を更新（権利落ち日ベースの実イベント）
  2. 会計年度で集計（fy = year if month>=4 else year-1）       # 地雷2
  3. first_complete_fy = min(集計年度)+1（期中開始年を捨てる） # 地雷1
  4. source='events' を再構築。manual/ir/haitoukin は上書きしない # 優先順位
```

### 3.2 バックフィル接合（2000年以前・raw補填）
```
backfill(code):  # haitoukin/IR/手入力 → dividend_annual
  - 対象: fiscal_year < first_complete_fy
  - 優先順位: manual > ir > haitoukin > jquants > events
  - 境界異常チェック: 前年比>10倍/<0.1倍 → 分割調整漏れ疑いで削除（地雷3）
  - NTT/SBG/電通総研はここで弾かれ override で対処
```

### 3.3 ストリーク＋打ち切り＋結果補正（合成順序）
```
compute_streaks(annual, listing_year, result_overrides):
  1. 進行中の会計年度を除外
  2. 末尾から連続年数を計数（増配 dps>prev*1.0001 / 非減配 dps>=prev*0.999）
  3. 歯抜けで打ち切り（地雷4）
  ── 合成順序（D4 §2）──
  4. machine値を算出
  5. result_overrides に当該fieldあり かつ override.value >= machine
        → value=override, status=ok(source=override), is_censored解除, as_of以降は機械で確認分を加算
  6. else machineが下限band/歯抜けで打ち切り → status=censored（N+表示）
  7. else status=ok(machine)
  → computed_metrics に 連続年数・status・source・streak_is_censored を書く
```
表示 `format_years()`: censored は必ず「N年以上」。override由来は出典明示（「ZAi集計で連続増配N年」）。

### 3.4 YoC・増配の質（D4.5・切り口①）
```
compute_yoc(code):
  - yield_on_cost_5y = 最新DPS ÷ 5年前株価（株価2000遡及が前提。未整備中は dividend_multiple_5y 代理）
  - 増配の質 = EPS倍率 / DPS倍率 から判定:
       EPS牽引(sound) / 性向拡大(payout_driven) / 一過性(cyclical)
  → YoCスコアに質係数（×1.0 / ×0.5 / ×0.3）を掛けて減点
```

---

## 4. 財務の更新（四半期・`findex update --quarterly`）

```
1. TTL>90日 の銘柄のみ取得
2. J-Quants /fins/summary → financial_snapshots（現在〜2年：売上/営業益/純益/EPS/TA/Eq/Cash/CFO/配当/予想/発行株）
3. EDINET 有報XBRL → financial_snapshots（深いBS：投資有価証券/有利子負債/支払利息/利益剰余金/流動資産/capex）
     ★stocks.accounting_standard で JGAAP/IFRS/US のラベル辞書を切替（IFRSは科目名違い）
     ★有報検索は提出日を日次スキャン（月末だけ見ると当たらない・3月決算は6月下旬窓）
4. beta = price_history × TOPIX 回帰で自前算出（fetchしない）
5. compute_financial_metrics() → computed_metrics（fin_computed_at 更新・各値にstatus）
     ROE / 自己資本比率 / EPS成長5y / 売上CAGR / FCFカバレッジ(=CFO-capex) /
     ROIC-WACC(beta,cost_of_debt=支払利息/有利子負債) / DOE(=ROE×配当性向) / 営業益率
```

---

## 5. スコアリング（評価層・v4 status-based）

```
1. rules.yaml(v4) を読み SHA256 を rule_versions に登録
2. 各銘柄の (指標値, status) を v4ルールに通す:
     - status=missing/insufficient/censored → 分子・分母から除外（持ってないデータで罰しない）
     - status=zero_legit → 0点で分母に残す（実力）
     - 営業利益率は業種相対スコア（sector33パーセンタイル＋絶対フロア）
     - 予想配当性向/利回りは予想欠損時に実績フォールバック
     - upper_cap/penalty_cap（利回り7%超・PER×PBR等）適用
     - 大型株(1兆円超)・金融は動的指標入れ替え（ROIC↔利益剰余金配当倍率, ネットキャッシュPER↔ミックス係数, 金融は自己資本比率除外）
3. 総合 = Σ(加重スコア)/Σ(採点できた指標の最大加重) × 100   ※動的分母
4. dividend_scores に (code, scored_at, total_score, score_json, rule_version_id)
   ＋ claim別グレード（grade_dividend/valuation/health/capital）を併記
```

---

## 6. X投稿ワークフロー（出力層・優先度低＝後回し）

```
1. テーマ選択（ローテーション。切り口は analysis-angles.md に蓄積）
2. dividend_scores + computed_metrics + claim別グレード から文面生成
3. 【品質ゲート】← 投稿前必須
     a. golden test 全green（花王=36 等）
     b. censored銘柄を裸の数字で含まない（N+ or override出典付きのみ）
     c. 対象claimの grade が基準以上（例 grade_dividend>=B）
     d. body_sha256 が過去30日に無い（二重投稿防止）
   不合格 → status='skipped'
4. Playwright ログイン（~/.findex/x_session.json 再利用）→ スレッド投稿
5. 成功→post_log(posted, tweet_id) / 失敗→failed（リトライしない）
```
※D5（X発信戦略）は優先度低のため詳細は後続。本節は枠組みのみ。

---

## 7. 移行ワークフロー（legacy findex.db → findex_v2.db）

**必ず移行すべき再現困難な2つ**: `dividend_annual`(source!='events') と `result_overrides`(旧streak_overrides 12件)。

```
migrate():
  1. findex.db は読み取り専用（コピーで作業）
  2. findex_v2.db を initdb（新スキーマ）
  3. stocks コピー（edinet_code/会計メタはEDINETリストで新規補充、listing_dateはkabutanで後追い）
  4. dividend_annual 全sourceコピー（haitoukin/ir/manual 最優先）
  5. streak_overrides → result_overrides に変換（field='consecutive_dividend_growth_years'等で汎用化）
  6. dividend_history(legacy) → dividend_events に変換コピー
  7. price_history は移行せず J-Quants＋yfinanceで2000年まで再取得（旧は2024-06〜のみ＝不足）
  8. financial_snapshots は J-Quants＋EDINETで再取得（旧raw_financialsは移行しない＝capex 0%等の欠落のため）
  9. derive 全再計算（status付き）→ computed_metrics 再構築
  10. golden test 検算（花王=36 等）→ 通ればOK
```
旧 `stock_fundamentals`/`raw_financials`/`momentum_scores`/`scores` は移行しない（二重パイプライン遺物・欠落多）。

---

## 8. レート制限の運用フロー（横断）

全取得は `RateLimitedFetcher` 経由。開発・検証は**コホート約30社**で回す。

```
開発: findex update --cohort           # data/verification_cohort.csv の28社
      findex update --codes 4452,9433
本番初回: フルスキャン（goldenが通ってから1回だけ。株価2000遡及は重い）

RateLimitedFetcher.run(codes):
  - batch_size分割・バッチ間スリープ
  - 429/401 → 指数バックオフ（最大5回）
  - 成功銘柄を checkpoint(JSON)。resume=True で続きから
  - ソース別の上限（J-Quants契約レート/EDINET日次スキャン/yfinance 2並列）を尊重
```

---

## 9. 整合性チェック（半年次・D6に接続）

```
- dividend_annual 境界異常（前年比10倍/0.1倍）の残存                       # 地雷3
- censored銘柄が dividend_scores 経由で裸の数字を出していないか
- result_overrides値 と machine値 の乖離（定義差の早期発見）             # D2.7/D6
- status分布の異常監視（missing急増＝取得障害の検知）
- golden test（ZAiトップ20と機械計算+override）一致
- listing_date と first_data_date の矛盾検出
- backfill＋override後に残る N+ 銘柄数（減らすべき指標）
- 検出結果を run_log に記録。不合格なら X投稿を自動停止
```
詳細な検証戦略（golden拡張・照合レポート・自動停止条件）は **D6 多フィールド検証** で規定。
