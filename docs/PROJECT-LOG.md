# findex プロジェクトログ

セッションをまたいで文脈を失わないための公式記録。**新しい作業を始める前に必ず本書とノーススター（[00-charter-and-data-integrity.md](design/00-charter-and-data-integrity.md)）を読むこと。**
フェーズが終わるごとに追記する（上に新しいフェーズを積む）。

---

## doc14 — ソートの誠実性＋net_cash無配フロア＋large_cap8軸化（第2次Geminiレビュー）（2026-06-19）

Gemini が posts.html を実市場で再検証し「数値は嘘でなくても並び順・見せ方がミスリード」と指摘。
doc12/13（ゴーストデータ根絶）に続く第2次FB。実DB・実コードで全指摘を裏取りし対応。
正本: [14-sort-honesty-and-net-cash-floor.md](design/14-sort-honesty-and-net-cash-floor.md)。

### 対応（コミット `22280f5`＝①②③／本コミット＝④列モデル）
- **② large_cap ソート**: 時価総額降順＝単なる大企業順の「見せ方の嘘」を、看板どおり**総合スコア
  降順**へ。連続増配 weight=2.5 で配当が主軸＝総合順でも高利回り×長期増配が上位（配当の過小評価は実データ上なし）。
- **① net_cash 無配**: top10の6/10が無配（キャッシュトラップ）→`YIELD_FLOOR_VALUE=1.5%`で無配排除
  （`_net_cash_eligible`述語化）。doc09でバリュー系を免除した判断を改定。バリュー主旨は温存。
- **③ div_growth**: doc12の `g_years>=3` で対応済（追加作業なし）。
- **④ 列モデル**: 6/8/14軸を実カードで比較し**8軸**採用（large_capのみ拡張）。`_rank_card` に
  `col_widths`＋`table-layout:fixed`/`<colgroup>` を追加（#最小/コード固定/銘柄広め可変/データ列一定）。
  強調(teal)は「高い＝良い」指標(ROE/総合/長期増配)に限定し、配当性向・PERは非強調(`pct_plain`/`x_plain`)
  でノイズ解消。デザインは本物の `_CARD_CSS` 準拠。

検収: **pytest 112 passed** / golden **18/18 不整合0** / post-gallery 再生成（large_cap=8軸カード）。

---

## doc13 — J-Quants確定無配の取り込み（ghost利回りの根治・Track B）（2026-06-19）

doc12 が Track A（テーマ層）で②③④を是正した後、残した①サンウェルズ9229 の ghost利回り9.7% を
**取得層**で根治。正本: [13-jquants-confirmed-dividends.md](design/13-jquants-confirmed-dividends.md)。

### 根本原因
`dividend_annual` は yfinance の実支払い（ex-date）だけで構築。**無配＝ex-dateイベント無し**のため
yfinance は構造的に無配年の行を立てられず、無配転落後も最新が直近の有配年に固定される。鮮度ゲート
`DIVIDEND_RECENCY_YEARS=3` も未発火（gap=2）→ `div_yield=直近DPS/暴落株価=9.7%`（status=ok）の幽霊。

### 実装（コミット `fbf4b0b`・fill-absent-無配-only）
- 既配線の `JQuantsClient.fins_summary` レスポンスにある確定年間配当 `DivAnn`（0.0=無配含む）を
  従来パーサが捨てていた。新パーサ `parse_fy_dividends`（FY実績のみ・予想/空文字は除外）で年度別抽出。
- ビルダー `_JQuantsDividendBuilder` / `build_jquants_dividends`: 確定無配(0.0)で**既存行が無い年だけ**
  source=`jquants` で挿入。既存系列（events/override/haitoukin/manual/ir）は一切上書きしない＝
  **golden保護を構造で担保**。CLI `findex dividends-jq --cohort|--codes|--all`（resume安全）。
- derive側は変更不要: 最新DPS=0.0 → 既存 `div_yield: dps==0 → zero_legit`（利回り非表示）に自然追従。

### 全銘柄反映（2026-06-19・ユーザー起動の背景ジョブ）
- `dividends-jq --all`: ok=3695・**無配補完=1281行/710社**・failed=3（429/timeout）→ `--codes` で再取得し
  failed=0、3734/3734 完全カバレッジ。→ `derive --all` → `score --all` → `post-gallery --all` → `verify --all`。
- 検収: **golden 18/18 不整合0**・computed 99.5%・pytest 108 passed。Geminiの**5銘柄
  （9229/2491/6927/8165/3989）すべて posts.html から消失（0 hits）**を確認＝Track A+B でゴースト根絶。

---

## doc12 — 生利回り系テーマの罠フィルタ（タコ足/偽ROE/復配ジャンプ・Track A）（2026-06-19）

Gemini が再生成後の posts.html を実市場と突合し「実態と乖離したゴーストデータ4つ」を報告。
実データ・実コード・実ランキングで裏取りし、4指摘すべて「実在」を確認。doc10 が未カバーだった
**生利回り系テーマ**（high_yield/low_pbr_yield/small_value/value_quality/div_growth）の罠を是正。
正本: [12-theme-layer-trap-filters.md](design/12-theme-layer-trap-filters.md)。

