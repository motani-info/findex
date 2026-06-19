# 12 - 生利回り系テーマの罠フィルタ（タコ足・偽ROE・復配ジャンプ）

> 起点: 2026-06-19、外部レビュー（Gemini）が再生成後の `docs/html/posts.html` 全16テーマを
> 実市場データと突合し「実態と乖離したゴーストデータ4つ」を報告。実データ（computed_metrics /
> financial_snapshots）・実コード（themes.py）・実ランキングで裏取りして検証した。
>
> **★ステータス: Track A 完了（2026-06-19）** — テーマ層の3フィルタを実装・実データ検証済み。
> golden 18/18 死守・pytest 106 passed。**Track B（取得層・①ghost利回り）は別GO待ち**。
>
> 関連: 本書は [[10-theme-layer-calibration]] の続き。doc10 が high_yield_safe 等へ較正思想を
> 波及させたのに対し、本書 doc12 は**doc10 が未カバーだった生利回り系テーマ**
> （high_yield / low_pbr_yield / small_value / value_quality / div_growth）の罠を潰す。

## 1. 4指摘の検証結論（実データ裏取り済み）

| # | 指摘 | 判定 | 真の原因（実データ） | 層 |
|---|---|---|---|---|
| ① | サンウェルズ9229 ghost利回り9.7% | 実在・最重要 | annual_div=14（FY2024実績）を暴落後株価で除算した幽霊利回り。**無配転落の予想配当が dividend_annual に未取得**。鮮度ゲート3年は未発火（FY2024→価格2026でgap=2）。roe=−10.7%（赤字） | **取得層(Track B)** |
| ② | 千趣会8165 偽ROE23% | 実在 | 営業益率**−6.2%（本業4年連続赤字）**＋純益は特益リバウンド＋自己資本**332億→170億（4年で半減）**。ROE=特益÷半減自己資本の罠。equity比率65%は健全＝Geminiの「すり減り」表現は不正確だが**絶対額は半減**で罠は実在 | テーマ層 |
| ③ | バリューコマース2491/ヘリオステクノ6927 タコ足217%/227% | 実在 | high_yield #2/#3・low_pbr_yield #2 等に実在。payout>100%・rel=0.0・cyclical。grade は doc11 で既にC表示だが順位は利回り降順で上位＝ミスリード | テーマ層 |
| ④ | シェアリング3989 YoC22.5%・連続増配0年 | 実在 | div_growth #3。YoC計算自体は正しい（5年前=無配低位株→復配ジャンプ）。質係数が quality=None→×1.0素通り。div_growth上位は富山第一銀行(#1)等の低基底回復で占有 | テーマ層 |

**Geminiの精度**: doc10（doc11レビュー時）は原因診断に誤りが混じったが、今回は症状・修正提案ともほぼ正確。
褒めている large_cap・doe_king は実データと一致＝対応不要。

## 2. 根本原因 — doc10 が未カバーだった「生利回り系テーマ」

doc10 は high_yield_**safe** / growth_room / doe_king / roic_spread / fcf_coverage / div_growth(ソート)
に較正を波及させたが、**生の利回り・割安でランキングする以下のテーマは未較正のまま残っていた**:
- `high_yield` / `low_pbr_yield` / `small_value`（利回り降順）← タコ足が混入
- `value_quality`（ROE降順）← 本業赤字×特益ROEが混入
- `div_growth`（YoC×質係数）← 連続増配0年の復配ジャンプが混入（質係数の取りこぼし）

新種バグではなく、doc10と同型の「採点思想がテーマ層に未波及」。修正は既存原則の延長＝設計リスク低。

## 3. Track A — テーマ層較正（実装済み・`findex/post/themes.py`）

### ③ タコ足ゾンビ除外（共有述語 `_is_takoashi`）
- 定義: **payout>100%（利益超の配当）かつ rel<0.6（減配常習・または未確証None）**。
  - 「貯金を切り崩した一過性高配当」で翌期大減配の蓋然性が高い＝高配当ランキングの罠。
  - **payout>100%でも rel が高い実績株は除外しない**（一時的減益とみなす。アイティメディア
    gradeA/rel1.0 等の誤殺回避）。単純な payout>100% 一律除外は健全株を巻き込むため棄却。
- 適用: `high_yield` / `low_pbr_yield` / `small_value` の eligible に `not _is_takoashi(r)`。
- 効果（実測 top10）: 2491・6927 を外科的に除去。繰上りは 4820(rel1.0/gA)・2296 伊藤ハム米久
  (rel1.0/gA) 等で質が向上。定数 `TAKOASHI_MIN_PAYOUT=1.0` / `TAKOASHI_MAX_REL=0.6`。

### ② value_quality に営業益率ゲート
- `operating_margin > 0` を要求。本業赤字なのに特益でROEがspikeする罠（千趣会）を除外。
  grade_health A/B だけでは ROE の質を担保できない。
- 効果（実測 top10）: 千趣会8165 の1件のみ除外（巻き込み最小）。

### ④ div_growth に連続増配ゲート
- `g_years >= 3` を要求。「増配で育った利回り」の看板に対し、連続増配0年の復配ジャンプ
  （シェアリングテクノロジー）を除外。
- 影響調査: eligible上位の g_years 分布は {0:5, 2:1, 3:7, 4:8, 5:17…}＝1-2年がほぼ不在。
  よって **≥1 と ≥3 は top10 が同一**（どちらも g=0 の2社 3989・9827 のみ除外）。
  概念整合で明快な ≥3 を採用（優良名を1社も失わない）。

### 検収
pytest **106 passed**（`_is_takoashi` + 生利回り系3テーマの除外テスト +2）/ verify --all
**golden 18/18 不整合0** / post-gallery 再生成で4銘柄の消失を確認。

## 4. Track B — 取得層（①ghost利回り・別GO待ち）

①サンウェルズ型の幽霊利回りは derive層では安全に直せない（DEVLOG既知の残課題）:
- **根治＝予想配当/当年無配の捕捉**。J-Quants `/fins/dividend` の予想DPS、または yfinance forward を
  取得し、**当年無配（予想DPS=0/未定）なら div_yield を stale/suspect 化**。
- 全銘柄fetchを伴うため[[00-charter-and-data-integrity]]のレート制限鉄則に従う（コホート先行）。
- 鮮度ゲート `DIVIDEND_RECENCY_YEARS=3` を締める案は決算ラグの正常22銘柄を誤検知＝不可。
