# findex v2 実装フェーズ計画

**作成日**: 2026-06-15
**位置づけ**: 設計（D1〜D7・D5除く）完結を受け、**設計を実装可能なタスクに分解**した橋渡し。正本の設計は各Dドキュメント、本書は実行順序とゲート。
**重要**: 着手は**ユーザーのGO後**。現時点は実装凍結のまま（本書は計画）。

---

## 0. 大原則（凍結解除後も厳守）

- **設計ドキュメントが正本**。コードは [data-model](design/data-model.md)(D3)・[indicator-system](design/04-indicator-system.md)(D4)・[indicator-calibration](design/04_5-indicator-calibration.md)(D4.5)・[data-workflow](design/data-workflow.md)(D7)・[verification](design/06-verification-strategy.md)(D6)と必ず突合してから書く。
- **一方向フロー**（取得→導出→評価→出力）。後段は前段テーブルだけ読む。
- **各フェーズの完了ゲート＝コホート検証(L2)が緑**。golden不一致なら次へ進まない。
- **レート制限**: 開発は常にコホート38社（`--cohort`）。全銘柄スキャンは golden が通ってから1回だけ。
- **DB**: 開発は `~/.findex/db/findex_v2.db`。旧 `findex.db`(223MB)は**読み取り専用の移行元**。直接書かない。

---

## 1. 雛形の流用可否（棚卸し）

| 既存 | 状態 | 方針 |
|---|---|---|
| `derive/streaks.py`（+test 10件green） | 打ち切り判定あり・配当中心 | **流用**。result_overrides汎用化＋status出力＋ギャップ打ち切りバグ修正 |
| `fetch/base.py`（RateLimitedFetcher） | バッチ/レジューム/バックオフ実装 | **流用**（ソース別レート設定を追加） |
| `fetch/listing.py` `fetch/prices.py` | 骨格(NotImplemented) | **作り直し**（kabutan/J-Quants/yfinance） |
| `db/schema.sql`（12テーブル・旧） | streak_overrides・status無し・会計メタ無し | **全面更新**（D3へ） |
| `score/` `post/` | ほぼ空 | **新規実装**（v4） |
| `cohort.py` `config.py` `cli.py` | 骨格 | 拡張 |

→ 流用は streaks/base のみ。**schema と fetch本体・score・verify は設計（D3/D4/D4.5/D6）から新規**。

---

## 2. 実装フェーズ（依存順）

### Phase 0: スキーマ再生成（D3）
- `db/schema.sql` を data-model(D3) から作り直す:
  - `result_overrides`（旧streak_overrides汎用化）、`stocks`に会計メタ+edinet_code、`financial_snapshots`にcapex/investment_securities/interest_expense等、来歴メタ(source/confidence/as_of/collected_at)、`computed_metrics`にstatus列＋claim別グレード
- `findex initdb` で findex_v2.db に適用（旧DBは触らない）
- **ゲート**: スキーマが全Dドキュメントのテーブル定義と一致

### Phase 1: マスター＋移行（D7 §7）
- JPX Excel → stocks（コード/名称/市場/sector33）
- **EDINETコードリストzip → edinet_code/決算期末月/連結**（実証済・3,842件・即時）
- kabutan → listing_date（**現0%・打ち切り判定の鍵**）
- 移行: 旧DBから `dividend_annual`(source!='events') と `streak_overrides`→`result_overrides`変換 を投入（再現困難・最優先）。price/financialは移行せず再取得
- **能動洗浄（design-review #7）**: yfinance配当(1999+)を再取得し移行dividend_annualと相互照合→乖離をreviewレポート
- **ユニバース確定（#8）**: JPX一覧から普通株抽出（ETF/REIT/優先株除外）。`delisting_date` 収集（生存バイアス排除・D8前提）
- **ゲート**: コホート38社のstocksが会計メタ・listing_date・delisting_dateまで揃う

### Phase 2: 取得層（D7 §0,§3,§4・fetch）
- **EDINET早期スパイク（design-review #4）**: 着手最初にJGAAP/IFRS/US各数社で会計基準別ラベル辞書の成立を確認（KDDI1社では不足・current_assets空振り既知）。辞書はYAMLで版管理・golden_financialsで単体検証
- prices: J-Quants（直近）＋ **yfinance 2000年遡及**（旧は2024-06〜のみ＝不足）
- **株価検証（#3）**: J-Quants×yfinance突合・分割イベント独立検証・外れ値検知（YoCの背骨の信頼度担保）
- financials: J-Quants `/fins/summary`（現在〜2年）＋ **EDINET有報XBRL**（深いBS・capex・**会計基準別ラベル辞書**・提出日日次スキャン）
- dividends: events取得 → dividend_annual(events) 再構築 ＋ haitoukin backfill
- result_overrides: ZAi/みんかぶ/IRから連続年数の"結果"取り込み（出典・as_of必須）
- すべて RateLimitedFetcher 経由
- **ゲート**: コホートで各フィールドのstatus（ok/missing）が想定通り。**EDINETパース成功率が基準別に閾値以上**（未満なら当該capital claimをgrade C固定）

