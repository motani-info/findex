# 15 - 全テーマ8軸標準化＋総合スコア右端固定（カード統一）

> 起点: doc14 で large_cap だけ8軸化したが、ユーザーレビューで「テーマ毎に軸数がバラバラ／
> 総合スコアが無い」「#・コードが省略され崩れる／タイトルが暗い」と指摘。全17テーマを統一。
>
> 関連: [[14-sort-honesty-and-net-cash-floor]]

## 1. 方針（ユーザー決定）

- **テーマ固有＋共通コア**方式（全テーマ完全同一は不採用＝固有指標が消えるため）。
- 全テーマを **8軸**（配当利回り＋6データ列＋総合スコア）に統一し、**総合スコアを右端に固定**。
- 列レイアウトを最適化（#・コードは省略しない／銘柄のみ枠内省略）。

## 2. 標準8軸の構成（`_std_cols`）

配当利回り（行頭強制）＋ **テーマ固有列**（signature）＋ **共通コア**で不足分を補充 ＋ **総合スコア（右端固定）**。

- 共通コア `_CORE_COLS`: 連続増配 / 配当性向 / PBR / ROE / 時価総額（この順で、signature に無い key を6データ列に達するまで補充）。
- `_STD_DATA_COLS=6`（配当利回りを除くデータ列数）。+総合スコア＋配当利回りで8軸。
- 固有 key がコアと重複する場合は固有を優先し二重化しない（例: streak は 連続増配 を固有に持つ）。
- 各テーマの signature（固有列）:
  streak=連続増配/連続非減配/増配の質、no_cut=連続非減配/減配信頼性/増配の質、
  long_growth=連続非減配/YoC/増配率5年、growth_room=FCFカバ/増配率5年、fcf_coverage=FCFカバ、
  high_roe_growth=営業益率、total_score=4grade、high_yield=減配信頼性/連続非減配、
  low_pbr_yield/large_cap/small_value=PER、roic_spread=ROIC−WACC/営業益率、doe_king=DOE/自己資本比率、
  high_yield_safe=YoC/減配信頼性/増配の質、div_growth=YoC/増配率5年/増配の質、
  value_quality=PER/自己資本比率/財務grade、net_cash=実質PER/表面PER。

## 3. レンダリング（`_rank_card(fixed_layout=True)`）

- `table-layout:fixed`＋`<colgroup>`で **#=44 / コード=72 / 銘柄=190 を固定、残りデータ列は均等配分**。
  カードは `.card.wide`（max-width 1120px）。
- **省略は銘柄列(3列目)だけ**（`nth-child(3)` に ellipsis）。#・コードは切らない
  （doc14 の全セル ellipsis で「10→1...」「コード→コ...」と崩れたバグの是正）。
- タイトル `.card h1{color:var(--ink)}` を明示（暗く沈む問題の是正）。
- 強調(teal `.hot`)は「高い＝良い」指標のみ（ROE/総合/長期増配/YoC等）。配当性向・PER・実質PER・
  自己資本比率は非強調 `pct_plain`/`x_plain`（doc14 で新設）。

## 4. 実装

- カスタムビルダー5本（streak/high_yield_safe/div_growth/value_quality/net_cash）を共通ヘルパー
  `_std_cols`/`_std_head`/`_render_rows`＋`_rank_card(fixed_layout=True)` に集約。旧 `_ranking_card_html` 廃止。
- `_ranking_theme` は `columns`→`signature` を受け取り `_std_cols` で標準8軸を生成。`_SPECS` 全テーマを
  signature 方式へ。`col_widths`（doc14）は固定レイアウト自動化に伴い廃止。

## 5. 検証

- pytest **113 passed** / `verify --all` golden **18/18 不整合0** / post-gallery 再生成（全17テーマ8軸・総合スコア右端）。
- 全テーマで右端＝総合スコア・データ8軸を機械チェック。#「10」・コード「9436」が非省略であることを確認。
