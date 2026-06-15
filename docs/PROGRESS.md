# findex 進捗ダッシュボード

プロジェクト全体の現在地・残作業・計画を一望するページ。**設計が動くたびに更新する**（正本の状態は各設計書、本ページはその要約）。

**最終更新**: 2026-06-15 / **現在フェーズ**: **実装フェーズ進行中（導出層Phase3-a/3-b/3-c完了）**/ **次の一歩**: Phase 3-d 価格由来指標（PER/PBR/配当利回り/時価総額/ネットキャッシュ）。3-cで財務由来11指標＋5状態statusを実装・コホート検証済

> 2026-06-15にユーザーGOで**実装凍結を解除**。Phase 0（スキーマ）・Phase 1（マスター）・Phase 2（取得層：EDINET会計基準別辞書／J-Quants財務／株価2000遡及／配当）が完了。各サブで**検証コホート35社を実データで検証してから次へ**進める方式。詳細は [プロジェクトログ](project-log.html) 冒頭。

---

## 1. ひとことサマリ

findex v2 は **ゼロから設計し直し中**。旧実装（`back_findex`）はデータ品質が破綻していたため切り離した。
いまは **設計フェーズ完結・実装凍結**。定款（全銘柄・全フィールドのデータ完全性を土台に、進化する独自指標で多角分析し、Xユーザーの興味を引く切り口で投稿し続ける）に沿って、D1→D8 の設計成果物を固め、フラット第三者レビューで是正済み。次は実装着手の判断（GO待ち）。

- **完了（設計フェーズ）**: D1〜D2.7、D3 データモデル、D4 指標システム、D4.5 較正v4、D7 ワークフロー、D6 多フィールド検証、D5 X発信戦略、**第三者レビュー是正**、**D8 バックテスト基盤（モデル検証）** ＝ **全設計が完結＋レビュー反映済**
- **レビュー是正（2026-06-15）**: フラット第三者レビューで7論点を是正。最大の盲点=「入力は厳密だがモデル無検証」→**D8バックテスト基盤**新設。他=読者/差別化(D5)・yfinance株価検証(D6)・旧DB能動洗浄(D6/D7)・EDINETリスクゲート(D6/計画)・総合スコア比較可能性(D4)・出力チャネル(Xメイン＋HTML生成・D5/D7)・ユニバース定義(charter/D3)
- **次**: **実装フェーズの方針決め**。順序＝移行(legacy→v2・能動洗浄)→fetch(EDINET早期スパイク含む)→derive→score(v4)→**backtest(モデル検証→v5)**→verify→出力(HTML生成＋X)。コホート38社で回す。GO待ち
- **凍結解除のタイミング**: 設計完結により、次は実装着手の判断。既存雛形(schema.sql/streaks.py/fetch基盤)は設計（特にdata-model D3・v4）と突合してから流用

### D2.5 実測の要点（2026-06-14）
- **J-Quants v2 は約2年窓**（現契約）。現在スナップショット財務は`/fins/summary`1コールで潤沢だが、長期時系列（配当ストリーク等）はライブ不可 → 旧DB(FY1989〜)＋バックフィルが土台
- **入手難フィールドは入手可能**。EDINET XBRLで投資有価証券・有利子負債・支払利息・利益剰余金を実取得。低カバレッジの真因は「データ欠如」でなく「会計基準をまたぐパース未対応」
- **重要訂正**: beta は旧DBで95%あり入手難ではない。FCF低カバレッジの真因は **capex 0%**（未取得）と investment_securities 不在
- **gap実数**: edinet_code 0%・listing_date 0%・capex 0% が要対応。財務BSの大半は99%超ある
- **MVP潤沢**: 確定ストリーク約2,700銘柄。配当系の投稿母数は設計確定後すぐ確保できる
- **時系列の下限（重要）**: 2000年以前で保持できるのは**配当のみ**。株価はyfinanceでも2000-01-04が下限、財務(EDINET)は2008年〜。**2000年以前の株価・PER・PBRは取得不能**（pre-2000は価格・バリュエーション系claimを出さない＝捏造しない）。旧DBの株価は2024-06〜しか無いが2000年まで再取得で回復可

---

## 2. 設計ロードマップ（D1〜D8）