### Track A 実装（themes.py・ユーザー承認方針）
- **③ タコ足ゾンビ**: 共有述語 `_is_takoashi`（payout>100% かつ rel<0.6/None）を
  high_yield/low_pbr_yield/small_value から除外。payout>100%でも rel高い実績株は温存（単純
  payout一律除外は健全株を誤殺＝棄却）。→ バリューコマース2491/ヘリオステクノ6927 を除去。
- **② 偽ROE**: value_quality に `operating_margin>0`。本業赤字×特益ROEの罠（千趣会8165=営業益率
  −6.2%/4年連続赤字/自己資本4年で半減）を除外。巻き込み1件のみ。
- **④ 復配ジャンプ**: div_growth に `g_years>=3`。連続増配0年の復配（シェアリング3989）を除外。
  g_years 分布上 ≥1 と ≥3 は top10 同一＝概念明快な ≥3 採用。

### 残（Track B・別GO待ち）
①サンウェルズ9229 の ghost利回り9.7%（無配転落の予想配当が dividend_annual に未取得・暴落
株価で除算）は**取得層**課題。予想配当/当年無配の捕捉が根治。全銘柄fetch＝レート制限鉄則に従う。

検収: pytest **106 passed** / golden **18/18 不整合0** / post-gallery 再生成で 5銘柄の top10 消失を確認。

---

## doc11 — 株式分割基準ズレの根本治療＋専門家レビュー対応（2026-06-19）

yfinance `close_adj`（分割調整済み）と J-Quants の EPS/BPS/shares（報告値＝分割前基準）の
基準ミスマッチで、分割後に PER/PBR/時価総額/配当性向が壊れる問題を根治。

### 到達したこと（コミット）
| 内容 | commit |
|---|---|
| `stock_splits`テーブル新設＋`findex splits`コマンド＋derive時動的補正（`_split_adjustment_factor`） | `4f295de` |
| 配当性向・DOEの分割基準ミスマッチ修正（レビューで露見した①の取りこぼし） | `48aa2d8` |

- yfinance `.splits` から 3079 件取得（逆分割・異常 ratio<1.0 の 745 件は除外）
- `compute_price_metrics` と `compute_financial_metrics` の両方で as_of 以降の分割累積係数により
  EPS/BPS/shares を分割後基準へ補正（純益・自己資本・総資産は総額なので補正不要）
- `financial_snapshots` の報告値は不変（出典明示の原則）。補正は compute 時のみ
- pytest 99 passed / golden 18/18 不整合0

### 効果（ビフォーアフター）
| 銘柄 | PER | 配当性向 |
|---|---|---|
| 2146 UTグループ | 0.78→11.65 | —→81.6% |
| 5401 日本製鉄 | 1.62→8.11 | —→102.6% |
| 3798 ULSグループ | 1.70→17.05 | — |
| 8001 伊藤忠 | （正）15.09 | 6.8%→34.1%（公式コミット35-40%と一致） |
| 8078 阪和興業 | 7.55 | 5.2%→25.8% |

### A-2: 65% CAGRサニティ閾値 → 据え置き確定
分割補正後は ok 最大 64.4% で閾値が実質不要化。50% に締めると正当な配当成長株 68 銘柄
（三越伊勢丹/京急/SCREEN等）を誤除外するため 65% 据え置き（安全弁として残す）。

### 専門家レビュー（post.html Deep Dive）の検証結果
全指摘を実データ・コードで検証:
- **① 配当性向過小評価 → 本物のバグ（本フェーズのリグレッション）→ 修正済み(48aa2d8)**
- **② タコ足配当にGrade A → 本物の設計欠陥（未対応・要判断）**: `grade_dividend` は
  「指標が算出できたか」のみ判定し「値が良いか」を見ない。reliability=0.0 でも status=ok → A。
  値ベース化（reliability低/payout>100%の扱い）は設計変更のため保留
- **③ ROIC spread一致 → 誤り**: 実値 0.343099 vs 0.343029 で異なる（表示1桁丸めの誤認）
- **Section2① 千趣会の毀損型ROE → 機構の誤診**: 自己資本比率 65.2% で健全、grade_health=B
- **Section2② サンウェルズ ghost利回り → データ鮮度の論点**: stale窓3年で2年差すり抜け＋
  無配年データ欠落。コードバグではなく既知トレードオフ
- **Section2③ 東洋証券の市況株混入 → 分類の弱さ（軽微）**: quality=sound だが本来 cyclical

### レビュー指摘の追加修正（2026-06-19・derive層で修正可能だったもの）
| 指摘 | 内容 | commit |
|---|---|---|
| ② | `grade_dividend` を reliability の値でキャップ（減配常習株のA→C。A:約2095→530件） | `0bf73e5` |
| ③ | 減配2回以上の市況株を増配の質 cyclical に固定（東洋証券 sound→cyclical） | `77c0616` |

