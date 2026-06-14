# 設計: テーブル定義（データモデル）— D3改訂版

**作成日**: 2026-06-14（D3でD2.5〜D2.7の実測を反映して全面改訂）
**位置づけ**: 本書がデータモデルの**正本（設計）**。`findex/db/schema.sql` は実装フェーズで本書から再生成する（旧 schema.sql は配当中心の雛形＝凍結）。
**親**: [charter](00-charter-and-data-integrity.md) / [D2](02-data-integrity-framework.md) / [D2.5実測](02_5-feasibility-findings.md) / [D2.6影響](02_6-data-limits-and-impact.md) / [D2.7結果補正](02_7-result-override-layer.md)

---

## 0. 設計原則

1. **一方向フロー**: 取得層 → 導出層 → 評価層 → 出力層。後段は前段テーブルだけを読む
2. **粒度別テーブル**: 年間配当（FY粒度）とイベント配当（権利落ち日粒度）を混ぜない（地雷1）
3. **計算は導出層に集約**: ストリーク・CAGR等は `computed_metrics` にのみ書く
4. **全値に来歴メタ**: source / confidence / as_of / collected_at（§1）。「足りない部分を常に把握」の物理的実体
5. **履歴を消さない**: 財務・株価・スコアは年度別/日付別に積む（1行上書き禁止）
6. **修正可能(C)と構造的不能(B/D)を区別**: C群は埋める導線を持つ、B/Dはマスター補填でなく結果補正(D2.7)とN+で扱う

### テーブル一覧と層の対応

| 層 | テーブル | 粒度 | 役割 | D2.x反映 |
|---|---|---|---|---|
| 取得 | `stocks` | 1銘柄1行 | 銘柄マスター＋**会計メタ** | 会計メタ追加・edinet_code導線 |
| 取得 | `price_history` | 銘柄×日 | 調整後終値（**2000年〜**） | 2000遡及・ソース分担 |
| 取得 | `dividend_events` | 銘柄×権利落ち日 | 配当イベント生データ | 変更なし |
| 取得 | `dividend_annual` | 銘柄×会計年度 | 年間配当の正準系列 | 来歴メタ拡張 |
| 取得 | `financial_snapshots` | 銘柄×会計年度 | 財務諸表（**J-Quants+EDINET**） | 入手難フィールド追加 |
| 取得 | `result_overrides` | 銘柄×フィールド | **公表結果による補正（汎用）** | streak_overridesを一般化 |
| 導出 | `computed_metrics` | 1銘柄1行 | 全派生指標の唯一の出口＋**claim別グレード** | グレード列追加 |
| 評価 | `dividend_scores` | 銘柄×採点日 | スコア履歴 | 変更なし |
| 評価 | `rule_versions` | 1ルール1行 | rules.yaml版管理 | 変更なし |
| 出力 | `post_log` | 1投稿1行 | X投稿履歴 | 変更なし |
| 運用 | `run_log` / `schema_version` | — | 実行ログ・世代 | 変更なし |

---

## 1. 来歴メタ（全取得テーブル共通の規約）

旧実装の根本欠陥（欠損に気づけない）を断つ。**取得層の各テーブルは値カラムに対し以下を持つ**（粒度に応じカラム or 別正規化）:

| メタ | 意味 | 例 |
|---|---|---|
| `source` | 一次ソース | jquants / edinet / yfinance / haitoukin / ir / manual |
| `confidence` | verified（照合済）/ present（未照合）/ review（乖離検知） | §D2 §5 |
| `as_of` | 値が指す時点（決算期末・基準日・公表時点） | 2025-03-31 |
| `collected_at` | 取得時刻（TTL・鮮度判定） | 2026-06-14T… |

> **カバレッジ追跡は materialize しない**（D2.5 §5）。上記メタを持つ実データ行から**集計クエリで状態を導出**（present/missing/insufficient）。重くなったらD3後段でビュー/テーブル化を判断。

---

## 2. `stocks` — 銘柄マスター＋会計メタ

**役割**: 全上場普通株（約3,842）の不変・準不変情報＋FY正規化に要る会計メタ。
**source**: JPX公式Excel（コード/名称/市場/業種）、**EDINETコードリスト（edinet_code/決算日/連結＝3,842件・実測取得済）**、kabutan（上場日）。

