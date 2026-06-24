# findex 進捗ダッシュボード

プロジェクト全体の現在地・残作業・計画を一望するページ。**設計が動くたびに更新する**（正本の状態は各設計書、本ページはその要約）。

**最終更新**: 2026-06-22 / **現在フェーズ**: **柱3（X発信）解凍＝GitHub Pages 投稿ハブ公開（LIVE）＋投稿層の継続較正＋予想配当利回り化** / **次の一歩**: 本番J-Quants環境での予想更新（FY2027反映）・分割データ欠落の追跡（柱1）・生存バイアス対応＝廃止株収集（データ制約）

> **★2026-06-22 配当利回りを「予想配当利回り（会社予想）」へ切替＝全銘柄公開**: ユーザー指摘（7463=11.0%等が実態と乖離）を起点に、特配込み実績÷株価のゴースト高利回りを根治。源泉=既取得 J-Quants `FDivAnn`/`NxFDivAnn`（新規負荷ゼロ）。`dividend_forecast`テーブル新設＋`_forecast_dps()`で予想優先。**予想DPSの分割補正漏れも修正**（3443川田 11.87%→3.96%等）。全3,734件反映（予想カバレッジ97.1%）。Yahoo664件突合で |乖離| 中央0.22pt/最大4.32pt（補正前 最大8.59pt）・2914JT=3.98%完全一致。pytest 122 / golden 18/18。正本: docs/PROJECT-LOG.md。
>
> **★2026-06-21〜22 柱3（X発信）解凍＝¥0 GitHub Pages 投稿ハブを公開（LIVE）**: 長く凍結していた柱3を解凍。X API無料枠廃止＋Web Intent画像添付不可の制約から「最後のタップだけ手動」の¥0方式を採用。**公開URL: https://motani-info.github.io/findex/**（全銘柄ユニバースの全テーマ）。findexリポを public 化し生成物のみ gh-pages 配信。再公開は `bash scripts/publish_hub.sh` 1コマンド。投稿層は doc10（テーマ層較正）→doc17（タラレバ＋EPS成長・武田型トラップ・配当併記・実文字140字）で継続較正。
>
> **★2026-06-17(夜) backtest メトリクス(D8 5.5-c)完了＝モデル検証パイプライン3段が全完了**: `metrics.py` 新規（spearman/三分位スプレッド/IC/grade_calib・純Python・単体テスト7件）＋ CLI `backtest --what metrics|all`。コホート生存者標本で**配線＋方向性を確認**（統計的有意性はフル銘柄＋廃止株収集後）。
> 所見: `consecutive_no_cut_years`×前方減配 IC=**−0.22**（配当安全性テーゼを実証）。一方 total_score×前方リターン=−0.21＝高スコア群が価格で劣後（ディフェンシブ妙味）＝**v5重み較正の客観材料**。grade_calibはPIT時点の財務欠落で全銘柄gradeB＝NULL(検証不能)を正直に可視化。pytest 84 passed。正本: docs/design/08-backtest-framework.md §8。
> triage副産物: **capex は取得済(3079銘柄)＝「capex 0%」は解消**。**delisting_date は無料データに廃止株なしでハードブロック**（生存バイアスは未解消の制約）。

> **★2026-06-17 doc 09「スケール露出データ品質の是正」完了**: 全3734洗替後の posts.html 目視FB（銘柄名欠落／配当利回り壊れ／ランキングに外れ値）を derive層の単一ゲートで根治。
> ① **A 名前**: `fetch_rows` の name を cohort35社→stocks全件に修正（欠落0件）。
> ② **B 鮮度ゲート**（`DIVIDEND_RECENCY_YEARS=3`）: 配当が最新株価年から3年超途絶→新status `stale`。廃配休配を現役利回りから排除（3070=25.8%/ok→stale）。
> ③ **C サニティゲート**: 全3710の実分布p99から較正した閾値（div_yield≤12%/\|roe\|≤100%/per≤200/pbr≤20/cagr5y≤65%）の範囲外を新status `suspect`。残存 ok>閾値=0件。
> ④ **テーマeligibility**: `MIN_N_SCORED=8` で薄データ除外（total_score上位がn_scored=1→≥11に是正）。
> 検収: golden 18/18 不整合0 死守・pytest 77 passed。stale/suspect は全レイヤ ホワイトリスト方式で自動「—」化（単一ゲート原則）。正本: docs/design/09-scale-data-quality-remediation.md。