| ID | 設計成果物 | 状態 | 成果物リンク |
|---|---|:---:|---|
| **D1** | ノーススター（定款・データ完全性・全体像） | ✅ 完了 | [charter](charter.html) |
| **D2** | データ完全性フレームワーク（データ辞書・claim単位グレード・期間充足・品質ゲート） | ✅ 改訂済 | [data-integrity-framework](data-integrity-framework.html) |
| **D2.5** | 取得可能性スタディ（実データでソース確定・gap実測・MVP母数） | ✅ 実測完了 | [feasibility-findings](feasibility-findings.html) |
| **D2.6** | 取得限界の整理と評価軸への影響調査（実測） | ✅ 完了 | [data-limits-and-impact](data-limits-and-impact.html) |
| **D2.7** | 結果補正レイヤ（公表値オーバーライドの一般化） | ✅ 完了 | [result-override-layer](result-override-layer.html) |
| **D3** | データモデル改訂（来歴メタ・result_overrides汎用化・C群フィールド・claim別グレード・株価2000遡及） | ✅ 完了 | [data-model](data-model.html) |
| **D4** | 指標システム仕様（Nullポリシー再設計・合成順序・16確定・claim別グレード閾値） | ✅ 完了 | [indicator-system](indicator-system.html) |
| **D4.5** | 指標較正 v4（YoC置換・DOE新設・閾値較正・業種相対・予想フォールバック） | ✅ v4確定 | [indicator-calibration](indicator-calibration.html) |
| **D6** | 多フィールド検証戦略（テストピラミッド・golden拡張・照合・status監視・自動停止） | ✅ 完了 | [verification-strategy](verification-strategy.html) |
| **D7** | ワークフロー改訂（ソース分担・status付き導出・v4採点・移行・整合性） | ✅ 完了 | [data-workflow](data-workflow.html) |
| **D5** | X発信戦略（バッジ無し前提・140字突破・テーマ体系・品質連動・学習） | ✅ 完了 | [x-posting-strategy](x-posting-strategy.html) |
| **R** | 設計レビューと是正（フラット第三者・7論点） | ✅ 是正済 | [design-review](design-review.html) |
| **D8** | バックテスト基盤（モデル検証・PIT・生存バイアス排除・IC・グレード較正・v5較正） | ✅ 完了 | [backtest-framework](backtest-framework.html) |

凡例: ✅完了 / ⏭️次に着手 / ⬜未着手

---

## 3. 定款と3本柱（達成度）

> あらゆる上場株式について、**必要なデータを正確に保持し、足りない部分を常に把握できる**ことを土台に、
> **独自指標（進化し続ける指標群）**で多角的に分析し、Xユーザーの興味を引く切り口で投稿し続ける。

| 柱 | 内容 | 設計状況 | 実装状況 |
|---|---|---|---|
| 柱1 | 正確なデータ基盤（全銘柄・必要データ＋充足把握） | 🟩 D2枠組み＋D2.5実測でソース確定。D3でモデル化済 | 🟨 **取得層実装済（Phase0-2）**。マスター3,734社・財務(J-Quants+EDINET)・株価2000遡及・配当。コホート35社で検証済。導出/評価/出力はこれから |
| 柱2 | 進化する独自指標による多角評価 | 🟩 D4仕様化＋D4.5較正v4＋**D8でモデル検証(重みv5較正)**まで設計済 | 🟥 未着手（Phase3導出層＝次） |
| 柱3 | Xユーザーの興味を引く切り口での発信 | 🟩 D5で戦略化済（140字突破=画像主役・テーマ体系・品質ゲート連動・出力=Xメイン＋HTML生成） | 🟥 未着手（Playwright方式・骨格あり・Phase6） |

土台原則: **正確でないデータは「無価値」でなく「有害」。確証を持てない数字は分析にも投稿にも一切流さない。**

---

## 4. 重要な意思決定の履歴

### 設計完結後の第三者レビュー（2026-06-15）
全設計を点検し7論点を是正（[design-review](design-review.html)）。ユーザー判断3点 = **MVPはフル設計維持（EDINET削らない）／出力はXメイン＋画像ローカルHTML生成（自前サイト兼用）／モデル検証は本格バックテスト構築**。最大の是正＝モデル無検証→**D8バックテスト基盤**新設。

### D2 第三者レビュー → 目的志向への是正（2026-06-14）
「back_findexの課題を気にするあまり、正確だが投稿に役立たない倉庫に偏っていないか」を点検し、4点是正:

| # | 検出した偏り | 是正 |
|---|---|---|
| 1 | データ辞書が**旧18指標から逆算**（最大のback_findex残留） | §0原則2「投稿フック→必要データ→定義」で逆算。`used_by`は参考であって前提でないと明記 |
| 2 | **総合グレードが投稿を絞りすぎ**（core欠損で全面除外） | **claim単位グレード**へ（配当系A・財務系Dなど銘柄内で別々。配当だけ完璧な銘柄の真実も投稿可） |
| 3 | **完璧主義の罠**（柱1完成待ちで投稿ゼロ） | §6.5「投稿開始の最小データ集合(MVP)」新設。カバレッジは初期は集計クエリで導出 |
| 4 | **ソース階層を実証前に断定** | §3を「仮説」に格下げ。EDINET一本足リスク明記。確定はD2.5 |