| カラム | 型 | クラス | 説明 |
|---|---|:--:|---|
| `code` | TEXT PK | A | 4桁証券コード |
| `name` | TEXT | A | 銘柄名 |
| `market` | TEXT | A | プライム/スタンダード/グロース 等 |
| `sector33` | TEXT | A | 33業種 |
| `edinet_code` | TEXT | C→A | EDINETコード。**EDINETコードリストzipで即埋まる**（旧0%） |
| `fiscal_period_end_month` | INT | A | 決算期末月。**コードリストの「決算日」由来**。FY正規化の基準（地雷2） |
| `consolidated` | INT | A | 連結有無。コードリスト由来。指標を同一基準に |
| `accounting_standard` | TEXT | C | JGAAP/IFRS/US。**EDINETパースのラベル辞書切替に必須**（IFRSは科目名が違う） |
| `listing_date` | TEXT | **C(0%)** | 上場年月日（kabutan）。**打ち切り判定の独立シグナル**。要収集（地雷7） |
| `founded_date` | TEXT | C | 設立年月日（補助） |
| `first_data_date` | TEXT | 導出 | DB内最古データ日（**単独では打ち切り判定不可**） |
| `is_active` | INT | A | 1=現役、0=上場廃止 |
| `delisting_date` | TEXT | C | 上場廃止日（生存バイアス対策） |
| `updated_at` | TEXT | — | 更新時刻 |

**地雷メモ**: `first_data_date`≠会社年齢。`listing_date` と必ず併用（旧実装はlisting_date 0%で打ち切りに気づけなかった＝再構築のきっかけ）。

---

## 3. `price_history` — 株価履歴（2000年〜）

**役割**: 調整後終値。配当利回り・PER・PBR・時価総額・モメンタムの原資。
**source**: 直近=J-Quants `/equities/bars/daily`（**現契約は2024-03〜のみ**）、深い遡及=yfinance（**2000-01-04が下限**・実測）。**pre-2000は構造的に存在しない（クラスD）**。

| カラム | 型 | 説明 |
|---|---|---|
| `code` | TEXT | 証券コード |
| `date` | TEXT | 日付（YYYY-MM-DD） |
| `close_adj` | REAL | 調整後終値（yfinance AdjC / J-Quants AdjC） |
| `volume` | INTEGER | 出来高 |
| `source` | TEXT | jquants / yfinance |

**PK**: (`code`, `date`)。
**運用メモ**:
- **初回は2000年まで遡及取得**（旧DBは2024-06〜しか無い＝収集不足。yfinanceで回復可）。日次は最新分のみ追記。
- J-Quants現契約は2年窓のため、**長期株価はyfinanceが主、J-Quantsは直近の補完**という分担。
- pre-2000の株価・PER/PBRは**取得不能を明示**（評価不能。捏造しない）。

---

## 4. `dividend_events` — 配当イベント（生データ）

**役割**: 権利落ち日ベースの実イベントのみ。`dividend_annual` の events ソースの原料。
**source**: J-Quants（現契約 `/fins/dividend` は403のため）yfinance `Ticker.dividends`（1999年9月以降）。**更新頻度**: 半年。

| カラム | 型 | 説明 |
|---|---|---|
| `code` | TEXT | 証券コード |
| `ex_date` | TEXT | 権利落ち日 |
| `amount` | REAL | 分割調整済み1株配当 |
| `source` | TEXT | yfinance 等 |

**PK**: (`code`, `ex_date`)。
**地雷メモ**: 合成レコード禁止（地雷1）。年間値は `dividend_annual` に直接入れる。1999年以前は存在しない→バックフィルで補う。

---

## 5. `dividend_annual` — 会計年度別配当（正準系列）⭐

**役割**: **ストリーク・配当CAGRはこのテーブルだけから計算**。findexの心臓部。
**source**: `events`（構築）/ `jquants`（fins/summary の DivAnn・現在〜約2年）/ `haitoukin`（2000年以前バックフィル）/ `ir` / `manual`。

| カラム | 型 | 説明 |
|---|---|---|
| `code` | TEXT | 証券コード |
| `fiscal_year` | INTEGER | **4月始まり会計年度**（地雷2） |
| `dps` | REAL | 年間1株配当（分割調整済み） |
| `source` | TEXT | events / jquants / haitoukin / ir / manual |
| `confidence` | TEXT | verified / present / review |
| `as_of` | TEXT | 公表/基準時点 |
| `updated_at` | TEXT | 更新時刻 |

**PK**: (`code`, `fiscal_year`)。
**優先順位（競合時）**: `manual` > `ir` > `haitoukin` > `jquants` > `events`（手動の確定値を機械再構築で潰さない）。
**地雷メモ**: 会計年度集計（地雷2）/ events初年度は期中の可能性で捨てる（地雷1）/ 分割不一致(NTT/SBG/電通総研)は境界異常チェックで弾きoverride（地雷3）。

---

## 6. `financial_snapshots` — 年度別財務（J-Quants + EDINET）

**役割**: ROE・自己資本比率・FCF・ROIC・ネットキャッシュ等の原データを**年度別に履歴保持**。
**source分担（D2.5実測）**:
- **J-Quants `/fins/summary`**: 現在〜約2年の主要財務（売上/営業益/純益/EPS/総資産/自己資本/現金/CFO・CFI・CFF/発行株数/配当/予想）。1コールで潤沢。
- **EDINET 有報XBRL（2008〜）**: 入手難の深いBS（投資有価証券・有利子負債・支払利息・流動資産・利益剰余金）。**会計基準別ラベル辞書でパース**。