### 残課題（derive層では安全に直せない＝取得層/データ品質の問題）
1. 配当鮮度: サンウェルズ型 ghost 利回り。鮮度窓を締めると決算ラグの正常22銘柄を巻き込む
   誤検知が出るため**閾値変更は不可**。本質はFY無配転落が `dividend_annual` に未取得という
   取得層のギャップ → fetch層で当年無配/予想配当を捕捉する改善が必要
2. PER<1 の3件（8303 SBI新生=EDINET抽出のeps異常/8729 ソニーFG=最近上場で株価史短い/
   8166 タカキュー=FY異常）は分割でなく各々別原因のデータ品質問題。J-Quants由来の異常eps
   は0件で体系的バグではない（EDINETフォールバック時の抽出品質）

正本: docs/design/11-split-adjustment-plan.md。

---

## 実装フェーズ前半 — Phase 0〜2（取得層まで）（2026-06-15）

設計完結＋レビュー是正の後、ユーザーGOで**実装凍結を解除**。各サブフェーズで**検証コホート（外れ値・難ケース35社）を実データで叩いてから次へ**進める方式（[[feedback_findex_verify_with_real_data]]「実データが神」）。コホートは旧28社（ストリーク中心）にIFRS/US基準・無配・減配・金融大型を足して35社に拡張。

### 到達したこと（コミット）
| Phase | 内容 | commit |
|---|---|---|
| 0 | D3スキーマ全面再生成（18テーブル）＋コホート拡張 | `b060f3e` |
| 1 | マスター3,734社（普通株=内国株式のみ）・EDINET会計メタ・旧DB移行（haitoukin配当622/override12）・上場日 | `9ddc7b9` |
| 2-a | EDINET会計基準別ラベル辞書（YAML版管理・design-review #4） | `df10526` |
| 2-c | financial_snapshots（J-Quants基礎＋EDINET深いBS） | `ba50b10` |
| 2-d | 株価2000遡及（yfinance分割調整Close） | `cf2d7cc` |
| 2-e | 配当イベント再取得・年度集計・能動洗浄 | `bf62106` |
| 2-e追補 | 配当接合の単位統一(A)・FY2000穴解消(B) | `3e320f2` |

コホートカバレッジ: 株価214,606行・財務72行・配当963行・会計基準100%・テスト22 passed。

### ⚠️ 実データ検証で捕捉・是正した罠（naiveなら見逃す・最重要の学び）
| # | 罠 | 実データでの発覚 | 是正 |
|---|---|---|---|
| 1 | yfinance上場日の**データ床はバンド**（単一値でない） | 古参（栗田/ユニチャーム/小林）を`2001-01-04`＝真の上場日と誤認 | 床カットオフ(2001-01-04)＋元日判定でNULL化。真値は床より後の実取引日のみ |
| 2 | `EarnForecastRevision`が`CurPerType=FY`で混入しSales空 | イオン/メルカリに空財務行 | `DocType`に`FinancialStatements`含み Sales有のみ採用 |
| 3 | EDINET有報年度＞J-Quants実績窓で深いBSが宙に浮く | イオンFY2026 | 深いBSのみ行を残す |
| 4 | yfinance`Adj Close`は**配当込み**でYoC/PERを歪める | NTT 25:1分割で`Close`が分割のみ調整と判明 | `close_adj`に`Close`採用（`Adj Close`不使用） |
| 5 | 配当の**分割単位不整合**（haitoukin当時株数 × events分割調整済） | KDDI haitoukin FY1999=3.0 vs events1.49（間の分割が未調整。実は連続） | 接合で「生/分割除算」2仮説を突合し整合する方を採用、混線はreviewフラグ |
| 6 | 地雷1の**無条件初年度ドロップ**が完全な年まで削除 | 花王FY2000(=10+12)が消え接合に穴 | 初年度の支払回数が次年度より少ない時のみ除外→花王1989-2025連続 |