> **★Part2 全データ洗替の進捗（2026-06-16夜・背景ジョブ運用）**
> ① listing --all ✅（3734・真値629/床NULL3105=設計通り） ② prices --all ✅（17.4M行・3736系列・1965-2026・N225済） ③ financials --all 🔄（EDINET深BS・逆順スキャンで巡航~7件/分） ④ dividends --all 🔄（yfinance ~27件/分） → ⑤derive --all → ⑥score --all → ⑦verify --all。重い取得は **nohup 背景ジョブ**（AIはポーリングしない・監視は `findex progress <name>`）。
> **★今回の2大是正（実害寸前を阻止）**:
> 1. **financials/dividends の resume が壊れていた（silent gap・コミット500fb40）**: 旧実装は両ソース全件取得後に末尾一括書込＝途中で落ちて resume すると取得済み銘柄がskipされ**行が永久に書かれず再取得もされない**（定款のsilent-drop禁止違反）。→ 1銘柄=取得→書込→**commitまでfetch_one内で完結**する結合フェッチャに再設計。base.run() が commit 後にのみ checkpoint＝**いつ落ちても resume が正しく続く（蓋閉じOK）**。
> 2. **EDINET探索の逆順スキャン化（3倍速・コミット19c2b4b）**: 有報は提出締切直前に集中するので窓を締切側から逆走査。1窓に有報1枚なので**返るdocIDは不変**（cohort10社で前方=逆順の docID 完全一致を実証）。ETA 17h→約6h。
> 監査の副産物: derive/score に `--all` 欠落を是正（`_resolve_target`一元化）、score の銘柄名を stocks マスター化。price_history はインデックス健全でO(n²)爆発なし。

> **★2026-06-16 戦略転換（ユーザー判断）**: 「このデータ量で本番化は無理。しっかり基盤を整えたうえで全データ洗替しよう。アウトプットはその後でOK」。→ 出力/X発信（Phase6）を凍結し、順序を反転して **基盤整備 → 全銘柄洗替** を正攻法で実施。基盤整備6課題のうち F1-F5 を完了（下記§5.5）。Part2（実際の3734洗替）は次セッションで実行。

> 2026-06-15にユーザーGOで**実装凍結を解除**。Phase 0（スキーマ）・Phase 1（マスター）・Phase 2（取得層：EDINET会計基準別辞書／J-Quants財務／株価2000遡及／配当）が完了。各サブで**検証コホート35社を実データで検証してから次へ**進める方式。詳細は [プロジェクトログ](project-log.html) 冒頭。

---

## 1. ひとことサマリ

findex v2 は **ゼロから設計し直し**、いまは **3本柱すべてが稼働中**。旧実装（`back_findex`）はデータ品質が破綻していたため切り離した。
設計（D1→D8）を固め第三者レビューで是正したのち実装凍結を解除し、**全3,734銘柄の洗替（柱1）→ 導出・採点v4・backtest配線（柱2）→ ¥0 GitHub Pages 投稿ハブ公開（柱3・LIVE）** まで到達。
以降は投稿層の継続較正（doc10/12/14/17・外部レビュー対応）とデータ品質の追い込み（予想配当利回り化・分割補正）が主戦場。残る大物は本番J-Quants環境での予想更新・全銘柄backtestによるv5重み較正・廃止株収集（生存バイアス）。

- **完了（設計フェーズ）**: D1〜D2.7、D3 データモデル、D4 指標システム、D4.5 較正v4、D7 ワークフロー、D6 多フィールド検証、D5 X発信戦略、**第三者レビュー是正**、**D8 バックテスト基盤（モデル検証）** ＝ **全設計が完結＋レビュー反映済**
- **レビュー是正（2026-06-15）**: フラット第三者レビューで7論点を是正。最大の盲点=「入力は厳密だがモデル無検証」→**D8バックテスト基盤**新設。他=読者/差別化(D5)・yfinance株価検証(D6)・旧DB能動洗浄(D6/D7)・EDINETリスクゲート(D6/計画)・総合スコア比較可能性(D4)・出力チャネル(Xメイン＋HTML生成・D5/D7)・ユニバース定義(charter/D3)
- **次**: **実装フェーズの方針決め**。順序＝移行(legacy→v2・能動洗浄)→fetch(EDINET早期スパイク含む)→derive→score(v4)→**backtest(モデル検証→v5)**→verify→出力(HTML生成＋X)。コホート38社で回す。GO待ち
- **凍結解除のタイミング**: 設計完結により、次は実装着手の判断。既存雛形(schema.sql/streaks.py/fetch基盤)は設計（特にdata-model D3・v4）と突合してから流用

