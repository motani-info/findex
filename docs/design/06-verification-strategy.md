# D6: 多フィールド検証戦略

**作成日**: 2026-06-15
**親**: [charter](00-charter-and-data-integrity.md)（正確でない数字は有害）/ [data-model](data-model.md) / [indicator-system](04-indicator-system.md) / [data-workflow](data-workflow.md) §9
**目的**: 検証を「配当ストリーク中心」から**全フィールド・全status**に広げ、誤った数字を投稿前に止める仕組みを設計する。これが定款「確証を持てない数字は流さない」の実行装置。

---

## 0. 検証の三層（テストピラミッド）

| 層 | 対象 | 頻度 | 速度 | 役割 |
|---|---|---|---|---|
| **L1 単体テスト** | 純粋関数（streaks/CAGR/YoC/status判定/採点式） | CI・コミット毎 | 即時 | ロジックの正しさ（API不要） |
| **L2 コホート検証** | 約38社（失敗モード網羅）で実データ突合 | 開発の各変更時 | 数分 | golden一致・status妥当・実データ結合 |
| **L3 全銘柄サニティ** | 全銘柄の分布・異常検知 | 半年次/フルスキャン後 | 重い | カバレッジ・外れ値・整合性 |

**原則**: 毎回全銘柄は回さない（レート制限）。**L1とL2で設計の正しさを担保**し、L3は分布監視に徹する。

---

## 1. golden の拡張（ストリーク → 多フィールド）

現在の golden は `golden_streaks_zai_20260601.csv`（連続増配20社）のみ。**財務・バリュエーションの正解値**を追加する。

### 1.1 golden_financials（新設）
少数銘柄 × 主要フィールドの**一次情報（EDINET有報/各社IR）由来の正解値**。

| 列 | 例 |
|---|---|
| code / fiscal_year | 9433 / 2024 |
| field | revenue / operating_income / net_income / equity / total_assets / retained_earnings / investment_securities / interest_bearing_debt |
| value | 有報XBRLの確定値（D2.5でKDDI実取得済：利益剰余金5,522,578M 等） |
| source / source_url / as_of | edinet S100... |

対象は会計基準を散らす（IFRS=9433、JGAAP=中小、US-GAAP=7203トヨタ）。**機械パース結果がこの正解と一致するか**を検証＝会計基準別ラベル辞書の正しさを担保。

### 1.2 golden_valuation（任意・軽量）
数銘柄の PER/PBR/配当利回りを、ある基準日の公表値（みんかぶ等）と±数%で突合。価格×財務の結合ミス検出用。

### 1.3 維持運用
golden は as_of 付きスナップショット。**経年で陳腐化**するため、半年次に再取得・差し替え（連続増配は毎年+1される＝§2の経年補正と同期）。

---

## 2. 検証コホートの拡張（28社 → 約38社）

現コホートは配当系失敗モード網羅。**財務・会計基準・status系**を追加する。

| 追加カテゴリ | 狙い | 例（確定は構築時） |
|---|---|---|
| accounting_ifrs | IFRSラベルのパース正しさ | 9433 KDDI（既）, 9984 SBG（既） |
| accounting_usgaap | US-GAAPの科目対応 | 7203 トヨタ |
| accounting_jgaap | 標準JGAAP対照 | 中堅JGAAP銘柄 |
| financial_sector | 動的swap・自己資本比率除外の検証 | 8306 三菱UFJ（銀行）, 8766 東京海上（保険） |
| young_ipo_insufficient | 上場5年未満→10年CAGR/5y成長が insufficient になるか | 2022年以降IPO銘柄 |
| loss_zero_legit | 赤字/無配→ status=zero_legit が正しく付くか | 直近赤字銘柄 |
| low_margin_sector | 業種相対スコアの妥当性 | 卸売/小売の中堅 |
| high_invest_securities | ネットキャッシュ×投資有価証券の取得 | 持合い厚い銘柄 |
| capex_heavy | FCF=CFO−capex の検証 | 設備産業（鉄鋼/化学） |

→ `data/verification_cohort.csv` に `mode` 列で追記。**各失敗モードが最低1社**あること。

---

## 3. 照合レポート（reconciliation）

導出後・採点前に自動生成し、`run_log` と差分ファイルに残す。

### 3.1 override vs machine（定義差の早期発見・D2.7）
- result_overrides がある銘柄で `|override − machine|` を一覧化。
- 大きい乖離（例 ±3年超）は `definition_note` 確認を促す（小林製薬「上場前起算」型）。
- **昇格採用したのに乖離が異常に大きい→ 定義差の疑い**としてフラグ。

### 3.2 ソース間クロスチェック（J-Quants vs EDINET）
- 両方が持つフィールド（total_assets/net_income/equity 等）で相対差を計算。
- **10%超の乖離 → confidence=review**（D2 §4の照合ルール）。分析から除外しレポート。
- 会計基準・連結単体の取り違えを検出（連結であるべき値に単体が混入 等）。

### 3.3 machine vs golden
- L2で golden_streaks / golden_financials と機械計算を突合。
- 不一致は CI/コホート検証を**赤**にし、原因（パース辞書・FY正規化・分割調整）を特定。