| カラム | 型 | クラス | source | 説明 |
|---|---|:--:|---|---|
| `code`, `fiscal_year` | TEXT,INT | — | — | PK |
| `revenue`, `operating_income`, `net_income`, `eps`, `bps` | REAL | A | jquants | PL・1株（売上CAGR/営業益率/ROE/EPS成長） |
| `shares_outstanding` | REAL | A | jquants | 時価総額・EPS |
| `total_assets`, `equity_attributable` | REAL | A | jquants/edinet | 自己資本比率・ROE |
| `operating_cf` | REAL | A | jquants(CFO) | FCF |
| `capex` | REAL | **C(0%)** | **edinet** | **FCF=CFO−capex の鍵。旧0%＝FCF崩壊の主因** |
| `cash_and_equivalents` | REAL | A | jquants | ネットキャッシュ |
| `retained_earnings` | REAL | A | edinet | 利益剰余金配当倍率（実測99.5%） |
| `current_assets`, `total_liabilities` | REAL | A/C | edinet | ネットキャッシュ |
| `interest_bearing_debt` | REAL | C | edinet | 有利子負債比率・cost_of_debt |
| `interest_expense` | REAL | C | edinet | **cost_of_debt算出**（ROIC-WACC） |
| `investment_securities` | REAL | **C(不在)** | **edinet** | ネットキャッシュ×0.7。旧DBに無い→EDINETで取得 |
| `effective_tax_rate` | REAL | C | edinet/導出 | ROIC NOPAT |
| `beta` | REAL | A | **導出** | **旧DB95%有＝入手難ではない**（D2.6訂正）。株価×TOPIX回帰で自前算出 |
| `market_cap` | REAL | A | 導出 | 株価×株数 |
| `source`, `confidence`, `as_of`, `collected_at` | TEXT | — | — | 来歴メタ（§1） |

**PK**: (`code`, `fiscal_year`)。
**D2.6反映**: 旧低カバレッジの主因は ①capex 0% ②investment_securities不在 の**収集漏れ**（クラスC＝修正可能）。betaは入手難ではない（訂正）。

---

## 7. `result_overrides` — 結果補正（公表値オーバーライド・汎用）⭐ D2.7

**役割**: マスターが取れない(B/D)が**結果だけ公表される**指標を、出典付きで補正。`streak_overrides`(12件)を**フィールド非依存に一般化**。
**source**: ダイヤモンドZAi・各社IR・みんかぶ（**集計主体が明確なもののみ**）。

| カラム | 型 | 説明 |
|---|---|---|
| `code` | TEXT | 証券コード |
| `field` | TEXT | 補正対象（consecutive_dividend_growth_years 等）。**汎用化の鍵** |
| `value` | REAL | 公表された結果値 |
| `as_of_fiscal_year` | INTEGER | **その値が何年度時点か**（経年補正に必須） |
| `source` / `source_url` | TEXT | 出典（信頼ソース限定） |
| `definition_note` | TEXT | **定義差の根拠**（例「上場前から起算」＝最大の地雷対策） |
| `confidence` | TEXT | verified（2ソース一致）/ single |
| `verified_at` / `verified_by` | TEXT | 検証時刻・方法 |

**PK**: (`code`, `field`)。
**採用ポリシー（D2.7 §2.2）**: ①信頼ソース限定 ②**昇格のみ**（override≥機械計算）③採用時は当該指標の is_censored 解除（claim単位）④as_ofで経年補正（機械で確認できた近年分を加算）⑤重要銘柄は2ソースでverified。
**対象の線引き**: 連続増配/非減配=✅、減配信頼性=🔶、CAGR=raw補填が本筋、**pre-2000株価/PER/PBR=対象外（結果が公表されない）**。

---

## 8. `computed_metrics` — 派生指標＋claim別グレード（導出層の出口）⭐

**役割**: 前段から計算した全派生指標を1銘柄1行で保持。スコアラはここだけ読む。
**source**: 導出層（dividend_annual + result_overrides + financial_snapshots + price_history + stocks）。

