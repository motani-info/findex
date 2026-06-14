# D2: データ完全性フレームワーク詳細

**作成日**: 2026-06-14
**ステータス**: 設計（実装しない）
**親**: [00-charter-and-data-integrity.md](00-charter-and-data-integrity.md)（ノーススター）。本書は §4 を仕様レベルに具体化する。
**次**: D2.5 取得可能性スタディ（本書の各フィールドが全銘柄分そろうかを実証）

---

## 0. 本書の狙い

findex の根本欠陥は「**収集すべきデータの定義が無かったこと**」だった（旧 `stocks` が上場日を持たず、欠損に気づけなかった）。
本書はまず「**完全とは何か**」をフィールド単位で定義する（データディクショナリ）。
カバレッジ・期間充足・品質ゲートはすべて「**この定義に対して**」測られる。「揃っているか」＝「定義に対して揃っているか」。

> 原則1: 定義が先、ソースは後。ソース選定（§3）は定義（§2）を満たすための手段にすぎない。

> 原則2（目的からの逆算）: **何を集めるかは「どんな投稿フックを出したいか」から逆算する**。
> 定款の目的は正確な倉庫を作ることではなく、**Xユーザーの興味を引く切り口で投稿し続ける**こと。
> 本書の `used_by`（依存指標）列は **back_findex から引き継いだ現指標群に基づく参考**であって、データ辞書の根拠ではない。
> 指標体系そのものが旧PJの遺産であり、無検証の前提にはしない（D4で再検討）。投稿フックのカタログ（D5）が確定したら、本辞書はそれに照らして見直す。

> 原則3（完璧主義を避ける）: 柱1（データ）は柱2・柱3（分析・投稿）に到達して初めて目的を果たす。
> 全フィールドの完全を待たず、**最小データ集合（§6.5）がそろった主張から投稿を始める**。「正確でない数字を出さない」と「言えることまで黙る」は別物。

---

## 1. データディクショナリのメタモデル

各フィールドは以下の属性で一意に定義する。本書ではこれを表で表現し、実装時に機械可読（例: `data_dictionary.yaml`）へ落とす。

| 属性 | 意味 |
|---|---|
| `field` | 正準フィールド名 |
| `domain` | 識別 / 会計メタ / 株価 / 配当 / 財務PL / 財務BS / 財務CF / 資本コスト |
| `type/unit/range` | 型・単位・値域（値域外は異常として弾く） |
| `grain` | 粒度（1銘柄1値 / 銘柄×日 / 銘柄×会計年度 / 銘柄×イベント） |
| `required` | **core**（無ければ分析不可＝グレードD）/ **required**（必須・欠損で減点）/ **optional**（補完） |
| `min_history` | 必要履歴年数（時系列フィールドのみ。期間充足判定に使う） |
| `primary` / `crosscheck` | 主ソース / 照合ソース（§3） |
| `validation` | 値域・整合・golden突合などの検証ルール |
| `used_by` | このフィールドに依存する指標（欠損の影響範囲＝なぜ必要か） |

`confidence` / `source` / `as_of` / `collected_at` は**全フィールドの行が持つ来歴メタ**（§5）。ディクショナリ側では持たない。

---

## 2. データディクショナリ本体

> 注1: `used_by`（依存指標）は現指標群に基づく**参考**。指標は進化する（D4）ため固定ではない（§0 原則2）。
> 注2: 算出指標（ROE・PER等）は**生フィールドから導出**するため、ここでは原則として生の入力を定義する。
> 注3: `min_history` の数値は**暫定**。各指標が要求する遡及年数（例: 配当10年CAGR→10y、5年CAGR→5y）から D4 で確定する。現状の値は「その指標の窓に合わせた仮置き」であり恣意ではないが、指標確定まで暫定扱い。

### 2.1 識別・属性（grain: 1銘柄1値 / 不変・準不変）
| field | 型/単位 | required | 主ソース / 照合 | 役割・備考 |
|---|---|---|---|---|
| `code` | TEXT(4桁) | core | JPX / J-Quants | 主キー |
| `name` | TEXT | core | JPX | 銘柄名 |
| `market` | TEXT | required | JPX | プライム/スタンダード/グロース等。動的指標入替の判定に使用 |
| `sector33` | TEXT | required | JPX | 33業種。セクター比較・金融判定 |
| `edinet_code` | TEXT | required | EDINET | 財務XBRL紐付けの鍵 |
| `listing_date` | DATE | **core** | kabutan / minkabu | **gap set 特定の鍵**（期間充足判定の独立シグナル） |
| `founded_date` | DATE | optional | kabutan | 補助 |
| `is_active` | BOOL | core | JPX | 上場廃止で false |
| `delisting_date` | DATE | optional | JPX/適時開示 | バックテストの生存バイアス対策 |

