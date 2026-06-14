# findex プロジェクトログ

セッションをまたいで文脈を失わないための公式記録。**新しい作業を始める前に必ず本書とノーススター（[00-charter-and-data-integrity.md](design/00-charter-and-data-integrity.md)）を読むこと。**
フェーズが終わるごとに追記する（上に新しいフェーズを積む）。

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
