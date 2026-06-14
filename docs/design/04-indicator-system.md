# D4: 指標システム仕様

**作成日**: 2026-06-14
**親**: [charter](00-charter-and-data-integrity.md) §6 / [D2.6影響](02_6-data-limits-and-impact.md) / [D2.7結果補正](02_7-result-override-layer.md) / [data-model](data-model.md)
**目的**: 指標を「進化するシステム」として仕様化する。本書で決めるのは ①**Nullポリシー再設計** ②**合成順序のデータ契約** ③**指標セットの確定（16/18）** ④**claim別グレード閾値**。
**原則**: 指標の「数」は本質でない（定款）。`rule_versions` で版管理し、追加・廃止・重み変更を前提とする。本書は v3 スナップショットの仕様。

---

## 1. Nullポリシー再設計（最重要・現行アンチパターンの是正）

### 1.1 現行の何が間違いか
現 rules.yaml: 「**データ取得不可（None）→ 生スコア0（分母から除外しない）**」。
これは**二重に不当**:
- データを「持っていないだけ」の銘柄を、実力0と同じに減点する
- かつ分母に残すので総合スコアを不当に押し下げる
- 結果、**「データが薄い銘柄」と「実際にダメな銘柄」を区別できない**（旧PJの誤りの一般形）

### 1.2 値の「不在」を4状態に分解する
derive層は値を計算するとき**なぜ不在か**を知っている。だから値と一緒に**status**を出す。スコアラは数字でなく status を見て採点する。

| status | 意味 | 実例 | 採点での扱い |
|---|---|---|---|
| `ok` | 値あり | 連続増配16年 | 通常採点 |
| `zero_legit` | **正当な0**（実値としての0） | 増配してない→連続増配0年、過去20年で減配2回→信頼性0 | **0点として採点**（実力。分母に残す） |
| `missing` | **欠損（修正可能）** | capex未取得でFCF不能、EDINETパース失敗 | **分母から除外**＋backfillフラグ。0点にしない |
| `insufficient` | **期間不足（構造的）** | 上場11年未満で10年CAGR不能 | **分母から除外**（評価不能。欠陥でない） |
| `censored` | **打ち切り**（過小確定リスク） | pre-2000で連続年数が頭打ち | **N+表示**。裸の数字で採点しない |

> 実測根拠（D4調査）: データ11年+銘柄の10年CAGR NULLは5%だが、**11年未満銘柄は100%NULL**（1,199銘柄）。これは欠損でなく `insufficient`＝構造的に不能。0点減点は誤り。

### 1.3 採点式（分母を動的にする）
```
総合スコア = Σ_i(生スコア_i × weight_i)  for i in {status ∈ ok, zero_legit}
           ────────────────────────────────────────────────────  × 100
             Σ_i(max_score × weight_i)    for i in {status ∈ ok, zero_legit}
```
- `missing` / `insufficient` / `censored` は**分子・分母の両方から除外**（持っていないデータで罰しない）
- ただし**除外した事実はグレードに必ず反映**（§4）。「薄いデータで高得点」を防ぐのはスコアでなく**グレード**の役目
- `zero_legit` は分母に残す（増配してない事実は減点に値する）

### 1.4 「薄いデータinflation」を防ぐ歯止め
分母除外だけだと、2指標しか無い銘柄が満点になりうる。歯止め=**グレード＋最小要件**:
- claim別グレード（§4）で「何を測れたか」を必ず併示
- 投稿は score だけでなく **score×grade** で判断（高スコア×低グレード＝注記 or 投稿対象外）
- core指標（配当継続性の最低限）が `missing`/`insufficient` の銘柄はそのclaimをCグレード以下に固定

---

## 2. 合成順序のデータ契約（機械計算 → override → N+）

ストリーク系（連続増配/非減配/減配信頼性）の値は、以下の決定的順序で確定する（D2.7）。

```
1. machine    = dividend_annual から純粋計算（derive/streaks.py）
2. override?   = result_overrides に該当 field があり、かつ override.value ≥ machine
                 → value=override, status=ok, is_censored=False, source=override
                 （as_of以降は機械で確認できた連続分を加算＝経年補正）
3. censored?  = override無し かつ machineが下限band/ギャップで打ち切り
                 → status=censored（N+表示）
4. else       = value=machine, status=ok, source=machine
```