### 2.2 会計メタ（grain: 1銘柄1値 / 年度で変わりうる）
旧実装が踏んだ「会計年度の二重定義」を断つための必須メタ。

| field | 型 | required | 主ソース | 役割 |
|---|---|---|---|---|
| `fiscal_period_end_month` | INT(1-12) | required | EDINET/J-Quants | 決算期末月（3月/12月/2月…）。FY正規化の基準 |
| `consolidated` | BOOL | required | EDINET | 連結/単体。指標を同一基準でそろえる |
| `accounting_standard` | TEXT | optional | EDINET | JGAAP/IFRS/US。項目対応の差異吸収 |

### 2.3 株価・市場（grain: 銘柄×日）
| field | 型/単位 | required | min_history | 主 / 照合 | used_by |
|---|---|---|---|---|---|
| `close_adj` | REAL/円 | core | 1y+ | J-Quants / yfinance | PER,PBR,利回り,モメンタム |
| `volume` | INT | optional | — | J-Quants | 流動性 |
| `shares_outstanding` | REAL | core | — | EDINET/J-Quants | 時価総額,EPS,BPS |

### 2.4 配当（grain: 銘柄×会計年度 ＋ 銘柄×イベント）
| field | 型/単位 | required | min_history | 主 / 照合 | used_by |
|---|---|---|---|---|---|
| `dps_annual[fy]` | REAL/円 | **core** | 可能な限り長く | J-Quants/EDINET ＋ haitoukin/IR(歴史) | 連続増配/非減配,配当CAGR,信頼性 |
| `forecast_dps` | REAL/円 | required | — | 適時開示/IR / yfinance | 予想利回り,予想配当性向 |
| `ex_date` events | DATE | required | — | J-Quants / yfinance | dps_annual構築,権利確定月（季節フック） |
| `record_month` | INT | optional | — | 適時開示 | 季節性の投稿切り口 |

> dps_annual は**正準系列**（FY粒度・4月始まり）。イベントとは別粒度で保持（地雷1）。pre2000-data.md の打ち切り・N+は本フィールドの期間充足の一事例。

### 2.5 財務 PL（grain: 銘柄×会計年度）
| field | 型 | required | min_history | 主 / 照合 | used_by |
|---|---|---|---|---|---|
| `revenue` | REAL | required | 5y+ | EDINET / J-Quants | 売上CAGR |
| `operating_income` | REAL | required | 1y+ | EDINET | 営業利益率 |
| `net_income` | REAL | required | 1y+ | EDINET | EPS,ROE,配当性向 |
| `eps` | REAL | required | 5y+ | EDINET（or net_income/shares） | EPS成長 |

### 2.6 財務 BS（grain: 銘柄×会計年度）
| field | 型 | required | 主 / 照合 | used_by |
|---|---|---|---|---|
| `total_assets` | REAL | required | EDINET | 自己資本比率,総資産 |
| `equity_attributable` | REAL | required | EDINET | 自己資本比率,ROE,BPS |
| `retained_earnings` | REAL | required | EDINET | 利益剰余金配当倍率 |
| `total_liabilities` | REAL | required | EDINET | ネットキャッシュ |
| `interest_bearing_debt` | REAL | optional | EDINET | 有利子負債比率 |
| `current_assets` | REAL | required | EDINET | ネットキャッシュ |
| `investment_securities` | REAL | **optional(入手難)** | EDINET | ネットキャッシュ（×70%）← 低カバレッジ要因 |
| `cash_and_equivalents` | REAL | required | EDINET | ネットキャッシュ |

### 2.7 財務 CF・資本コスト（grain: 銘柄×会計年度 / 1銘柄1値）
| field | 型 | required | 主 / 照合 | used_by |
|---|---|---|---|---|
| `operating_cf` | REAL | required | EDINET | FCF配当カバレッジ |
| `capex` | REAL | required | EDINET | FCF（=営業CF−capex） |
| `beta` | REAL | optional（導出） | 株価×指数の自前回帰 / yfinance | ROIC-WACC。※D2.5実測: yfinanceで95%取得可＝**入手難ではない**（当初想定を訂正） |
| `capex` | REAL | required | EDINET CF（投資活動） | FCF。※D2.5実測: **旧DBで0%＝FCF低カバレッジの真因**。最優先で埋める |
| `cost_of_debt` | REAL | optional | EDINET(支払利息/有利子負債) | ROIC-WACC。支払利息はEDINETで取得実証済み |
| `effective_tax_rate` | REAL | optional | EDINET | ROIC-WACC(NOPAT) |

> **低カバレッジの真因（D2.5実測で確定・当初推定を訂正）**: beta は95%あり入手難ではない。真の主因は ① **capex 0%**（一度も取得されず＝FCFが崩れる）② **investment_securities 不在**（yfinanceに無い→EDINETで取得実証済み）③ 複合指標(ROIC/FCF)が多フィールドの積で落ちること。詳細は [02_5-feasibility-findings.md](02_5-feasibility-findings.md)。D4 でこれら依存指標の扱い（重み・代替・不足時挙動）を決める。