### D2.5 実測の要点（2026-06-14）
- **J-Quants v2 は約2年窓**（現契約）。現在スナップショット財務は`/fins/summary`1コールで潤沢だが、長期時系列（配当ストリーク等）はライブ不可 → 旧DB(FY1989〜)＋バックフィルが土台
- **入手難フィールドは入手可能**。EDINET XBRLで投資有価証券・有利子負債・支払利息・利益剰余金を実取得。低カバレッジの真因は「データ欠如」でなく「会計基準をまたぐパース未対応」
- **重要訂正**: beta は旧DBで95%あり入手難ではない。FCF低カバレッジの真因は **capex 0%**（未取得）と investment_securities 不在
- **gap実数**: edinet_code 0%・listing_date 0%・capex 0% が要対応。財務BSの大半は99%超ある
  - ※ **2026-06-17 更新**: capex は全データ洗替で取得済（**3079銘柄非NULL**・fcf_coverage ok=2753）＝「capex 0%」は解消済み。listing_date も F4 で全件対応済。
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
| 柱1 | 正確なデータ基盤（全銘柄・必要データ＋充足把握） | 🟩 D2枠組み＋D2.5実測でソース確定。D3でモデル化済 | 🟩 **全3,734銘柄 洗替済**。マスター・財務(J-Quants+EDINET)・株価2000遡及・配当（実績＋**会社予想**）・分割補正（doc11）。残=分割データ欠落の追跡・生存バイアス(廃止株) |
| 柱2 | 進化する独自指標による多角評価 | 🟩 D4仕様化＋D4.5較正v4＋**D8でモデル検証(重みv5較正)**まで設計済 | 🟩 **導出・採点(v4)実装済**＋backtest(配線+方向性)＋テーマ層較正(doc10/12/14)。残=全銘柄backtestでv5重み較正 |
| 柱3 | Xユーザーの興味を引く切り口での発信 | 🟩 D5で戦略化済（140字突破=画像主役・テーマ体系・品質ゲート連動・出力=Xメイン＋HTML生成） | 🟩 **公開（LIVE）**: ¥0 GitHub Pages 投稿ハブ https://motani-info.github.io/findex/ 。全18テーマ・タラレバ試算・実文字140字・予想配当利回り。再公開=`publish_hub.sh` |

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
| 3 | 導出（status付き・YoC質ゲート・DOE・打ち切り合成・beta/ROIC・claim別グレード） | golden_streaks緑・status分布妥当 | ✅ `0d9f432`＋3-e |
| 4 | 採点（v4 status-based・動的分母・業種相対・YoC質ゲート・動的入れ替え） | スコア説明可能 | ✅ コホート採点 |
| backtest | **モデル検証**（PIT・生存バイアス排除・前方アウトカム・重みv5較正） | スコアが前方アウトカムと相関 | 🟩 5.5-a/b/c **全完了**（outcomes884・PITスコア442・metrics34）。下記§5.6 |
| 5 | 検証（findex verify・全銘柄スキャン1回） | verify緑・全銘柄ランキング生成 | 🟨 **verify実装完了(F5)**・全銘柄スキャンはPart2 |
| 6 | 出力（HTML生成＋X発信・claim内ランキング主） | サイト生成＋品質ゲート通過の投稿 | 🟩 **公開（LIVE）**: ¥0 GitHub Pages 投稿ハブ（全18テーマ・タラレバ試算・予想配当利回り）。`publish_hub.sh` で再公開。自動投稿は仕様制約で不採用＝最後のタップのみ手動 |

**移行で救った再現困難データ（実施済）**: `dividend_annual`(haitoukin 622) と `result_overrides`(旧streak_overrides 12)。price/financial/eventsは再取得。配当は yfinance events で再構築＋haitoukin接合を能動洗浄。

### 5.5 基盤整備（全銘柄洗替の前提・F1-F5完了 2026-06-16）
全銘柄スキャンの致命傷＝「黙ってデータを落とす」系を、コホートで顕在化する前に潰した。
- **F1 取得の完全性ゲート** (`base.py is_complete`): 「例外なし＝done」で空/部分データを黙ってチェックポイントに刻む欠陥を是正。Falseなら failed に回し done を刻まない＝resumeで再取得。コミット`c5a377c`
- **F2 EDINET robustness** (`edinet.py`): `find_latest_doc` が「真に書類無し(clean)」と「一過性失敗で見落とし」を弁別。`_scan_one_date` がリトライ、解消しなければ `EdinetScanError`（空と断定しない）。EdinetFetcherはバックオフ対象にし尽きれば再取得。コミット`c5a377c`
- **F3 streaks 歯抜け区別（E1是正）** (`streaks.py`): `_streak` が中断理由(gap/cut/start)を返し、データ欠落(gap)中断は censored（N年以上）に。**実データで FY2000-2001 の系統的 seam穴を可視化**（コホート censored 3→13・新規10は全て実在の歯抜け）。override(golden)は is_censored=False 維持＝**golden 18/18不変**。コミット`3c6deb0`
- **F4 listing 全銘柄対応** (`listing.py`/`cli.py`): `listing --all`（3734明示）＋ YahooListingFetcher の完全性ゲート（both-null=パース失敗疑い→再取得）。非コホート12社で実検証（日立1949/トヨタ1949/ファストリ1994等正値・failed0）。コミット`369d78b`
- **F5 findex verify（検収）** (`verify.py`): 洗替結果を読み取り専用で点検＝カバレッジ/golden整合/seam穴/review率/status分布。コホートで golden 18/18整合✓・FY2000接合穴9社・review6社を確認。コミット`ef912f5`
- **テスト**: 計76緑（基盤整備で+11: robustness5/streaks2/verify4）。

### ★Part2 全データ洗替（次セッションで実行）
F1-F5 で基盤が固まった。実行パイプライン（各段 checkpoint・resume・verify検収）:
```
master(3734) → listing --all(全Yahoo・数時間) → prices(2000遡及+N225)
  → financials(J-Quants+EDINET ★最重・F2で堅牢化) → dividends(+異常洗浄)
  → derive --what all → score → verify --all(検収・未充足は再fetch)
```
**残る正確性課題（洗替中に効く）**: E2 配当seam穴(FY2000接合)の上流是正＝F3が穴を残しても正直化するが、根治は接合修復。E3 pre-2000 review接合。動かない制約: A1生存バイアス(廃止株無料不可)・A2財務深度5年(財務系バックテスト不能)。