**契約事項**:
- override は**昇格のみ**（公表値が機械計算より長いときだけ）。古い公表値で機械計算を下げない
- override採用時、**その指標の `censored` を解除**（他指標は不変＝claim単位）
- 定義差は `definition_note` に必ず保持し、**投稿時は出典明示**（「ZAi集計で連続増配N年」）。機械値とのギャップはD6照合の対象
- 配当CAGRは override 対象外（"結果"がクリーンに公表されない）＝raw補填(haitoukin)経由のみ

---

## 3. 指標セットの確定（16/18問題）

### 3.1 結論
**現スナップショット = rules.yaml v3 の16定義**（標準14＋大型/金融の代替2）。「18」は v3 前（`dividend_growth_5y_cagr` と `debt_to_equity` を含んでいた旧版）。**数は版管理事項であり固定しない**（定款）。

| # | 指標 | field | weight | 主入力 | 必要履歴 | データクラス | 想定status分布 |
|---|---|---|--:|---|---|---|---|
| 1 | 連続非減配年数 | consecutive_no_cut_years | 2.5 | dividend_annual | 長い | B/D(打切) | ok/censored/zero |
| 2 | 連続増配年数 | consecutive_dividend_growth_years | 1.5 | dividend_annual | 長い | B/D | ok/censored/zero_legit |
| 3 | 減配信頼性 | dividend_reliability | 0.8 | dividend_annual(20y) | 20年 | B/D | ok/zero_legit/insufficient |
| 4 | 10年増配CAGR | dividend_growth_10y_cagr | 1.2 | dividend_annual(11y) | 11年 | B | ok/**insufficient**(若32%) |
| 5 | 予想配当性向 | payout_ratio | 2.0 | forecast_dps,net_income | 現在 | A | ok（99.8%） |
| 6 | FCF配当カバレッジ | fcf_payout_coverage | 1.0 | CFO,capex,配当 | 現在 | **C(capex)** | ok/**missing**(capex回復で改善) |
| 7 | EPS成長5y | eps_growth_5y | 1.0 | eps,eps5y前 | 5年 | A/B | ok/insufficient |
| 8 | 売上5yCAGR | revenue_growth_5y_cagr | 1.0 | revenue,5y前 | 5年 | A | ok（97%） |
| 9 | 自己資本比率 | equity_ratio | 1.5 | equity,total_assets | 現在 | A | ok（99.5%） |
| 10 | ROE | roe | 1.5 | net_income,equity | 現在 | A | ok（95%） |
| 11 | 営業利益率 | operating_margin | 1.0 | op_income,revenue | 現在 | A | ok（99.3%） |
| 12 | ROIC-WACC | roic_minus_wacc | 0.8 | NOPAT,投下資本,WACC(beta,負債,税) | 現在 | A/C | ok/missing（beta有・cost_of_debt要EDINET） |
| 13 | 配当利回り | div_yield | 1.2 | price,forecast_dps | 現在 | A | ok（84%） |
| 14 | ネットキャッシュPER | net_cash_per | 1.5 | 時価総額,現金,投資有価証券,負債 | 現在 | A/**C** | ok/missing（investment_sec要EDINET） |
| 代1 | 利益剰余金配当倍率 | retained_earnings_div_ratio | 1.0 | retained_earnings,配当 | 現在 | A | ok（99.5%）replaces #12 |
| 代2 | ミックス係数 | mix_coefficient | 1.5 | per,pbr | 現在 | A | ok replaces #14 |

代1/代2 は **large_cap（時価総額1兆円+）/financial（銀行・保険・証券）** で #12/#14 と差し替え。financial は #9 自己資本比率を除外。

### 3.2 実測を踏まえた重みの再検討（D4の宿題→将来版）
- #6 FCFカバレッジ: 旧41%の主因 capex 0% が回復すれば有効率上昇 → **回復後に重み再評価**（現在 weight 1.0 は暫定）
- #12 ROIC-WACC: beta は95%有（D2.6訂正）。cost_of_debt を EDINET支払利息で埋めれば改善 → 回復後再評価
- これらは `rule_versions` で次版として扱う。**今は v3 を凍結スナップショットとして確定**。

---

## 4. claim別グレードの閾値（D2.6 §6 の具体化）

各 claim は依存指標群の status から A〜D を機械判定する。

| claim | 構成指標 | A | B | C | D |
|---|---|---|---|---|---|
| **dividend**（配当継続性） | #1,#2,#3,#4 | 全てok（censored無し）＋照合済 | okだが一部未照合 | 一部 censored/insufficient | core(#1)が missing |
| **valuation**（割安度） | #5,#13,#14(or代2) | 全てok | 一部present | 一部 missing | price無し |
| **health**（財務健全） | #9,#10,#11 | 全てok | — | 一部 missing | 全て missing |
| **capital**（資本効率） | #6,#12(or代1) | 全てok | — | 一部 missing | 全て missing(capex/inv_sec欠落) |

**判定規則**:
- `censored` を含む claim は **A不可**（確定でないため）。N+で投稿は可だが「以上」と明示
- `missing` を含む claim はその指標を分母除外しつつ、claimグレードを1段下げる
- `insufficient`（若い銘柄）はそのclaimを「評価対象外」とし、**減点でなく非表示**
- 総合スコアは「採点できた指標」での%、グレードは「どれだけ採点できたか」。**投稿は両方を見る**（D2.6）

---

## 4.5 ランキングの比較可能性（[design-review](design-review.md) #5）

動的分母（§1.3）は「持っていないデータで罰しない」ために必須だが、副作用として **6指標で採点された銘柄と14指標で採点された銘柄の `total_score` が同じ物差しでない**（両方「/100」だが採点母数が違う）。横断ランキングをそのまま並べると誤解を生む。

**決定**:
- **claim内ランキングを主**にする（例: 配当claimのトップ、健全性claimのトップ）。claim内は依存指標集合が揃っており比較可能。投稿・サイトの主役はこれ。
- **総合 `total_score` は参考値**とし、**最小採点指標数の足切り**を付ける（例: 規定数未満しか採点できない銘柄は総合ランキングに載せない＝薄データ銘柄が上位に紛れない）。総合を出すときは必ず claim別グレードを併示。
- **重み配分の妥当性は [D8 バックテスト](08-backtest-framework.md)で検証**する。総合スコアが前方アウトカム（減配回避・リターン）と相関しなければ、総合ランキングの扱いを下げ claim内に寄せる（D8の分位スプレッド・グレード較正が判断材料）。

> 本書の重み（2.5/1.5/…）は v3/v4 の**手づけスナップショット**。D8で前方アウトカムにより較正し v5 へ進める（[charter §5](00-charter-and-data-integrity.md)）。

---

## 5. 出力契約（computed_metrics への書き込み）

derive層は各指標について以下を computed_metrics に書く（data-model §8）:
- 値: `<field>`（数値 or NULL）
- status: `<field>_status` ∈ ok/zero_legit/missing/insufficient/censored
- 由来: `<field>_source` ∈ machine/override/censored
- claim別グレード: grade_dividend/valuation/health/capital（A〜D）
- `identity_ok`, `streak_is_censored`

スコアラは `<field>` と `<field>_status` だけを読んで §1.3 の式で採点する（生SQLや原データを読まない＝一方向フロー）。

---

## 6. 次への引き渡し
- **D5 X発信**: claim別グレードとstatusを投稿の品質ゲートに使う。「高配当×増配ランキング」等のフックは grade_dividend≥B かつ censored明示で構成。override由来は出典付き
- **D6 検証**: override値 vs machine値のギャップ、status分布の異常監視、golden（花王36年等）
- **実装フェーズ**: rules.yaml に `null_policy: status_based` を導入し「None→0」を撤廃。derive層が status を emit するよう改修。capex/investment_securities/cost_of_debt 取得後に #6/#12 を再評価し次 rule_version へ