---

## 3. ソース権威階層（**仮説**・D2.5で実証して確定）

> **ステータス: 仮説**。下表はまだ確定でない。**ソース選定は D2.5（取得可能性スタディ）の実証結果で決める**。
> ここでは「定義（§2）を満たせそうな候補と優先仮説」を示すに留める。

| 領域 | 主ソース候補（一次情報） | 照合 / 補完 | フォールバック |
|---|---|---|---|
| 識別・マスター | JPX 公式 | J-Quants 銘柄一覧 | — |
| 上場日・設立日 | kabutan | minkabu / EDINET沿革 | — |
| 株価 | J-Quants | — | yfinance |
| 会計メタ・財務 | EDINET XBRL（一次・**要検証**） | J-Quants statements | yfinance |
| 配当（現代） | J-Quants / EDINET | 各社IR・適時開示 | yfinance |
| 配当（2000年以前） | haitoukin / 各社IR | — | — |
| 検証 golden | 各社IR / ダイヤモンドZAi | みんかぶ | — |

優先仮説: **EDINET（財務）・J-Quants（株価/配当）・JPX（マスター）の一次情報を主**とし、yfinance はフォールバック。

> **リスク（D2.5で潰す）**:
> - **EDINET一本足リスク**: XBRL は会計基準（JGAAP/IFRS/US）・年度をまたぐパースが難しく、財務の全フィールドを一社依存にするとカバレッジ・工数が読めない。J-Quants statements との二系統で冗長化する案も含めて検証する。
> - **yfinance降格の根拠**: 真因は「データ定義の欠如＋欠損検知の欠如」であって yfinance 自体ではない（§00）。よって降格は「品質が劣るから」でなく「**一次情報を主にすべきだから**」。欠損検知が効くなら yfinance をフォールバックに残すのは合理的で、全排除はしない。

---

## 4. 照合（reconciliation）ルール

複数ソースに値があるときの決定的解決:
1. **優先順位**: `manual ≥ ir > 一次バルク(EDINET/J-Quants/JPX) > フォールバック(yfinance)`
2. **乖離検知**: 上位と下位の差が閾値超なら `confidence=要レビュー` を立て、**分析から除外**
   - 財務・株価: 相対差 10% 超
   - 配当（分割調整疑い）: 前年比 10倍 / 0.1倍（地雷3）
3. **解決の記録**: 採用値・不採用値・理由を残し再現可能にする
4. 手動・IR値はバルク再取得で**上書きしない**（§00 §4.8）

---

## 5. カバレッジ追跡（field × stock の状態）

すべての (銘柄, フィールド[, 年度]) に状態を持たせ、充足を**測定可能**にする。

| 状態 | 意味 |
|---|---|
| `verified` | 値あり＋照合/golden済み（信頼最大） |
| `present` | 値あり・未照合 |
| `insufficient` | 値はあるが期間不足（§7） |
| `missing` | 必要だが欠損 |
| `n/a` | その銘柄に適用されない（例: 金融に有利子負債比率） |

来歴メタ（`source` / `confidence` / `as_of` / `collected_at`）を各値に付与（§00 §4.2）。
カバレッジは集計してダッシュボード化し、改善の進捗（＝gapが埋まる様子）を可視化する。

> **実装注（完璧主義を避ける）**: (銘柄 × フィールド × 年度) を**materialized table で全件保持すると数百万セル**になり、初期から作るのは過剰。
> まずは来歴メタを持つ実データ行から**集計クエリで状態を導出**する（present/missing は値の有無、insufficient は §7 の充足判定で算出）。
> 専用カバレッジテーブルの materialize は、集計が重くなって初めて検討する（D3で判断）。

---

## 6. データ品質グレード（claim 単位）

> **設計変更（目的からの逆算）**: 当初は「1銘柄＝1総合グレード」でcore欠損なら投稿対象外としていた。
> しかしそれだと**配当だけ完璧な銘柄が財務欠損でDになり、「30年連続増配」という真実すら投稿できない**。
> 投稿フックは多様なので、グレードは**銘柄全体でなく「主張（claim）／指標セット単位」**で付ける。

### 6.1 識別グレード（銘柄が分析土俵に乗るか）
最低限の同定だけを見る。これを満たさない銘柄のみ全面除外。
- `identity_ok` = `code,name,market,sector33,listing_date,is_active` が `present` 以上
- `identity_ok=false` → 全面除外（そもそも何の銘柄か確定できない）

### 6.2 claim 単位グレード
「言いたいこと（claim）」ごとに、それが依存するフィールド集合で A〜D を付ける。