### 取得層(Phase2)の実データ確認サマリ
- **EDINET会計基準別辞書**: AccountingStandardsDEIで判別。IFRS=`jpigp_cor:*IFRS`/JGAAP=`jppfs_cor:*`、連結=ctxサフィックス無し。IFRSは投資有価証券/流動資産が構造的にinsufficient、**US GAAP連結は構造化XBRL不在→grade_capitalフォールバック**
- **株価**: yfinance`Close`=分割調整・配当未調整（YoCに正）。J-Quants突合で最大乖離**0.000%**
- **配当**: events(2000+)が信頼基盤。haitoukinは社により分割調整状態が不統一→接合で単位統一＋混線はreviewフラグ
- **listing_date 真値取得＋打ち切り精緻化（Step2・2000年問題の核）**: yfinanceの firstTradeDate は国内株で2000-2001床に張り付き古い銘柄の真の上場日を欠く（旧DB listing_date=8/3734・しかも床値）。**Yahoo!ファイナンス(JP)プロフィールが「上場年月日」を真値で持つ**（花王1949年5月＝年月のみも・設立年月日も補完）→これを真値ソースに採用（`fetch/listing.py YahooListingFetcher`・`listing --source yahoo`）。コホート35/35取得（JT1994/KDDI1993/ニトリ1989/メルカリ2018で実在と一致、サンエー2005床→2000-09訂正）。**打ち切り判定を精緻化**: 真の上場日が揃ったので「データ下限前に既に公開・配当した履歴の欠落」のみN+とする＝①上場<最古配当年 かつ ②上場<網羅開始年(2000)の両方が必要。**IPO世代(>=2000上場)はIPO→初配当の空白があっても全履歴保持＝非打ち切り**（電通総研2000上場/初配当2002をN+から実数12年/23年に解放）。古い実打ち切り（NTT1987/イオン1974/クレディセゾン1963）はN+維持。golden18/18不変。
- **配当の単年アーティファクト隔離（Step1・正確性の根因是正）**: yfinance events系列に2種のアーティファクト（①半期払いで単年だけ1回しか取れず年合計が半額＝沖縄セルラー2010 ②yfinance単年誤値＝神戸物産2009=0.156/サンエー2006/PPIH2003）が混じり、連続年数・CAGR・YoC・バックテスト正解ラベルを汚す。`flag_dividend_anomalies`が**払い回数の最頻値＋孤立性（翌年は最頻回数に復帰）**と**前年35%未満の急落**の2精密シグナルで検出し`confidence=review`に隔離（下流は自動除外）。**実減配（日産FY2022=5.0の値減配・危機の頻度低下）は弁別して残す**＝過剰隔離で実シグナルを消さない。golden 18/18は不変（花王36等の連続増配は正確性維持）。根因を取得層1箇所で是正したのでバックテスト側の暫定ガードは撤去。

