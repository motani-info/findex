# 09 - スケール露出データ品質の是正計画（posts.html FB起点）

> 起点: 2026-06-17、全データ洗替（全3734）完走後に `findex post-gallery --all` →
> `docs/html/posts.html` を目視。ユーザーFB「多くのランキングでデータが壊れている／
> 銘柄名がない／配当利回りがない」。本書は調査結果と是正の実行計画。
>
> **★ステータス: 完了（2026-06-17）** — §3の全7ステップを実装・検証済み。golden 18/18
> 死守・pytest 77 passed・残存外れ値(ok>閾値)0件・名前欠落0件。詳細は §4。
>
> 関連: [[00-charter-and-data-integrity]]（定款＝全銘柄全データの正確性が土台）、
> 「小サンプル成功 ≠ スケール安全」。golden 18/18 通過は**必要条件だが十分でない**
> （goldenは18コホート銘柄しか見ず、全3734の外れ値を検出できない）。

## 1. 調査結果 — 3つの根本原因（実値エビデンス付き）

### A. 銘柄名が出ない（名前欠落）
`findex/post/report.py` の `fetch_rows`（L79-82）が **`load_cohort()`（35社）からしか
名前を引いていない**。全銘柄ギャラリーでは非コホート銘柄が `names.get(code,"")` で空に
なり、`🥇` メダルだけ表示される。花王(コホート)は出るが 3070 等は出ない。
**stocks テーブルには3734社すべて name がある** → 取得元を間違えているだけの局所バグ。

### B. 配当利回りが「ない／壊れている」（鮮度欠如）
`annual_div` が**年代を問わず「最新の入手可能DPS」を採用**している。
- 例: 3070 ジェリービーンズ。dividend_annual は **2018年(16円)が最後**。現在株価 62円。
  → div_yield = 16 / 62 = **25.8%**（status=ok で素通り）。配当が8年前で止まっている
  のに「現役配当」として利回り計算している＝**配当鮮度(recency)判定が無い**。
- 一方 324A 等の新規上場は div_yield=missing で正当に「—」。だが利回り主役テーマの
  上位に来ると「利回りが無い」に見える（これは表示順の問題）。

### C. データ全般が壊れて見える（外れ値のスケール露出）
コホート35社には存在しなかった**外れ値が全3734で status=ok を素通り**し、テーマの
sort が外れ値を最上位へ押し上げる。

| 指標 | status=ok のまま異常 | 件数（/3710） |
|---|---|---|
| div_yield > 10% | 廃配/特配/株価瞬間値 | 16（>15%は6） |
| dividend_growth_5y_cagr > 50% | 復配・低基底からの増配 | 94 |
| \|roe\| > 100% | 微小・負の自己資本で分母崩壊 | 52 |
| per > 200 | 薄利益 | 37 |
| pbr > 20 | — | 26 |

→ 定款「小サンプル成功 ≠ スケール安全」の典型。

## 2. 対応方針

**根治点は derive層（`findex/derive/compute.py` の status 付与）**。ここで直せば
report/themes 両方が自動で恩恵を受ける（表示層で個別パッチしない＝定款の「単一ゲート」
原則 = `fetch_rows` が report/themes 共通入口）。

1. **A 名前**: 表示層の局所修正。`fetch_rows` を stocks テーブルからの一括 name 取得に
   変更（cohort依存を撤廃）。
2. **B 鮮度**: derive層に**配当鮮度ゲート**を新設。as_of基準年から一定年数（素案3年）
   以内に配当実績が無ければ div_yield/YoC 等を `stale`（表示「—」）に。廃配・休配を
   現役利回りから排除。既存 `flag_dividend_anomalies` と整合させる。
3. **C 外れ値**: derive層に**経済的サニティ範囲ゲート**を新設。範囲外は `ok` のままに
   せず `suspect`（表示「—」＋review隔離）。範囲はステップ2の実データ分布から較正
   （恣意的な数字を置かない）。素案: div_yield≤12%, |roe|≤100%, per∈(0,200], pbr≤20,
   cagr≤50%。
4. **テーマ eligibility 強化**: 薄データ（n_scored小）・suspect銘柄を各テーマで除外。
   全銘柄前提で再設計。

## 3. 実行計画（順序＝下層から）

| # | ステップ | 内容 | 検収 |
|---|---|---|---|
| 1 | A 名前修正 | `fetch_rows` の name 取得を stocks 全銘柄へ | post-gallery で全行に銘柄名が出る |
| 2 | 外れ値の分布調査 | div_yield/roe/per/pbr/cagr の全3734分布→サニティ閾値を**実データで較正** | 閾値ごとの除外件数・除外銘柄が妥当 |
| 3 | B 鮮度ゲート | compute.py に配当recency判定→div_yield/YoC/関連に stale | 3070=stale化・花王等の現役は不変。golden 18/18 不変 |
| 4 | C サニティゲート | compute.py に範囲外→suspect。status分布に新状態追加 | per>200/roe>100%等が「—」化。golden 18/18 不変 |
| 5 | テーマ eligibility 強化 | 薄データ/suspect除外を `_ranking_theme`/各builder に | 各テーマ上位が実在の優良銘柄に |
| 6 | 再生成＋目視検収 | `derive --all`→`score --all`→`post-gallery --all`。17テーマ目視 | 壊れ/空名/異常利回りゼロ |
| 7 | 回帰 | `pytest`＋`verify --all`。golden不整合0を死守 | 全緑・18/18 |