| claim 例 | 依存フィールド集合 | このclaimのグレードで判定 |
|---|---|---|
| 連続増配/非減配ストリーク | `dps_annual` 系列＋`listing_date` | 配当系 |
| 配当利回り・予想配当性向 | `close_adj,forecast_dps,net_income` | 配当バリュ系 |
| バリュエーション（PER/PBR/ミックス） | `close_adj,eps,equity,shares_outstanding` | バリュ系 |
| 財務健全性（自己資本比率/ROE等） | `equity,total_assets,net_income` | 財務系 |
| ROIC-WACC・FCF | `operating_cf,capex,投資有価証券,beta,cost_of_debt` | 資本効率系（入手難依存） |

| グレード | 条件（その claim の依存集合に対して） | 扱い |
|---|---|---|
| A | 依存フィールドが全て `verified`、時系列は期間充足 | その claim を投稿に全面採用 |
| B | 全て `present` 以上（一部未照合） | 採用可・必要なら注記 |
| C | 一部 `insufficient`/`missing` | **その claim は「評価不能」**として出さない（他の claim は出せる） |
| D | 依存フィールドが欠損 | その claim は出さない |

→ 1銘柄が「配当系A・バリュ系B・資本効率系D」のように**claim ごとに別グレード**を持つ。
総合スコア／ランキングは「採用可能な claim だけ」で構成し、欠けた claim は分母から除外（黙って0点にしない＝§8）。

### 6.5 投稿開始の最小データ集合（MVP）
柱1完璧主義を防ぐ安全弁。**以下がそろえば、その claim についてはこの段階でも投稿してよい**。

| 投稿カテゴリ | 必要（これだけそろえば出せる） | 不要（後追いでよい） |
|---|---|---|
| 配当ストリーク系 | `identity_ok` ＋ `dps_annual`系列(verified) ＋ `listing_date` | 財務全般・資本コスト |
| 高配当・利回り系 | `identity_ok` ＋ `close_adj` ＋ `forecast_dps`/`dps_annual` | ROIC・FCF・投資有価証券 |

入手難フィールド（投資有価証券/beta/cost_of_debt）に依存する claim（資本効率系）は**MVPに含めない**。
そろってから段階的に解放する。これにより「データ完成待ちで一切投稿できない」状態を回避する。

---

## 7. 期間充足モデル（打ち切りの一般化）

時系列フィールド／指標は `min_history` を宣言し、銘柄ごとに充足判定する。
- 充足 → 確定値
- 不足 → 「**N年以上（N+）／評価不能**」と明示（裸の数字にしない）
- 充足判定には `listing_date`（識別ドメイン）を独立シグナルに使う（データ開始＝真の開始か、欠落かを区別）

> これは配当ストリーク専用ではなく**全時系列指標の一般則**。2000年以前配当（pre2000-data.md）はこのモデルの一事例。

---

## 8. データ層の品質ゲート（silent never）

分析・投稿の**前段**でゲートする（投稿層だけに頼らない）:
- `identity_ok=false` → 全面除外（§6.1）
- **claim 単位**でゲート（§6.2）: その claim の依存集合がグレードC/D → **その claim は「評価不能」として出さない**（他の claim は出せる）
- `要レビュー` / `insufficient` フィールド → 依存指標を「評価不能」とし、**黙って0点・裸の数字にしない**
- スコアと並べて**データ品質（claim別グレード・充足）を必ず提示**
- 多フィールド golden（D6）が赤 → 該当 claim の投稿停止

> rules.yaml の現 Null ポリシー「None→生スコア0（分母から除外しない）」は本ゲートと矛盾する。D4 で再設計する。

---

## 9. D2.5（取得可能性スタディ）への引き渡し

本書のディクショナリは「**集めるべきもの**」の定義。D2.5 は「**実際に集まるか**」を実証する。検証対象:
1. 各フィールドの gap set 規模（全銘柄中どれだけ欠損/不足になるか）。特に入手難フィールド（investment_securities / beta / cost_of_debt）
2. **ソース階層（§3）の確定**: EDINET/J-Quants で core/required がどこまで埋まるか。EDINET一本足リスクの実測（パース成功率・会計基準別カバレッジ）。yfinanceフォールバックの要否
3. 埋まらない分の手動バックフィルの工数・入手性（§00 §4.8）
4. 保管モデルの方式選定（ドメイン別 source カラム vs 汎用 provenance 層）
5. 手動データの正確性担保（出典必須・二重チェック・golden）
6. **MVP（§6.5）の実在性**: 配当系・高配当系の最小データ集合が「いま」何銘柄でそろうか（＝すぐ投稿を始められる母数）

→ 結果を **claim 別グレード（§6）・ソース階層（§3）の確定**と、指標のデータ契約（D4）に反映する。