### 導出層(Phase3)の実データ確認サマリ
- **3-a ストリーク**: 機械計算→result_override（昇格のみ）→N+ の合成順序。golden 18/18一致。決算変更/分割の変則年は機械が過小評価→公表値で昇格
- **3-b 配当由来指標**: YoC・DPS倍率・CAGR・信頼性・減配回数。減配検出は「前年割れ かつ 2年前も割れ」で頑健化（花王FY2012スパイク復帰を誤検出しない）
- **3-c前バックフィル**: 増配の質はEPS5年比較が前提。J-Quants約2年窓では縮退→**有報「主要な経営指標等の推移」（最新1枚にPrior4..Current同梱）**で5年史を取得。J-Quantsが直近2年・EDINET summaryが古い3年をCOALESCE補完。花王5年EPS=230.59/183.28/94.37/231.94/260.30で実証。US GAAPは5年史も構造化されず→insufficientのまま（捏造しない）
- **3-c 財務由来指標（11指標の生値＋5状態status）**: ROE/自己資本比率/D/E/営業益率/配当性向/DOE/EPS成長/売上CAGR/FCFカバ/利剰配当倍率/ROIC−WACC。点指標は最新**J-Quants確報**をアンカー（5年史の薄いorphan行を掴まない）、深いBS（有利子負債/利益剰余金/capex）は各フィールド最新非NULLを独立取得、成長は5年史CAGR。コホート35社status分布: equity_ratio/roe=35ok、営業益率31ok（残=銀行/持株/IFRS営業益欠落・正当）、EPS成長28ok・売上CAGR30ok、FCFカバ22ok。**確証主義の実証**: ①**IFRS有利子負債は企業独自拡張タグ**（NTT=ShortTermDebt/ソニー=Borrowings系）で完全抽出不可→標準BondsAndBorrowingsが在る社のみok・無ければ**insufficient**（NTT/SBGをD/E=0と偽装しない）。zero_legit(無借金)はJGAAP（標準タクソノミ信頼可）限定。②売上/capexの要素IDが業種で分裂（営業収益・固定資産取得・有形無形合算）→標準タグのみフォールバック鎖化（イオン/日産/高島屋回復、ソニー独自拡張はinsufficient）。③ROIC−WACCは市場値/beta（価格層）依存→現状insufficient。④**EDINET日次スキャンは一過性失敗でデータを黙って取りこぼす**（find_latest_docが例外握り潰し）＝Phase2 robustness課題（全銘柄runでは再取得/検証が必須）
- **3-d 価格由来指標（6指標）**: PER=価格/EPS・PBR=価格/BPS・時価総額=価格×株数・配当利回り=DPS/価格・ミックス係数=PER×PBR・ネットキャッシュPER。最新終値×最新J-Quants確報の1株/株数。コホート34/35ok（日産=赤字でPER系insufficient・クレディセゾン=J-Quants基礎データ無でPBR/時価missing・メルカリ=無配で利回missing＝全て正当）。実値も妥当（花王PER23.4/PBR2.59、JT時価12兆、メルカリPBR6.2成長株プレミアム）。
- **beta（株価×日経225回帰）**: 週次5年リターン回帰 beta=Cov/Var。市場=日経225（^N225→price_history code 'N225'。**TOPIX指数は無料取得不可・TOPIX連動ETF1306は2026-03の1:10分割未調整で分散膨張→不可**。指数は分割/配当なくクリーン）。月次60点はノイズ過大（神戸物産-0.29）→週次260点で是正。検証: SBG1.72/ソニー0.93/日産0.89/銀行0.72（高beta景気敏感）、JT0.28/花王0.21（低betaディフェンシブ）＝相対順位正確。`findex prices --benchmark`でN225取得、`derive --what beta`。
- **ROIC−WACC活性化（beta後段）**: NOPAT=営業利益×(1−税率)、投下資本=自己資本(簿価)+有利子負債、ROIC=NOPAT/投下資本。CAPM Re=Rf+beta×ERP、Rd=支払利息/有利子負債（取れねば2%）、WACC=(E/V)Re+(D/V)Rd(1−税率)・E=時価総額。**定数 Rf=0.01/ERP=0.06/実効税率=0.30 をモジュール定数で明示**（個別未抽出のため固定）。**確証主義の連鎖**: 有利子負債が信頼抽出できない社（IFRS拡張タグ＝NTT/ソニー/ユニチャーム/ニトリ）はD/E insufficientを連鎖してROICもinsufficient（偽値を出さない）、無借金JGAAPはD=0で算出可、営業利益不在の銀行/持株（MUFG/SBG/クレディセゾン）も算出不能。コホート26/35ok。実値の経済的妥当性: アセットライト高ROIC（USS14.97%/神戸物産13.86%/電通総研12.48%）が上位、資本集約/苦戦（ガス0.9%/武田-0.4%/日産-1.1%/アステラス-1.8%）が下位＝直感と一致。`derive --what roic`。`--what all`順序=streaks→dividends→financials→prices→beta→roic→grades
- **3-e claim別グレード＋恒等式チェック（導出層の最終出口）**: 主張(claim)ごとに依存指標(status_jsonキー)集合でA〜Dを付ける（D2 §6.2）。core=必須/extra=期間充足・補助。**A**=core全ok＋extra充足、**B**=core全okだがextraにcensored(N+)/insufficient/missing、**C**=core一部insufficient/missing（評価不能＝投稿しない）、**D**=coreが一つも算出されず（無配の配当系・該当データ皆無＝構造的対象外）。insufficient(抽出を試みたが信頼不可)と missing(そもそも無い)を区別。4claim=配当系/バリュ系/財務系/資本効率系(入手難)。コホート分布: 配当 A28/B6/D1（D=メルカリ無配）、バリュ A32/C2(クレディセゾンJ-Quants基礎無・日産赤字)/B1(メルカリ無配)、財務 A21/B10/C4（C=営業益率欠落の銀行/持株/IFRS：MUFG/SBG/クレディセゾン/ユニチャーム）、資本効率 A21/C14（入手難claimらしくIFRS拡張・銀行/持株・リースがC）。営業利益率はhealthのcoreに据える（銀行の自己資本比率は構造的に低く誤解を招くため、汎用比率だけで健全性Aを与えない保守判断）。**identity_ok=恒等式 DOE≒ROE×payout のクロスチェック**（3指標とも ok のとき・許容誤差15%）: 一致30/不一致2/判定不能3。不一致=キヤノン(純益/EPS×株数=0.677)・神戸物産(0.809)＝**自己株式多で per-share(期中平均・自己株除く)と総額(期末発行株数)の基準差を実検出**＝品質監査として機能。`derive --what grades`

### 評価層(Phase4・v4)の実データ確認サマリ
- **status_based 動的分母（D4 §1の核心）**: ok/zero_legit のみ分子・分母に算入。missing/insufficient/censored は両方から除外（持っていないデータで罰しない）。旧v3「None→0点・分母に残す」アンチパターンを是正。スコアは `dividend_scores`、ルールは `rule_versions`(SHA256版管理)。`findex score --cohort`
- **v4較正**: ①10年CAGR廃止→YoC(取得利回り5年)新設＋**質ゲート**(dividend_quality で×1.0sound/×0.5payout_driven/×0.3cyclical)＋DOE新設 ②自己資本比率80%→70%・ROE20%→15% ③営業利益率を**業種相対**(sector33内パーセンタイル・母数min_sector_n=4未満は絶対閾値フォールバック) ④動的入れ替え(large_cap≥1兆/financialでroic→利益剰余金倍率・net_cash_per→ミックス係数・金融は自己資本比率除外)
- **発見＆是正した実装バグ**: `consecutive_no_cut_years`（最高重み2.5の核心指標）に**status未付与**で全銘柄が採点から除外されていた→`compute_streaks_for_code`で連続非減配にもstatus(ok/censored)を付与。`build_streaks`はstatus_jsonを上書き（merge でない）ため`--what all`で先頭実行が前提（単独runは他statusを消す）。
- **コホート採点**: n_scored=11〜15が大半（フルデータ社）。ランキングは高配当ツールとして妥当（配当良質なリース/アセットライト＝みずほリース90.7/USS87/SPK80.6が上位、成長/無配のソニー・SBG・メルカリが下位）。**薄いデータinflationを実観測**: クレディセゾン7指標のみで93.6点1位だがグレードC/C/C＝設計通り「歯止めはスコアでなくグレード（score×grade で判断）」。n_scored列で透明化。**重みは旧PJ継承の手づけ→前方アウトカム較正はPhase5.5バックテスト(D8→v5)**