詳細は [プロジェクトログ](project-log.html)。

---

## 5. 実装フェーズの段取り（コホート35社で各フェーズ検証）

詳細は [実装フェーズ計画](implementation-plan.html)。各フェーズ末は**コホート35社を実データ検証**で区切る。

| Phase | 内容 | ゲート | 状態 |
|---|---|---|:---:|
| 0 | スキーマ再生成（D3・18テーブル） | 全Dのテーブル定義と一致 | ✅ `b060f3e` |
| 1 | マスター＋移行（普通株3,734・edinet_code/会計メタ・listing_date・haitoukin/override移行） | コホートのstocks完備 | ✅ `9ddc7b9` |
| 2 | 取得層（EDINET基準別辞書・株価2000遡及＋J-Quants突合・財務J-Quants＋EDINET・配当＋能動洗浄） | status妥当・EDINETパース成功率が閾値以上 | ✅ `df10526`〜`3e320f2` |
| 3 | 導出（status付き・YoC質ゲート・DOE・打ち切り合成・**seam穴橋渡し**） | golden_streaks緑・status分布妥当 | 🟨 3-a/3-b/3-c完了・3-d次 |
| 4 | 採点（v4 status-based・動的分母・業種相対） | スコア説明可能 | ⬜ |
| backtest | **モデル検証**（PIT・生存バイアス排除・前方アウトカム・重みv5較正） | スコアが前方アウトカムと相関 | ⬜ |
| 5 | 検証（findex verify・全銘柄スキャン1回） | verify緑・全銘柄ランキング生成 | ⬜ |
| 6 | 出力（HTML生成＋X発信・claim内ランキング主） | サイト生成＋品質ゲート通過の投稿 | ⬜ |

**移行で救った再現困難データ（実施済）**: `dividend_annual`(haitoukin 622) と `result_overrides`(旧streak_overrides 12)。price/financial/eventsは再取得。配当は yfinance events で再構築＋haitoukin接合を能動洗浄。

### 取得層(Phase2)の実データ確認サマリ
- **EDINET会計基準別辞書**: AccountingStandardsDEIで判別。IFRS=`jpigp_cor:*IFRS`/JGAAP=`jppfs_cor:*`、連結=ctxサフィックス無し。IFRSは投資有価証券/流動資産が構造的にinsufficient、**US GAAP連結は構造化XBRL不在→grade_capitalフォールバック**
- **株価**: yfinance`Close`=分割調整・配当未調整（YoCに正）。J-Quants突合で最大乖離**0.000%**
- **配当**: events(2000+)が信頼基盤。haitoukinは社により分割調整状態が不統一→接合で単位統一＋混線はreviewフラグ

### 導出層(Phase3)の実データ確認サマリ
- **3-a ストリーク**: 機械計算→result_override（昇格のみ）→N+ の合成順序。golden 18/18一致。決算変更/分割の変則年は機械が過小評価→公表値で昇格
- **3-b 配当由来指標**: YoC・DPS倍率・CAGR・信頼性・減配回数。減配検出は「前年割れ かつ 2年前も割れ」で頑健化（花王FY2012スパイク復帰を誤検出しない）
- **3-c前バックフィル**: 増配の質はEPS5年比較が前提。J-Quants約2年窓では縮退→**有報「主要な経営指標等の推移」（最新1枚にPrior4..Current同梱）**で5年史を取得。J-Quantsが直近2年・EDINET summaryが古い3年をCOALESCE補完。花王5年EPS=230.59/183.28/94.37/231.94/260.30で実証。US GAAPは5年史も構造化されず→insufficientのまま（捏造しない）
- **3-c 財務由来指標（11指標の生値＋5状態status）**: ROE/自己資本比率/D/E/営業益率/配当性向/DOE/EPS成長/売上CAGR/FCFカバ/利剰配当倍率/ROIC−WACC。点指標は最新**J-Quants確報**をアンカー（5年史の薄いorphan行を掴まない）、深いBS（有利子負債/利益剰余金/capex）は各フィールド最新非NULLを独立取得、成長は5年史CAGR。コホート35社status分布: equity_ratio/roe=35ok、営業益率31ok（残=銀行/持株/IFRS営業益欠落・正当）、EPS成長28ok・売上CAGR30ok、FCFカバ22ok。**確証主義の実証**: ①**IFRS有利子負債は企業独自拡張タグ**（NTT=ShortTermDebt/ソニー=Borrowings系）で完全抽出不可→標準BondsAndBorrowingsが在る社のみok・無ければ**insufficient**（NTT/SBGをD/E=0と偽装しない）。zero_legit(無借金)はJGAAP（標準タクソノミ信頼可）限定。②売上/capexの要素IDが業種で分裂（営業収益・固定資産取得・有形無形合算）→標準タグのみフォールバック鎖化（イオン/日産/高島屋回復、ソニー独自拡張はinsufficient）。③ROIC−WACCは市場値/beta（価格層）依存→現状insufficient。④**EDINET日次スキャンは一過性失敗でデータを黙って取りこぼす**（find_latest_docが例外握り潰し）＝Phase2 robustness課題（全銘柄runでは再取得/検証が必須）