| 区分 | カラム |
|---|---|
| 価格由来（日次） | `per`, `pbr`, `current_market_cap`, `div_yield`, `mix_coefficient`, `net_cash_per` |
| 財務由来（四半期） | `equity_ratio`, `roe`, `operating_margin`, `eps_growth_5y`, `revenue_growth_5y_cagr`, `roic_minus_wacc`, `fcf_payout_coverage`, `retained_earnings_div_ratio`, `payout_ratio` |
| 配当由来（半年） | `annual_div`, `consecutive_no_cut_years`, `consecutive_dividend_growth_years`, `dividend_growth_10y_cagr`, `dividend_reliability`, `dividend_cut_count_20y` |
| **品質（D2.6/D2.7）** | `streak_is_censored`, **`grade_dividend`, `grade_valuation`, `grade_health`, `grade_capital`**（claim別 A〜D）, `identity_ok` |
| 由来フラグ | 各指標の `*_source`（machine / override / censored）で「結果補正が効いたか」を記録 |
| 更新時刻 | `price_computed_at`, `fin_computed_at`, `div_computed_at` |

**PK**: `code`。
**最重要**: `streak_is_censored`（N+表示）＋ **claim別グレード**（D2 §6・配当系Aでも資本効率系Dなど銘柄内で別評価）。グレードは前段の来歴メタから**導出**（materialize不要）。

---

## 9. `dividend_scores` / `rule_versions` / `post_log` / `run_log` / `schema_version`

| テーブル | 役割 | 要点 |
|---|---|---|
| `dividend_scores` | 現在採点を日付別に積む（推移） | PK(`code`,`scored_at`)、`rule_version_id`、`total_score`、`score_json` |
| `rule_versions` | rules.yaml を SHA256 で版管理（再現性） | `id` AUTO、`rules_sha256` UNIQUE |
| `themes` | X/サイトのテーマ定義レジストリ（D5） | `theme_id`、`name`、`angle_ref`、`format`(A/B/C)、`enabled` |
| `post_queue` | 生成済み・投稿待ち（D5） | `id`、`theme_id`、`body`、`image_paths`、`claims`(json：使用数字とstatus/source/as_of＝事後監査)、`gates_passed`、`status`∈draft/approved/posted/blocked |
| `post_log` | X投稿履歴。本文SHA256で30日窓の二重投稿防止 | `id` AUTO、`status`∈posted/failed/skipped、`engagement`(json) |
| `run_log` | バッチ実行記録 | `id` AUTO、`job`/`started_at`/`status` |
| `schema_version` | スキーマ世代 | `version` PK |

### バックテスト（D8・モデル検証）

> [D8 バックテスト基盤](08-backtest-framework.md) のPIT（時点正確）スコアとアウトカムを保持。現在採点 `dividend_scores` とは分け、再現可能なバックテスト結果を別系統で持つ。

| テーブル | 役割 | 要点 |
|---|---|---|
| `backtest_runs` | 1回のバックテスト実行 | `run_id`、`rule_version_id`、`as_of_grid`、`universe_def`、`params_json` |
| `backtest_scores` | **PIT再現スコア**（as_of別・入力をas_offで絞って算出） | `run_id`、`code`、`as_of_date`、`total_score`、`score_json`、`grade_*` |
| `backtest_outcomes` | 前方アウトカム | `code`、`as_of_date`、`horizon_y`、`fwd_div_cut`、`fwd_dps_cagr`、`fwd_total_return`、`fwd_max_dd` |
| `backtest_metrics` | 評価結果 | `run_id`、`level`(total/claim/indicator)、`key`、`metric`(spearman/IC/decile_spread/grade_calib)、`value`、`sample_n` |

### 対象ユニバース・生存バイアス（[design-review](design-review.md) #8）
- `stocks` は**国内上場普通株のみ**（ETF/REIT/優先株/出資証券を除外）。正準ユニバースは JPX一覧から普通株抽出で確定（[charter §2](00-charter-and-data-integrity.md)）。
- 上場廃止銘柄も `is_active=0`＋`delisting_date` で**残す**（D8の時点ユニバース・生存バイアス排除に必須）。`delisting_date` はクラスC・D8の前提条件。

> **Nullポリシー（D4で確定）**: 現 rules.yaml「None→生スコア0」はアンチパターン。**①欠損（減点）②正当な0（増配なし＝実値）③構造的不能（若い銘柄＝分母から除外）**を区別する。本モデルの来歴メタとグレードがその判定材料。

---

## 10. 参照グラフ

```
stocks ──code──┬─< price_history (2000〜, jquants/yfinance)
               ├─< dividend_events ──build──> dividend_annual >──┐
               ├─< financial_snapshots (jquants+edinet)         │
               └─< result_overrides (公表結果・汎用) ───────────┤
                                                                ▼
                              computed_metrics (派生指標＋claim別グレード)
                                  機械計算 →(昇格のみ)result_override →(不足)N+
                                                     │
                                                     ▼
                            dividend_scores >── rule_version_id ──> rule_versions
                                                     │
                                                     ▼
                                              post_log（投稿）
```

外部キーは張らず `code` で論理結合（SQLite・移行容易性）。整合性は半年次の整合性チェックジョブ＋D6照合（override vs 機械計算のギャップ検知）で担保。