### バックテスト(Phase5.5・D8)の実データ確認サマリ
- **5.5-a 前方アウトカム（完了）**: as_of から前方N年の「実際に起きたこと」＝正解ラベルを `backtest_outcomes` に算出。**純粋に前方データのみ依存（look-ahead無し）**。fwd_div_cut（減配回避＝第一アウトカム）/fwd_dps_cagr（増配実現）/fwd_total_return（価格＋受取配当）/fwd_max_dd（危機耐性）。as_ofグリッド=各年6月末2008〜2020・horizon3/5。`findex backtest --cohort --what outcomes`
- **減配検出の頑健化（2つの罠を実データで是正）**: ①**特配スパイクが窓先頭**（花王FY2012=93特配で窓開始）→前方窓に**2年の後方文脈を含めて**判定し誤検出回避 ②**配当の分割単位不整合**（神戸物産2009=0.156÷6・沖縄セルラー2010=9.375÷2＝実際は増配継続）→単年で前年の55%未満への急落＋翌年に前年水準へ即復帰するV字は分割アーティファクトと見なし除外。**JTのFY2021実減配(154→140=91%)は閾値超で真の減配として残す**＝アーティファクトと実減配を弁別。
- **コホート検証**: 減配42/884窓(4.75%)が全て危機期/既知の減配者に集中＝日産14(2008危機+Ghosn/COVID・前方TR-0.53/最大DD-0.70)・JT8(FY2021高配当の罠)・ソニー8・キヤノン8(COVID)・ロート4(リーマン)。連続増配の常連(KDDI/アステラス/花王)は減配0＝正解ラベルとして妥当。
- ⚠**全銘柄バックテストの前提条件（未充足）**: ①`delisting_date`収集（生存バイアス排除・現状コホートは現役のみ）②配当の分割単位正規化（上記アーティファクトの上流是正）。コホートは配線検証用。

### 出力(Phase6)のMVP — パイプライン端から端まで貫通
- **MVP HTMLレポート（完了）**: `findex/post/report.py`＋`findex report --cohort`→`docs/html/report.html`。**柱3で初の触れる成果物**。設計の安全弁D2 §6.5（完璧主義を待たず確信できるclaimから出力）を実装。**品質ゲートを実装で遵守**: status=ok/zero_legitの数字だけ表示（他は「—」）・連続年数の打ち切りは「N年以上」（花王36→16事故の再発防止）・ZAi公表override由来は出典バッジ・claim別グレード併示・免責必須・数字は全てDB由来。
- **2部構成**: ①連続増配・非減配ランキング（配当claim grade≠Dを連続増配年数で降順。花王36年[ZAi公表]がトップ＝再構築の動機だった連続増配の正確性を実証）②v4総合スコア（参考・4グレード併示）。②には**暫定の明示注記**（重み手づけ・バックテスト未完・薄いデータは指標数少でスコア上振れ→歯止めはグレード）。クレディセゾン7指標93.6点1位がC/C/C/7で透明に可視化。
- ローカルHTML一級化（D5）＝X障害時の受け皿・自前サイト・投稿画像の母体。生成物はgitignore（再生成可能）。
- **X投稿draft（Phase6 MVP段階1・完了）**: `findex post streak [--cohort] [--top N] [--publish]`。D5 §8の「1テーマ・手動承認付き」を実装。**既定はdraft**（本文＋画像PNG生成＋品質ゲート判定のみ・投稿しない）、`--publish`で実投稿。構成=`post/themes.py`（テーマ生成・本文≤140字加重・claim事後監査）＋`post/image.py`（HTML→PNG・Playwright headless要素スクショ）＋`post/poster.py`（旧x_posterベース＋**画像添付対応**を新規追加・セッション再利用`~/.findex/x_session.json`）。**品質ゲートを実コードで実装**: status_ok_only（fetch_rowsがstatus=okのみ値・report.pyと共有の単一実装）/censored_as_n_plus（打ち切りは「N年以上」）/source_cited（ZAi公表バッジ）/grade_shown（claim別grade併示）/body_within_limit（加重140字・**初版192字は本文超過でゲートが正しくブロック**→126字に短縮）。`passed=False`なら投稿拒否（沈黙は許容・誤発信は不可）。画像=ダーク固定テーマのランキングカード（花王36年[ZAi公表]・三菱HCキャピタル27年以上[N+]等が品質ゲート通り表示）。テスト3追加（weighted_len/本文140字回帰/テーゼ含有）で計65緑。実投稿は`.env`のX認証＋ユーザーGO後。