---

## 6. 既知のリスク・宿題

設計凍結中なので「未解決の設計課題」と「設計で解決済み・実装待ち」を区別する。

### 6.1 実装で解決済み（✅・Phase0-2で実データ確認）
| 項目 | 結果 |
|---|---|
| `edinet_code`・会計メタ投入（旧0%） | EDINETコードリストzipで3,842件・コホート100%（Phase1） |
| `capex`・`investment_securities`（旧0%/不在） | EDINET有報XBRL・JGAAP/IFRS取得（コホートcapex 21/35）。IFRSは構造的にinsufficient・US連結は取得不能でgrade_capitalフォールバック |
| 株価2000遡及（旧は2024-06〜のみ） | yfinance`Close`(分割調整)で回復・J-Quants突合0.000%（Phase2-d） |
| 旧DBからの移行 | haitoukin配当622・override12を移行（Phase1）。events再取得＋接合の能動洗浄（Phase2-e） |
| `listing_date`（旧0%・打ち切り判定の鍵） | **設計のkabutanはJS化で静的取得不可** → yfinance firstTradeDate主（床バンドはNULL）。kabutan補完(Playwright)は `listing_date IS NULL` が対象＝後続 |

### 6.2 未解決リスク・宿題（🟨＝要注視 / 🟥＝実装バグ）
| 項目 | 状態 |
|---|---|
| **モデル（重み）が無検証** | 🟨 最大の盲点。重みは旧PJ手づけ→**D8バックテストで前方アウトカム較正→v5**（Phase5.5・design-review #1） |
| **配当接合の単年seam穴** | 🟨 haitoukin/events接合で一部銘柄に単年欠損（リンナイFY2001等）→Phase3ストリークで橋渡し |
| **配当のpre-2000 review銘柄** | 🟨 合併等で接合が不整合（ユニチャーム/イオン等）はconfidence=review→左打ち切り/override/N+で扱う |
| **`delisting_date` 収集** | 🟨 コホートは全現役でNULL（正）。上場廃止銘柄のbackfillは未（生存バイアス排除＝D8前提・design-review #8） |
| **listing_date NULL床のkabutan補完** | 🟨 yfinance床に張り付く古参は真値不明のまま（Playwright補完が後続） |
| **EDINET/yfinanceの全銘柄スキャン実時間** | 🟨 EDINETは提出日日次スキャンで1社あたり重い。全3,734社は数時間規模→運用設計（実装計画§4） |
| **X自動化の脆さ/ToS** | 🟨 HTML生成兼用＋手動承認フォールバック（D5/Phase6・design-review #6） |
| `streaks.py` ギャップ中断の打ち切り未検知 | 🟥 既知の実装バグ・Phase3で修正 |

> **取得層で実証済みに格下げした旧リスク**: EDINET会計基準別パース（🟨→IFRS/JGAAP成立・US fallbackを実証）／yfinance株価検証（🟨→J-Quants突合0.000%）。

凡例: ✅実装で解決 / 🟨未解決リスク・要注視 / 🟥実装バグ

---

## 7. 分析切り口カタログ（柱2/柱3の蓄積）

有望と検証できた「切り口」を `docs/design/analysis-angles.md`（[analysis-angles](analysis-angles.html)）に蓄積する。
- **切り口①: YoC（取得利回り）× 増配持続性**（検証済2026-06-14）。YoC=量、DSS(増配持続性)=質の2軸で「本物の増配株 vs 一過性の罠」を判別。核心の分解式「DPS倍率=EPS倍率×配当性向変化」でブースト株（イクヨ66x/EPS0x、日本製鉄36x/EPS減）を弾く。DOE追加候補。D4.5で指標化・D5でテーマ化

---

## 8. レビューの入口

- **[設計レビューと是正](design-review.html)** = フラット第三者レビュー7論点と是正方針の索引（実装前の品質点検）
- **[実装フェーズ計画](implementation-plan.html)** = 設計→コードの橋渡し（Phase0〜Phase6・backtest含む・GO待ち）
- このダッシュボード（progress.html）= 全体の現在地
- [ノーススター（charter）](charter.html) = 正本。迷ったらここに戻る
- [D8 バックテスト基盤](backtest-framework.html) = モデル検証（最新の追加設計）
- [プロジェクトログ](project-log.html) = 意思決定の履歴（過ちと是正）