### Phase 3: 導出層（D4・D4.5・derive）
- streaks: result_overrides汎用合成（機械→override昇格→N+）＋**status出力**＋ギャップ打ち切りバグ修正
- YoC（取得利回り）＋ dividend_multiple ＋ **増配の質係数**（EPS倍率/DPS倍率→sound/payout_driven/cyclical）
- DOE（=ROE×配当性向）
- 財務指標（ROE/自己資本比率/FCF=CFO−capex/ROIC-WACC/営業益率）＋ **beta=price×TOPIX回帰**
- 各値に **status付与**（ok/zero_legit/missing/insufficient/censored）＋ **claim別グレード**算出
- → computed_metrics（唯一の出口）
- **ゲート**: golden_streaks 一致（花王=36等）＋ status分布が妥当

### Phase 4: 評価層（D4・D4.5・score）
- rules.yaml を **v4** に更新（YoC/DOE/閾値70-15/業種相対/null_policy:status_based）
- スコアラ: **動的分母**（missing/insufficient/censored除外、zero_legitは0点）、YoC質係数、業種相対（営業益率）、予想欠損の実績フォールバック、大型/金融swap
- rule_versions に v4 登録
- → dividend_scores（claim別グレード併記）
- **ゲート**: コホートのスコアが説明可能（薄データ銘柄が不当に高得点でない＝grade併示で確認）

### Phase 5: 検証（D6・verify）
- `golden_financials` 作成（EDINET/IRから少数銘柄の正解値・会計基準散らす）
- コホート 28→38社 拡張（財務/会計基準/status系）
- 照合レポート（override乖離・J-Quants×EDINET・golden突合）
- `findex verify` CLI（L1単体＋L2コホート＋L3分布を束ねる）
- **ゲート**: `findex verify --cohort` が緑 → **全銘柄スキャン1回**へ

### Phase 5.5: バックテスト＝モデル検証（D8・design-review #1）
- PIT入力ビュー（price/financial/dividend/override を as_of で絞る）＋時点ユニバース（delisting含む・生存バイアス排除）
- 採点エンジンを as_off グリッド（2008-2024各年）で回す → `backtest_scores`
- 前方アウトカム（減配回避/増配実現/トータルリターン/最大DD）→ `backtest_outcomes`
- メトリクス（Spearman/指標別IC/分位スプレッド/グレード較正）→ `backtest_metrics` → HTMLレポート
- **重み較正 → rules.yaml v5**（ウォークフォワードで検証期間が崩れないこと・解釈可能性優先）
- まず golden+コホートで配線検証→フル
- **ゲート**: 総合/claim/グレードが前方アウトカムと相関（効かなければclaim内ランキングに寄せる根拠）

### Phase 6: 出力＝HTML生成＋X発信（D5）
- **HTML生成層を一級コンポーネントに（design-review #6）**: ランキング表/チャートをローカルHTMLで描画→PNG（X画像）＋閲覧可能サイト（X障害時の受け皿・SEO資産）
- X発信: フック（看板=切り口①YoC×持続性）・品質ゲート連動・Playwright投稿（**手動承認フォールバック**）・コンプラ（売買推奨しない・免責固定）
- claim内ランキングを主、総合は足切り付き参考値

---

## 3. マイルストーン

| MS | 完了状態 | 検証 |
|---|---|---|
| M1 | スキーマ＋マスター＋移行（Phase0-1） | コホートのstocks完備 |
| M2 | 取得層（Phase2） | コホートの全フィールドstatus妥当 |
| M3 | 導出＋採点（Phase3-4） | golden_streaks緑・スコア説明可能 |
| M4 | 検証完備＋全銘柄スキャン（Phase5） | `findex verify`緑・全銘柄ランキング生成 |
| **M4.5** | **バックテスト＝モデル検証（Phase5.5）** | スコアが前方アウトカムと相関・重みv5較正 |
| M5 | 出力（HTML生成＋X発信）（Phase6・後日） | サイト生成＋品質ゲート通過の投稿 |

---

## 4. 着手前の確認事項（GO時に決める）

1. **凍結解除のGO**（実装を始めてよいか）
2. **着手範囲**: M1から順か、特定フェーズ先行か
3. **.env整備**: 現在キーは `back_findex/.env`。findex/.env を正式に用意するか（gitignore済）
4. **作業の進め方**: 1フェーズずつレビュー or まとめて
5. **運用設計（design-review #9）**: 実行環境（ローカルMac/cron想定）・フルスキャンの実時間見積（3,800銘柄×2000遡及＋EDINET日次は数時間〜日規模）・API課金/上限・部分失敗の再開・**停止条件の通知手段**（run_logだけでなく通知）

→ GO が出たら Phase 0（スキーマ再生成）から着手。各フェーズ末にコホート検証で区切る。