---

## 6. 既知のリスク・宿題

設計凍結中なので「未解決の設計課題」と「設計で解決済み・実装待ち」を区別する。

> ### ★データ可用性ブロッカー: 生存バイアス排除は無料データで不可（2026-06-16実証・ユーザー了承）
> **廃止株の過去株価・配当は無料ソースから取得不能**（実証: ライブドア/武富士/カネボウ等の廃止コードは yfinance=0行「possibly delisted」・Yahoo!JP=404。現役のみデータ有）。設計D8は delisting_date を「クラスC・要収集」と楽観視したが、実地では**廃止株データは有料tier（J-Quants premium等）にしか無い**（現契約J-Quantsは2年窓で不可）。
> **影響**: バックテストは**生存者のみ**になる。最悪の配当結末（減配→倒産→廃止）が標本から消えるため、**減配回避率など「配当安全性」が楽観側に偏る**（ツールの核心主張が最も盛られる）。中央値・相対順位への影響は小、テール（破綻回避の絶対率）が甘くなる偏り。
> **方針（option 1）**: ①全バックテスト指標に survivorship 注記必須 ②**相対メトリクス優先**（生存者内の順位相関・指標別IC・分位スプレッド）・絶対率は楽観側上限として扱う ③「グレードAは廃止しない」等の絶対断言は禁止 ④廃止株データの有料調達は将来アップグレードとして記録。**現在スコア/MVP出力は無影響**（生存バイアスが歪めるのは過去検証のみ・現役株のtoday採点は無傷）。

> ### ★第2のブロッカー: 財務データ深度が5年のみ＝財務系指標はバックテスト不能（2026-06-16・PIT実装で判明）
> PITスコア再現を実装(`backtest/pit.py`・as_of別in-memory DBで評価層を回す・コミット予定)して判明: **financial_snapshotsはFY2021-2026の5年のみ**（J-Quants2年窓＋EDINET有報「主要な経営指標」5年バックフィルの深さ）。一方バックテストのas_ofグリッドは前方3-5年アウトカムのため2008-2020。**財務データ(2021+)とas_of点(〜2020)が重ならない**→財務系/バリュ系/資本効率系の指標はPIT再現できず、**バックテストは実質「配当シグナルのみ」**(連続年数・減配信頼性・YoC・増配の質・配当利回り＝配当データは1989まで深い)。財務系指標の検証にはEDINET有報を2008まで多年バックフィルする取得拡張が必要(現状未収集)。加えて**歴史as_of点ではresult_override(ZAi2025公表)が時点フィルタで除外され連続年数は機械値のみ＝特配ペイヤー(花王)で過小・ノイズ**。PIT機構自体は正しく動作(花王の機械ストリークがas_ofと共に増加=time-filter正)。
> **含意**: 完全なモデル検証(全指標の重みv5較正)は財務多年backfill＋全銘柄(統計力)＋廃止株(survivorship)が要る大仕事。**いま無料データで可能なのは「配当シグナルが前方減配回避を予測するか」の生存者・低statistical-powerな一次検証のみ**。ツールの核心(配当継続性)に当たるので価値はあるが限定的。

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
| **モデル（重み）が無検証** | 🟨 最大の盲点。重みは旧PJ手づけ→**D8バックテストで前方アウトカム較正→v5**（Phase5.5・design-review #1）。配線+方向性は確認済、統計的有意性は全銘柄＋廃止株が前提 |
| **株数/分割の基準ズレ（多軸一致・最優先）** | 🟩 **T1是正 完了（2026-06-24）＝17→7→4件**。残7件をyf権威株数(`get_shares_full`)で全数裏取り→真の分割バグ3件のみ是正: **2726**=重複split畳み込み窓7→14日／**5535・8022**=shares系統限定の明示override(`_SHARES_FACTOR_OVERRIDE`・DPS不変)。是正後mcap収束(2726 -3.2%/8022 +1.5%/5535 -6.7%)。pytest152・golden18/18・doc11既存(UT/日鉄/伊藤忠)不変。**残4件(8746/8887/6659/6664)はsplit無しの決算後増資＝鮮度クラスと確定（分割バグでない・本番J-Quants待ち）**。〔前段Phase2: doc11を開示日基準化(`disclosed_date`4,654行)＋splits空応答洗替の二次バグ根治(2c0314b)・UT 0.76→11.45。Option1=yf発行済株数の全面採用は**不採用/revert**＝報告株数こそ真値(優先株/金庫株でyfがブレる・伊藤園/キヤノンで実証)〕。正本=`docs/yahoo-crosscheck-remediation.md` T1節 |
| **PBR/自己資本(BPS)の基準・抽出エラー** | 🟨 **NEW（2026-06-23・448件、大半は鮮度/四半期差±20-30%）**。PBRだけズレ時価総額は一致＝株数は正常でBPS/自己資本側。**最大の異常=4222児玉化学**（PBR+593%だが時価総額は−0.5%で一致＝前回「株数7倍誤り」の見立ては誤り、真因は自己資本5.47Bが過小・FY系列でbps不整合）。多視点で初めて正診できた典型 |
| **時価総額の株数基準差（自己株/浮動）** | 🟨 **NEW（2026-06-23・78件）**。時価総額だけズレPBRは一致＝発行済 vs 上場株式数（自己株控除）の差。大型株に系統的（7267ホンダ等）。一括検証可能 |
| **予想配当の分割欠落＋多軸混在の要確認** | 🟨 **NEW（2026-06-23）**。予想配当の分割欠落クラスタ（2296/5410/9629等・`yahoo_highdiv_compare_*.csv`）＋多軸混在292件（7273イクヨ 利回り+1005%等の個別要確認）。`yahoo_ranking_triage_*.csv` |
| **予想配当の鮮度差（−乖離）** | 🟨 当環境のJ-Quants予想as_ofが2026年初で頭打ち→Yahoo(6月)の改定/増額を未反映。本番J-Quants環境での再取得で解消（runbook=PROJECT-LOG・予想切替フェーズ） |
| **配当接合の単年seam穴** | 🟨 haitoukin/events接合で一部銘柄に単年欠損（FY2000接合穴9社）。F3で正直化済(censored)＝害なし・上流修復は任意 |
| **配当のpre-2000 review銘柄** | 🟨 合併等で接合が不整合（ユニチャーム/イオン等）はconfidence=review→左打ち切り/override/N+で扱う |
| **`delisting_date` 収集（生存バイアス）** | 🟨 廃止株データは無料ソースに無い＝ハードブロック。有料tier前提（§6冒頭ブロッカー）。全銘柄backtestのv5較正もこれ待ち |
| **listing_date NULL床のkabutan補完** | 🟨 yfinance床に張り付く古参は真値不明のまま（Playwright補完が後続・任意） |
| **doc17保留テーマ（beta/CFマージン導出）** | 🟨 defensive_moat(beta)/recurring_revenue(operating_cf÷revenue)は生値DB有・fetch_rows未露出＝導出層作業で投稿テーマ化可能 |