### 3.4 株価履歴の検証（yfinance 2000-2024・[design-review](design-review.md) #3）
YoC（看板指標）とバックテストの背骨は **yfinance の過去株価**（J-Quantsは2024〜のみ＝照合源が無い区間）。降格したはずの主ソースに依存するため、独自に検証する。
- **複数ソース突合**: 入手可能な区間でJ-Quants（2024〜）とyfinanceを重ね、調整後終値の乖離を監視（直近の整合が取れていれば過去の信頼度の傍証）。
- **分割イベントの独立検証**: 分割・併合（NTT/SBG/電通総研の地雷）を別途イベントリストで持ち、yfinanceの調整係数と突合。前日比の異常（×0.1/×10）を外れ値検知。
- **YoC感度チェック**: 5年前株価が外れ値の銘柄はYoCを `confidence=review` にして投稿・ランキングから除外。
- **信頼度の上限**: pre-2024に golden 価格源が無い区間は、YoCに**信頼度の上限**を付け正直に扱う（捏造しない＝定款）。

### 3.5 旧DB配当の能動洗浄（移行照合・[design-review](design-review.md) #7）
連続増配claimの土台 `dividend_annual`(FY1989〜) は**旧DBにしか無い再現困難データ**で、かつ花王26 vs 36 事故の当該データ。移行時に受け身で信じず能動的に洗う。
- **yfinance配当(1999+)を再取得し、移行した dividend_annual と相互照合**。乖離は `confidence=review` で要確認。
- 不一致銘柄をレポート化し、result_override/手動で確定。旧DBの silent error を移行で持ち越さない。

---

## 4. status 分布の監視（取得障害・劣化の検知）

D4で各値に status を付けたので、**status分布の異常**が品質劣化のセンサーになる。

| 監視項目 | 正常時 | アラート条件 |
|---|---|---|
| field別 missing率 | 安定 | **前回比で急増**（＝フェッチ障害・APIスキーマ変更） |
| censored率（連続年数） | backfill/overrideで漸減 | **上昇**（＝backfill未反映・listing_date未取得） |
| insufficient率 | 若い銘柄相応 | 急変（＝履歴データ消失） |
| review率（乖離） | 低 | 上昇（＝ソース不整合） |
| 残存N+銘柄数 | 漸減目標 | 横ばい/増（＝補正パイプライン停滞） |
| **EDINETパース成功率**（会計基準別） | 基準別に高位安定 | **基準別に低下**（＝タクソノミ変更・ラベル辞書の未対応） |

→ L3（半年次）で集計し `run_log` に記録。閾値超は X投稿を自動停止（§5）。

### 4.1 EDINETパースのリスク低減ゲート（[design-review](design-review.md) #4）
EDINET会計基準別XBRLパースは**実装最大の工数リスク**（基準別ラベル辞書・タクソノミ変更）。削らず**ゲートで守る**:
- **早期スパイク**: 実装着手時にJGAAP/IFRS/US各数社で基準別辞書の成立を先に確認（D2.5はKDDI1社・current_assetsで既に空振り）。
- **パース成功率ゲート**: 基準別の必須フィールド取得率が閾値未満なら、その基準の銘柄の **capital claim を grade C以下に固定**（capex/投資有価証券が埋まらない銘柄を高評価にしない）。
- **基準別辞書を独立成果物に**: golden_financials（§1.1・IFRS/JGAAP/US散らす）で**辞書の正しさを単体検証**してから本適用。辞書はコードでなくデータ（YAML）として版管理。

---

## 5. 投稿の自動停止条件（品質ゲートの確定仕様）

[data-workflow](data-workflow.md) §6 の品質ゲートを**判定基準として確定**する。1つでも不合格なら該当claimの投稿を止める。

```
投稿可 = ALL(
  golden_streaks 全green,                       # 連続増配の核がズレてない
  golden_financials 全green,                    # 財務パースが正しい
  対象claimの grade >= B,                        # D2.6 claim別グレード
  文面の数字に status∈{missing,insufficient} の指標が無い,
  censored銘柄は「N年以上」or override出典付きのみ,   # 花王26 vs 36の再発防止
  status分布アラートが出ていない（§4）,
  body_sha256 が過去30日に無い                    # 二重投稿防止
)
不合格 → post_log(status='skipped', reason) で記録し投稿しない
```

**最優先の不変条件**: 「**確定値に見える誤った数字を出さない**」。censored を裸の数字で出すことだけは絶対に許さない（旧PJ最大の事故）。

---

## 6. CI / 開発フローへの組み込み

```
コミット時(L1): pytest（streaks/yoc/status/採点式の単体）— API不要・必ず緑
変更検証(L2):   findex verify --cohort
                 → コホート38社を取得→導出→採点→golden突合→照合レポート
                 → 1件でも golden 不一致なら exit≠0（マージ不可）
本番前(L3):     フルスキャン後に分布監視＋整合性チェック（§3.2/§4/§9 of workflow）
```

`findex verify` は新設CLI（実装フェーズ）。golden・コホート・照合・status監視を1コマンドに束ねる。

---

## 7. まとめと実装フェーズへの引き渡し

| 検証資産 | 状態 | 実装フェーズでやること |
|---|---|---|
| golden_streaks（連続増配20社） | ✅ 既存 | 半年次更新 |
| golden_financials | 設計のみ | EDINET/IRから少数銘柄の正解値を作成 |
| 検証コホート | 28→38社へ拡張設計 | 財務/会計基準/status系の銘柄を追記 |
| 照合レポート | 設計のみ | override乖離・ソース間・golden突合を実装 |
| status分布監視 | 設計のみ | L3集計＋アラート |
| `findex verify` CLI | 設計のみ | L1/L2/L3を束ねる |

→ **これでD1〜D7（D5除く）の設計が完結**。次は**実装フェーズの方針決め**（移行→fetch実装→derive→score→verifyの順、コホートで回す）。D5（X発信）は実装が動いてから着手。