**原則**:
- 各ステップで golden 18/18 を壊さない（コホートの正解値は外れ値修正の影響を受けない
  はず。受けたら修正側のバグ）。
- 閾値は必ずステップ2の実データ分布から決め、勘で置かない（定款）。
- 鮮度/サニティは新 status 値（stale/suspect）で表現し、missing/insufficient/censored
  と区別する（情報を潰さない）。

## 4. 実施結果（2026-06-17 完了）

### 確定閾値（全3,710社の実分布 p99 から較正・ステップ2）
| 指標 | p99 | 採用閾値 | 範囲外を | 該当件数 |
|---|---|---|---|---|
| div_yield | 7.2% | ≤12% | suspect | 4（残りは鮮度でstale） |
| \|roe\| | 131% | ≤100% | suspect | 52 |
| per | 221 | ≤200 | suspect | 37 |
| pbr | 15.9 | ≤20 | suspect | 26 |
| dividend_growth_5y_cagr | 64% | **≤65%**（p99基準・ユーザー判断で素案50%から緩和） | suspect | 26 |
| 配当鮮度 | — | 最新株価年から**3年**超で配当途絶→stale | stale | div_yield 121 / yoc 105 |
| n_scored（薄データ） | — | **≥8**（左裾1-7=425社/11.5%を除外） | テーマ除外 | golden18社は全て≥11で不変 |

### 変更ファイル
- `findex/post/report.py` — `fetch_rows` の name 取得を `load_cohort()`(35社)→`stocks`全件INに修正（A 名前バグ）
- `findex/derive/compute.py` — `DIVIDEND_RECENCY_YEARS`/`SANITY_MAX_*` 定数＋`_dividend_is_stale` 新設。
  div_yield(stale/suspect)・yield_on_cost_5y/10y(stale)・per/pbr/roe/dividend_growth_5y_cagr(suspect) にゲート適用
- `findex/post/themes.py` — `MIN_N_SCORED=8`＋`_sufficient()` を `_ranking_theme` と5つの手書きbuilderに適用

### 検収結果（ステップ6・7）
- **A 名前**: posts.html の銘柄名欠落セル **0件**（3070「ジェリービーンズグループ」表示）。
- **B 鮮度**: 3070 が div_yield 25.8%/ok → **stale**（— 表示）。花王等の現役配当は不変。
- **C サニティ**: 残存 ok>閾値（div_yield>12% / \|roe\|>100% / per>200）すべて **0件**。新status stale=331・suspect=145。
- **テーマ**: total_score 上位が ファンペップ(n_scored=1) → スターツ出版等(n_scored≥11) に是正。17テーマ全て該当5社・上位は健全レンジ内。
- **回帰**: `verify --all` golden 検査18・一致18・**不整合0**（死守）。`pytest` **77 passed**。
- 新status `stale`/`suspect` は表示層(`_val`)・採点層(`_SCORED_STATUS`)・grade(`_OK_STATUS`)が
  全てホワイトリスト方式のため自動的に「—」化／動的分母から除外（ブロックリスト改修不要＝定款の単一ゲート原則）。

## 5. 追加是正: テーマ別 配当利回りフロア（2026-06-17 ユーザーFB）

posts.html 目視で「高配当/増配を謳うテーマに低・無配当が上位に来る」FB（例: large_cap に
東京エレクトロン0.9%・ファストリ0.4%、growth_room に 0.2%級のほぼ無配）。テーマの看板に
応じた**段階的な現配当利回りフロア**を `themes.py` に新設（`_yield_ok`）。一律フロアは増配
アリストクラット（花王2.5%・小林製薬1.9%）を消すため不採用。バリュー/資本効率テーマは
利回りが主旨でないため適用外。

| 群 | フロア | テーマ |
|---|---|---|
| 高配当系 | **≥3.0%**（high_yield は看板どおり3.5%維持） | high_yield_safe, low_pbr_yield, large_cap(時価総額順は維持), small_value |
| 増配・配当系 | **≥2.0%** | div_growth, growth_room, fcf_coverage, doe_king, total_score |
| 連続/質系 | **≥1.5%**（アリストクラットを残す） | streak, no_cut, long_growth, high_roe_growth |
| バリュー/資本 | フロアなし | value_quality, net_cash, roic_spread |

検収: 全17テーマで上位5の利回りがフロアを満たす（違反0）。large_cap=トヨタ/東京海上/NTT等
（全て≥3.0%）、doe_king=ミンカブ6.2%等（—/0%消滅）、連続系は花王/小林を維持。pytest 77 passed。
`dy=None`（stale/suspect/missing）はフロア不通過で自動排除＝低配当と無配当を同時に弾く。