> **解決済みに格下げした旧リスク**: ~~X自動化の脆さ/ToS~~（→¥0 GitHub Pages 投稿ハブ方式を採用＝自動投稿せず最後のタップのみ手動・2026-06-21）／~~`streaks.py` ギャップ中断の打ち切り未検知~~（→F3 `3c6deb0` で censored 化）／~~UTグループ型 PER/PBR異常低値~~（→doc11 分割基準補正 `4f295de` で根治・UT 0.78→11.65）／EDINET会計基準別パース・yfinance株価検証（取得層で実証）。

凡例: ✅実装で解決 / 🟨未解決リスク・要注視 / 🟥実装バグ

### 6.3 次の一手（残タスク・優先順）
セッション再開時の起点。詳細手順は各設計書／`docs/PROJECT-LOG.md`／`logs/DEVLOG.md` を参照。

1. **【柱1・対策フェーズ】Yahoo多軸突合の是正タスク → 正本=[`docs/yahoo-crosscheck-remediation.md`](yahoo-crosscheck-remediation.md)** — 検証ツール3本（読み取り専用）: `scripts/yahoo_highdiv_compare.py`（配当）/`scripts/yahoo_ranking_snapshot.py`（5軸断面）/`scripts/yahoo_ranking_triage.py`（軸を{データ:PBR/時価総額/利回り}と{基準差:PER/ROE}に分け符号・係数で根因分類→`logs/yahoo_ranking_triage_*.{csv,md}`）。**全3,905銘柄 分類済**。軸別整合=時価総額94%・PBR80%・利回り78%が±15%内（findexの裏取り）。是正タスク（詳細は是正台帳）: **T1 株数/分割の多軸一致17件（🟥最優先・確実）**／T2 PBR自己資本の極端42件（4222等）／T3 配当findex過大66件（split漏れ/ghost）／T4 時価総額の株数基準78件（自己株/価格日差）／T5 多軸混在292件（個別）。健全=基準差のみ1557＋整合843＝対応不要。※各タスクは「数件で裏取り→一括補正→再突合で確認」、1軸の見かけで一括修正しない（4222を多軸で正診した教訓）。
2. **【柱1/柱2・本番依存】本番J-Quants環境での予想更新（FY2027反映）** — 当開発環境は開示が2026年初で頭打ち＝ここで再取得しても無意味。最新開示が取れる本番でのみ runbook（再取得→FY2027中止ゲート→derive→突合で乖離縮小確認→publish_hub）を実行。−乖離の鮮度差が解消する。
3. **【柱2・大物】全銘柄backtest → v5重み較正** — 現状は配線+方向性のみ。統計的有意性には ①財務多年backfill（現状5年）②全銘柄（統計力）③廃止株収集（生存バイアス・#4）が前提＝段階作業。
4. **【柱1・ブロッカー】廃止株収集（生存バイアス排除）** — 無料データに廃止株なし＝有料tier前提で現状ブロック。解消すれば #3 の前提が揃う。
5. **【柱3・任意】投稿層の拡充** — doc17保留テーマ（beta=defensive_moat / CFマージン=recurring_revenue）の導出層露出でテーマ追加。武田型トラップのさらなる調査（doc12系・タスク化済）。push通知チャネル（Telegram/ntfy・現状ブックマーク/iOSアラーム運用）。

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