### 設計と実態のズレ（設計書にFB済み）
- **listing_date**: 設計はkabutan名指しだが**kabutanは全面JSレンダリングで静的取得不可**（Yahoo/IRBANK/みんかぶ同様）。→ yfinance firstTradeDate主（2000-2001床はNULL）＋ kabutan(Playwright)補完。ユーザー承認済
- **price close_adj**: 設計は"AdjC"だが配当込みはYoCを歪める → 分割のみ調整の`Close`に訂正
- **EDINET会計基準パース**: AccountingStandardsDEIで基準判別。**IFRSはinvestment_securities/current_assetsが構造的に単独タグ無し→insufficient**（欠損でなく該当なし）。**US GAAP連結は構造化XBRLに出ない→全項目censored→grade_capitalフォールバック**（design-review #4を実証）
- **能動洗浄(#7)**: 「重複年の照合」だけでは接合の単位ズレを取り逃す（重複年ゼロのため）→ 分割正規化＋接合連続性で検査する方式に強化

### 次フェーズ
**Phase 3（導出層）**: ストリーク（result_overrides昇格→N+・**単年seam穴の橋渡し**＝リンナイFY2001等）・YoC＋増配の質・DOE・5状態status・**claim別グレード**を `computed_metrics` に。`streaks.py`ギャップ打ち切りバグもここで修正。

---

## Phase 1 — 設計フェーズ：定款の確立と軌道修正（2026-06-14）

### このフェーズで到達したこと
- findex v2 を**ゼロから設計し直す**方針を確立（旧実装 `../back_findex` は切り離し、参照元としてのみ使う）
- **定款（サービスのコアコンセプト）**を明文化し、データ完全性を土台とするアーキテクチャを確立
- 設計の途中で**重大な誤解が発生し、ユーザー指摘により是正**（下記「犯した過ちと是正」が本フェーズ最大の学び）
- 成果物はすべて markdown + HTML（`uv run python scripts/build_docs_html.py` で再生成、`docs/html/` でレビュー）

### 定款（最上位制約・不変）
> あらゆる上場株式について、**必要なデータを正確に保持し、足りない部分を常に把握できる**ことを土台に、
> **独自指標（進化し続ける指標群）**で多角的に分析し、Xユーザーの興味を引く切り口で投稿し続ける。

- 柱1 正確なデータ基盤（全銘柄・必要データの保持＋充足把握）← 土台
- 柱2 独自指標による多角評価（**指標群は進化する。数は本質でない**）
- 柱3 Xユーザーの興味を引く切り口での発信
- 土台原則: **正確でないデータは「無価値」でなく「有害」。確証を持てない数字は分析にも投稿にも一切流さない。**

### ⚠️ 犯した過ちと是正（最重要・繰り返さないこと）

| # | 犯した過ち | なぜ起きたか | 正しい理解（是正後） |
|---|---|---|---|
| 1 | データ品質を「**2000年以前の配当**」に狭めた | `back_findex` がその切り口で書かれており、それを設計の前提にした | データ不足・不正確は**全銘柄・全フィールド**の問題。財務は universe 半分が低カバレッジ。2000年配当は問題空間の1セル |
| 2 | 「**18指標**」を定款のコアに固定しようとした | 旧 README/記憶の「18指標」を不変と誤認 | 指標は**進化する**（追加・廃止・重み変更）。コアは「数」でなく「版管理された進化する指標システム」 |
| 3 | **yfinance が根本原因**と診断した | 表層の症状に飛びついた | 真因は ①**収集すべきデータの定義が不完全**だった ②**欠損に気づけない設計**だった。ソース変更だけでは直らない |
| 4 | **完全なデータ取得を前提**にした | 実現可能性を検証せず理想を前提化 | 全データ完全は**物理的に不可能**（back_findex結論）。ゴールは「充足状況を100%正確に把握し、持てないものは正直に扱う」 |
| 5 | 進捗を**チャット内ウィジェット**で可視化した | ユーザーの作業環境を考慮せず | レビュー成果物は**HTMLファイル**で出す |
| 6 | 設計確定前に**実装（雛形）を進めた** | 手応えを急いだ | **設計確定まで実装凍結**。コードを書かない |

**メタ教訓（最も大事）**:
> `back_findex` は「部品・地雷知識の参照元」であって、**設計の前提・出発点にしてはならない**。
> 旧PJの切り口をなぞると、ユーザーが新findexを立ち上げた目的（旧設計の前提のまま進む誤りを断つこと）そのものを裏切る。
> 常に [ノーススター](design/00-charter-and-data-integrity.md) を正本とし、問題を一領域に狭めない。

### 確定した設計判断
- **データソース**: 一次情報（EDINET=財務XBRL / J-Quants=株価・配当 / JPX=マスター / kabutan=上場日 / 各社IR）を主に。**yfinance はフォールバックに格下げ**
- **設計の出発点はデータディクショナリ**（収集すべきデータの完全定義）。ソース選定はそれを満たす手段
- **取得できないデータ**は、カバレッジ追跡で gap を列挙 → マスターデータ（上場日等）で対象銘柄を特定 → 1社ずつIR/HP収集 → 来歴付きで保管（バルクで上書きしない）。`dividend_annual.source` / `streak_overrides` がその先行実装
- **銘柄データグレード A〜D**: Dは分析・投稿から除外（誤情報より「出さない」が正しい）
- **検証は約30社コホート**（`data/verification_cohort.csv`）で回す（レート制限対策）
- **DB**: 開発は `~/.findex/db/findex_v2.db`。旧 `~/.findex/db/findex.db`（218MB・収集済み）は**移行元として温存・直接触らない**

### 成果物（Phase 1 で作成、`docs/html/` でHTML閲覧可）
- `docs/design/00-charter-and-data-integrity.md` — **ノーススター（正本）**
- `docs/requirements.md` — 要件定義書（※2000年に寄った前提を含む。D2以降で是正予定）
- `docs/design/data-model.md` — テーブル定義（同上・改訂予定）
- `docs/design/data-workflow.md` — ワークフロー（同上・改訂予定）
- `docs/design/pre2000-data.md` — 2000年問題（データ完全性の**一事例**に位置づけ是正済み）
- `data/verification_cohort.csv` / `data/golden_streaks_zai_20260601.csv` — 検証データ
- `scripts/build_docs_html.py` — md→HTMLビルダー

### ⚠️ 既存コードの注意（凍結中）
`findex/` 配下に雛形コード（schema.sql / streaks.py / fetch基盤 / CLI / tests）が存在するが、
これは**軌道修正（定款確立）より前に書かれ、狭い設計（配当中心）を部分的に体現している**。
**設計確定（D2以降）まで凍結。流用する際は必ずノーススターと突合してから**。盲目的に使わない。

### 現在地と次フェーズ
- 状態: **設計フェーズ・実装凍結**。D1（ノーススター）完了、**D2 改訂済み（目的志向バイアス是正を反映）**
- D2 成果物: `docs/design/02-data-integrity-framework.md` — データディクショナリ（識別/会計メタ/株価/配当/財務PL・BS・CF・資本コスト）、ソース階層、照合、カバレッジ状態、claim単位グレード、期間充足、品質ゲート。入手難フィールド（investment_securities/beta/cost_of_debt）を低カバレッジ要因として特定

#### ⚠️ D2 第三者レビューで検出した偏り → 是正（2026-06-14）
back_findexの課題を気にするあまり「正確だが投稿に役立たない倉庫」に偏っていないかを点検し、4点是正:
1. **目的からの逆算が弱かった** — データ辞書が旧18指標から逆算されていた（最大のback_findex残留）。§0に原則2「投稿フック→必要データ→定義」を追加。`used_by`は参考であって前提でないと明記
2. **総合グレードが投稿を絞りすぎ** — 1銘柄1グレードでcore欠損=投稿対象外だと「配当だけ完璧な銘柄」の真実すら出せない。§6を**claim（主張）単位グレード**に作り替え（識別グレード§6.1＋claim別§6.2）
3. **完璧主義リスク** — §6.5「投稿開始の最小データ集合(MVP)」を新設（柱1完成待ちで投稿ゼロを回避）。§5カバレッジは初期はmaterializeせず集計クエリで導出
4. **ソース階層が実証前に断定** — §3を「仮説」に格下げ。EDINET一本足リスク明記。確定はD2.5へ
#### D2.5 取得可能性スタディ 実測完了（2026-06-14）
2段階方式で実施。成果物 `docs/design/02_5-feasibility-findings.md`（HTML: feasibility-findings.html）。
- **第1段（ライブプローブ）**: J-Quants v2 `/fins/summary` は現在財務を1コールで潤沢に返すが**約2年窓**（長期時系列はライブ不可）。`/listed/info`・`/fins/dividend`は現契約403。EDINET XBRLで投資有価証券・有利子負債・支払利息・利益剰余金を実取得＝**入手難フィールドは入手可能**。会計基準でラベルが変わる（IFRS接尾辞等）ことを実証。EDINETコードリストで証券→EDINETコード3,842件＋会計メタ(決算日・連結)取得可
- **第2段（旧DB集計・read-only）**: edinet_code/listing_date/capex が0%、財務BSは99%超。**重要訂正: betaは95%あり入手難でない。FCF低カバレッジの真因はcapex 0%とinvestment_securities不在**。配当はFY1989〜・3,210銘柄・打ち切り27.7%(1,039銘柄)・下限band(2000-2002)1,365銘柄。確定ストリーク約2,700銘柄=MVP母数潤沢
- D2を訂正（§2.7 betaの位置づけ、capex追加）。検証は`.scratch/`の使い捨てプローブ（gitignore）で実施・本番コード未着手
#### D2.6 取得限界の整理と評価軸への影響（2026-06-14）
成果物 `docs/design/02_6-data-limits-and-impact.md`。旧PJ最大の過ち（取れないデータに気づかず誤値を評価・投稿＝花王26 vs 36）を設計で根絶するための土台。
- **取得限界を4クラスに整理**: A完全取得可（現在値）/ B時系列下限あり（配当1989・株価2000・財務2008）/ C field欠落＝修正可能（listing_date・edinet_code・capex・investment_securities・深い株価）/ D構造的に取得不能（pre-2000株価/PER/PBR・backfill外の真の連続年数）
- **評価軸への影響を実測**（computed_metrics 3,746・真NULLと正当0を分離）。破綻4タイプ:
  - ①field欠落で機能不全（修正可）: FCF配当カバレッジ 真NULL57%（capex 0%が主因）、ROIC-WACC24%、ネットキャッシュPER12%（investment_sec）
  - ②履歴長不足（一部構造的）: 10年増配CAGR 35.6%、EPS成長5y 31.2%（若い銘柄は原理的に不能）
  - ③**打ち切りで静かに誤る（最危険）**: 連続年数系。streak_is_censored 27.7%（1,039銘柄）がNULLでないのに過小＝品質フィルタをすり抜ける。N+表示が生命線
  - ④影響軽微（現在値のみ）: 自己資本比率99.5%・ROE95%・営業益率99.3%・売上CAGR97%・配当性向99.8%
- **構造的洞察**: findex核心の配当継続性（重み6.0＝全体の約1/3）が最も取得困難な深い配当履歴に乗る。増配株分析というアイデンティティ自体が最も不確かなデータ領域に成立
- **価格2000・財務2008の下限は「現在スコア」にはほぼ効かない**（現在値指標が大半）。実害はバックテストと長期チャート投稿(D5)。現在スコアの実害主因は①capex欠落と③打ち切り
#### D2.7 結果補正レイヤ（公表値オーバーライドの一般化・2026-06-14）
成果物 `docs/design/02_7-result-override-layer.md`。ユーザー問い「pre-2000のマスターは無理でも、"結果"（連続増配30年）だけ公表集計から補填できないか」への設計回答。
- **結論: できる。ただし配当ストリーク系に限る**。株価/PER/PBRのpre-2000は"結果"の公表が無く点列なので補正不能
- 2種のバックフィルを区別: ①マスター補填(raw, haitoukin年間配当) ②結果補正(override, ZAi集計の連続年数)。後者は`streak_overrides`12件・golden20件で先行実装済み→汎用`result_overrides`(field/value/as_of/source/definition_note/confidence)に拡張
- ポリシー: 信頼ソース限定/昇格のみ(override≥機械計算)/採用時is_censored解除(当該指標のみ)/as_ofで経年補正/2ソースでverified
- **最大の地雷=定義差**（小林製薬「上場前から起算」で公表26年）。出典明示・definition_note・機械値併記で管理。投稿では「ZAi集計で連続増配28年」と出典付き断定回避＝柱3の武器にもなる
- 効果は投稿母数の頭(有名増配株)を確定値化＝柱3に直接効く。裾はN+で正直に
#### D3 データモデル改訂（2026-06-14）
成果物 `docs/design/data-model.md`（全面改訂）。本書がモデルの正本（schema.sqlは実装時に再生成）。D2.5〜D2.7の実測を反映:
- **来歴メタを全取得テーブル共通規約に**（source/confidence/as_of/collected_at）。カバレッジは集計クエリで導出（materializeしない）
- **streak_overrides → 汎用 result_overrides**（code/field/value/as_of/source/definition_note/confidence）。フィールド非依存に一般化（D2.7）
- **stocks に会計メタ追加**（fiscal_period_end_month/consolidated/accounting_standard）。edinet_codeはEDINETコードリストで即埋まる（旧0%）
- **financial_snapshots のソース分担明記**: J-Quants fins/summary（現在〜2年・潤沢）＋ EDINET XBRL（深いBS・入手難）。capex(C・edinet)・investment_securities(C・edinet)・interest_expense(cost_of_debt)を追加。**betaは導出（旧95%・入手難でないと訂正）**
- **price_history を2000年遡及**＋ソース分担（yfinance主・J-Quants補完）。pre-2000は構造的不能を明示
- **computed_metrics に claim別グレード**（grade_dividend/valuation/health/capital＋identity_ok）と由来フラグ（machine/override/censored）
- 各フィールドにクラス注記（A完全/C修正可/B・D構造的）
#### D4 指標システム仕様（2026-06-14）
成果物 `docs/design/04-indicator-system.md`。
- **Nullポリシー再設計（現「None→0」アンチパターン撤廃）**: 値の不在を5状態に分解 `ok/zero_legit(正当な0)/missing(欠損・修正可)/insufficient(期間不足・構造的)/censored(打切)`。derive層が(値,status)を出しスコアラはstatusを見て採点。**missing/insufficient/censoredは分子・分母とも除外**（持ってないデータで罰しない）、zero_legitは0点で分母に残す。実測根拠=データ11年未満1,199銘柄は10年CAGR100%不能=insufficientで減点は誤り
- **薄いデータinflation防止**: 分母除外だけだと2指標で満点化→グレードで「何を測れたか」を併示。投稿は score×grade で判断
- **合成順序データ契約**: machine→override(昇格のみ・採用時censored解除・as_of経年補正)→censored(N+)→machine。CAGRはoverride対象外
- **指標セット確定**: v3の16定義(標準14＋大型/金融代替2)。「18」はv3前(dividend_growth_5y_cagr/debt_to_equity含む旧版)。数は版管理事項で固定しない。capex回復後に#6FCF・#12ROIC(beta有)を再評価し次rule_versionへ
- **claim別グレード閾値**: dividend(#1-4)/valuation(#5,13,14)/health(#9-11)/capital(#6,12)をstatusからA〜D判定。censored含むclaimはA不可
#### D4.5 指標較正・v4確定（2026-06-14）
成果物 `docs/design/04_5-indicator-calibration.md`。D4で検出した指標設計の歪みを実データで較正。**全項目ユーザー承認でv4確定**:
- ①**10年CAGR廃止→YoC(取得利回り5年)新設(weight1.2)**＋**増配の質ゲート=掛け算減点**(EPS牽引sound×1.0/性向拡大payout_driven×0.5/一過性cyclical×0.3)。分解式DPS倍率=EPS倍率×配当性向変化で一過性株(イクヨ/日本製鉄)を弾く。株価2000遡及までdividend_multiple_5yを代理
- ②**DOE新設(weight0.8)**=ROE×配当性向。利益変動に強い持続性シグナル
- ③**自己資本比率 満点80%→70%**(実測:中央値55%・80%超は10%のみ)、**ROE 20%→15%**(20%は上位10%)。両満点は0.4%＝数学的綱引きを緩和
- ④**営業利益率を業種相対スコア化**(絶対20%は卸売3.3%〜証券19.8%の業種差で不公平・絶対フロア併用)。ROE相対化は効果見て判断
- ⑤予想配当性向/利回りに実績フォールバック＋confidence（Nullポリシーと接続）
- v4指標数: 標準15(CAGR-1・YoC+1・DOE+1)＋代替2。数は固定しない
- 較正の根拠データは全て旧DB実測。実装フェーズでrules.yaml更新（null_policy:status_based・YoC質ゲート・DOE・閾値・業種相対）後に再スコア
#### D7 ワークフロー改訂（2026-06-15）
成果物 `docs/design/data-workflow.md`（全面改訂）。D2.5〜D4.5の確定をワークフローに反映:
- **ソース分担を明記**: JPX(マスター)/EDINETコードリスト(edinet_code・会計メタ・月次)/kabutan(上場日)/J-Quants(直近株価・現在〜2年財務)/yfinance(株価2000遡及)/EDINET有報XBRL(深いBS・capex・会計基準別パース・提出日日次スキャン)/haitoukin(配当backfill)/result_overrides(公表結果)。beta=price×TOPIX回帰で自前算出
- **導出はstatus付き**(ok/zero_legit/missing/insufficient/censored)、合成順序(機械→override昇格→N+)、YoC＋増配の質係数(×1.0/0.5/0.3)、DOE
- **採点はv4 status-based**(missing/insufficient/censoredは動的分母から除外、zero_legitは0点で残す、営業益率は業種相対、予想欠損は実績フォールバック)
- **移行更新**: streak_overrides→result_overridesに変換、price_historyは移行せず2000年まで再取得(旧2024-06〜のみ)、financial_snapshotsはJ-Quants＋EDINETで再取得(旧raw_financialsは捨てる)
- **整合性チェック**にoverride vs machine乖離・status分布異常・残存N+数を追加(D6に接続)
#### D6 多フィールド検証戦略（2026-06-15）— 設計フェーズ完結
成果物 `docs/design/06-verification-strategy.md`。検証を配当ストリーク中心から全フィールド・全statusに拡張:
- **テストピラミッド3層**: L1単体テスト(streaks/yoc/status/採点式・CI毎・API不要) / L2コホート検証(約38社・各変更時・golden突合) / L3全銘柄サニティ(半年次・分布監視)
- **golden拡張**: 既存golden_streaks(連続増配20社)に加え golden_financials新設(EDINET/IR一次情報の財務正解値・会計基準IFRS/JGAAP/US-GAAPを散らしパース辞書を検証) ＋ golden_valuation(任意)
- **コホート28→38社**: 財務/会計基準/status系を追加(accounting_ifrs/usgaap/jgaap, financial_sector=銀行保険のswap検証, young_ipo=insufficient検証, loss=zero_legit検証, low_margin=業種相対検証, capex_heavy, high_invest_securities)
- **照合レポート**: ①override vs machine乖離(定義差検出) ②J-Quants vs EDINETクロスチェック(10%超でreview) ③machine vs golden
- **status分布監視**: missing急増(フェッチ障害)/censored上昇/review上昇/残存N+を半年次に監視しアラート
- **投稿自動停止条件を確定仕様化**: golden全green＋claim grade≥B＋missing/insufficient指標を文面に含まない＋censoredは必ずN+/override出典付き＋status異常なし＋二重投稿防止。最優先不変条件=「確定値に見える誤った数字を出さない」(花王26vs36再発防止)
- `findex verify` CLI新設(L1/L2/L3を束ねる・実装フェーズ)
- **設計ロードマップ完了**: ~~D1〜D4.5, D7, D6~~ ＝ **D5除く全設計完結**。次=**実装フェーズの方針決め**(移行→fetch→derive→score→verify・コホート38社)。D5 X発信は実装が動いてから
- **次の一歩: D3 データモデル改訂（D2.5の実測gapを反映）**。実装は引き続き凍結
- gitコミット方針: **findex配下だけ**（無関係な親リポの変更は触らない）。D1-D2を `1bbe7b1` でコミット済み
#### 設計レビューと是正＋D8バックテスト基盤（2026-06-15）— 実装前の品質点検
成果物 `docs/design/design-review.md`（是正の索引）＋ `docs/design/08-backtest-framework.md`（新設）。設計完結後、フラット第三者視点で全設計を点検し7論点を是正:
- **総評**: データ基盤(柱1)の厳密さは高いが、**モデル妥当性(柱2)とプロダクト/読者(柱3)が手薄**。重心が入力の正確性に偏り、定款が警戒した完璧主義が投資配分に出ていた
- **#1(最重要) モデル無検証**: 重みは旧PJ手づけで予測力未実証＝「確証無きモデル」。ユーザー判断=**本格バックテスト基盤構築**→**D8新設**(PIT時点正確・生存バイアス排除・前方アウトカム=減配回避/増配実現/トータルリターン・指標別IC・グレード較正・ウォークフォワードで重みv5較正・解釈可能性優先)
- **#2 読者/差別化未設計**: D5に読者像＋1行テーゼ「増配率に騙されない、質で選ぶ増配株」(切り口①)を追加
- **#3 yfinance株価が背骨で検証手段なし**: D6に株価検証(複数ソース突合・分割イベント独立検証・外れ値・信頼度上限)追加
- **#4 EDINETパースが最大工数リスク**: ユーザー判断=削らずフル維持→**リスクをゲートで潰す**(早期スパイク・パース成功率ゲート・基準別辞書を独立検証)
- **#5 総合スコア比較可能性**: claim内ランキングを主・total_scoreは足切り付き参考値(D4)・重み根拠はD8
- **#6 X自動化が最脆**: ユーザー判断=**Xメイン＋投稿画像をローカルHTML生成(自前サイト兼用)**→HTML生成層を一級化(D5/D7)・手動承認フォールバック・コンプラ明文化(売買推奨しない・免責)
- **#7 旧DB単一依存**: 移行時にyfinance配当1999+で能動洗浄・相互照合(D6/D7)
- **#8 ユニバース曖昧**: charter/D3で普通株のみ・delisting保持(生存バイアス対策)を定義
- **#9 整合性**: D3を単一正本化(themes/post_queue/post_log/backtestテーブル畳み込み)・運用設計を実装計画へ
- 改訂: charter(ユニバース・モデル検証原則・ロードマップR/D8)・D4(比較可能性)・D4.5(v5較正)・D5(読者/出力/コンプラ)・D6(株価検証/旧DB照合/EDINETゲート)・D3(themes/post_queue/backtest/ユニバース)・D7(backtest工程/移行照合/HTML生成)・実装計画(EDINETスパイク/Phase5.5 backtest/Phase6 HTML生成/運用設計)
- **設計フェーズ＝D1〜D8完結＋レビュー是正済**。実装は引き続き凍結・GO待ち

#### D5 X発信戦略（2026-06-15）— 設計ロードマップ全完結
成果物 `docs/design/05-x-posting-strategy.md`。優先度低として後回ししていたD5を設計:
- **前提＝バッジ無しアカウント**: 140字制限・API投稿不可・画像は文字数外・スレッドは手動連結。→ Playwright(セッション再利用・既存x_poster.py流用)
- **140字制約の突破口＝画像主役**: 「本文140字＝フック」「画像＝データ(ランキング表/チャート)」に役割分担。本文に数字を詰め込まない。フォーマット3類型(A単発/B画像主役=主力/Cスレッド)
- **投稿の定型化**: 投稿=テンプレート×データクエリ×品質ゲート。フック/claim/根拠/締め/固定フッタに分解。本文の数字は必ずDB由来=手打ちしない(捏造防止)
- **テーマ体系=切り口カタログ駆動**: 目標逆算シミュレーション(看板・ユーザー例「月3万つみたて→月5万配当」)/YoC実績/増配の質/連続増配ランキング/配当性向余力・DOE/割安×増配/高配当。1テーマ=1themes/*.yaml
- **看板テーマ詳細**: 目標逆算シミュレーション。順算/逆算、積立＋配当再投資＋YoC上昇。**想定増配率は捏造せず切り口①で実証した本物の増配株のEPS牽引実績レンジから採る**＋保守/標準/強気3シナリオ＋実在銘柄併記＋免責必須
- **品質ゲート連動(定款の鉄則の実装)**: status=okのclaimのみ・N+表示徹底・claim別グレード整合・出典/as_of必須・D6照合異常で自動停止・免責フッタ。不変条件=「自信ありげな誤った数字を絶対に出さない」
- **データモデル追記提案**: themes/post_queue/post_log(post_queue.claimsで事後監査可能性を担保)
- **段階導入(Phase6)**: MVP(連続増配ランキング・手動承認)→看板(目標逆算)→自動化(ゲート緑後cron)→学習(post_log効果測定)
- **設計フェーズ完全完結（D1〜D7・D5すべて）**。残るは実装着手の判断（ユーザーGO待ち・実装凍結継続）
