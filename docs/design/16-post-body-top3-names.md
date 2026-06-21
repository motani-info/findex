# 16 - 投稿本文へトップ3社＋看板指標を注入（引きを強める）

> 起点: ユーザーが posts.html を実運用で手直しして投稿する際、「本文に企業名が無いと引きが弱い」と
> 判断。ROIC−WACC テーマを手動で「社名＋利回り」入りに改稿した例を提示し、全テーマへ横展開を依頼。
>
> 関連: [[15-eight-axis-standard-all-themes]] [[14-sort-honesty-and-net-cash-floor]]

## 1. 背景・課題

従来の投稿本文（`body_fn`）は**フック2行＋#タグのみで企業名ゼロ**。数字・銘柄は画像カードに寄せる
設計だったが、タイムライン上で画像を開かせる前の「引き」が弱い。ユーザー手直し例:

```
資本コストを超えて稼げているか。
価値創造(ROIC−WACC)ランキング🚀 トップ5
本当の意味で儲かる会社。
🥇 ZOZO 3.6% / 🥈 サイボウズ 1.7% / 🥉 JAC 4.2%
#ROIC #バリュー株
```

## 2. 方針（ユーザー決定 = パターンP2「社名＋看板指標」）

4パターン（社名＋利回り／社名＋看板指標／冒頭社名＋問いかけ／コンパクト1行）を実データで提示し、
ユーザーは **P2「社名＋看板指標」** を選択。

- 社名横に出す数字は **そのテーマのランキングを決めた指標（sort_key 由来）** ＝看板と数字が一致し最も誠実。
- 本文の構成: `フック1 → テーマ名ランキング トップN → トップ3社ブロック → フック2 → #タグ`。
- 社名は **半角正規化（NFKC）**（ＺＯＺＯ→ZOZO・読みやすさと字数節約）、長名は12字で末尾「…」省略。
- 投稿は最終的に手動（柱3は凍結中）ゆえ、JAC のような略称化はユーザーがコピー後に手直しする前提。

## 3. 本文上限ゲートの引き上げ（140 → 250）※後に §7 で 140 に再修正

- 旧ゲート `weighted_len(body) <= 140` は X の実上限（加重 **280**＝日本語140字）の**半分**で過度に保守的。
  社名3行を入れると 140 を超える（ユーザー版は加重160）。
- `BODY_MAX = 250`（実上限280に余白）に統一。`_gates` / streak ゲート / ギャラリー表示（`/250字`）を更新。
- 全17テーマの実測: 最大 188/250（roic_spread/doe_king/net_cash）。2桁トップNでも安全。

> ⚠️ **この §3 の判断（加重250へ引き上げ）は §7（2026-06-21）で撤回**。実運用で「140文字以上は
> 投稿できない」ことが判明し、**実文字数140字**を上限に戻した。下記 §7 が現行仕様。

## 4. 実装（findex/post/themes.py）

- `_post_name(name, maxlen=12)`: NFKC 半角化＋末尾省略。
- `_body_metric(v, fmt)`: 投稿用の素テキスト整形。fmt = pct / pct_signed / year / x / num（未算出は「—」）。
- `_post_name_block(shown, headline, top=3)`: 「メダル＋半角社名＋看板指標」を改行区切りで返す
  （末尾改行込み・該当0社や headline=None は空文字＝旧フックのみへ自動フォールバック）。
- `_ranking_theme` に `headline=(key, fmt)` を追加。`shown` を body より先に作り `body_fn(n, names)` へ渡す。
  各 `_SPECS` の `body_fn` を `lambda n, names:` 化し、テーマ名行の直後へ `{names}` を差し込み＋`headline` 追加。
- カスタムビルダー5本（streak/high_yield_safe/div_growth/value_quality/net_cash）も `shown` を body 前に
  作り `_post_name_block` を注入。`_streak_body(n, names="")` 化。

### テーマ別 headline（= sort_key の指標）

| テーマ | headline | テーマ | headline |
|---|---|---|---|
| streak | 連続増配 年数 | high_yield | 利回り % |
| no_cut | 連続非減配 年数 | low_pbr_yield | 利回り % |
| long_growth | 連続増配 年数 | large_cap | 利回り %（注） |
| growth_room | 配当性向 % | small_value | 利回り % |
| fcf_coverage | FCFカバ 倍 | roic_spread | ROIC−WACC ±% |
| high_roe_growth | ROE % | doe_king | DOE % |
| total_score | 総合スコア num | div_growth | YoC % |
| high_yield_safe | 利回り % | value_quality | ROE % |
| net_cash | 実質PER 倍 | | |

（注）large_cap は並びこそ総合スコア降順だが、看板「配当」の引きとして社名横は利回りを添える。

## 5. 検証

- pytest **118 passed**（新規5: `_post_name` 正規化/`_body_metric` 整形/`_post_name_block` メダル行/
  全 `_SPECS` body_fn が names 注入＆BODY_MAX 以内/`_streak_body` names 注入）。
- `verify --all` golden **18/18 不整合0**。
- `post-gallery --all`: 17テーマ再生成、全本文にトップ3社＋看板指標を確認（最大188/250字・全ゲート通過）。

## 6. 追補（2026-06-21）: 配当利回りの必須併記（POSTルール）

> 起点: ユーザー指示「全体のPOST文章のルールとして必ず配当利回りは書く」。
> 例: DOEテーマでも `🥇ユー・エス・エス 配当3.0% DOE13.6%` のように利回りを併記する。

### ルール（全テーマ共通・恒久）

**投稿本文のトップ3社行には、配当利回りを必ず併記する。** findex の看板は配当株スクリーニングであり、
どのテーマ（DOE・ROIC−WACC・EPS成長など利回り以外が看板の軸でも）でも読者が最初に知りたいのは
「で、利回りは何%か」。看板指標だけだと利回りが画像を開くまで分からず引きが弱い。

### 形式

- 社名横は **`配当X%` を常時先頭に併記** ＋ 看板指標（§4の headline）を短ラベル付きで続ける。
  - 例（看板＝DOE）: `🥇ユー・エス・エス 配当3.0% DOE13.6%`
- **看板が配当利回りそのもの**（key=="dy" の high_yield / low_pbr_yield / small_value / large_cap /
  high_yield_safe）は重複させず **`配当X%` のみ**。
- **利回り未確証（dy=None）は `配当—`** と正直に表示（定款「確証なき数字は出さない」＝裸の0や捏造をしない）。

### 実装（findex/post/themes.py）

- `_post_name_block` を改修: 各社行を `{メダル}{社名} 配当{dy}% {ラベル}{看板値}` で組む（key=="dy" は `配当{dy}%` のみ）。
- `_HEADLINE_LABEL`（新規 dict）: 看板キー→短ラベル。
  `DOE / YoC / ROE / 実質PER(net_cash_per) / EPS成長(eps_growth_5y) / 非減配(nc_years) / 増配(g_years) /`
  `性向(payout_ratio) / FCFカバ(fcf_payout_coverage) / 総合(total) / ROIC−WACC(roic_minus_wacc)`。
- タラレバ3本（future_dividend / road_to_3man / dividend_doubling）は `_post_name_block` 非経由（本文は
  TOP1社の前提付き試算の独自の語り）＝対象外。画像は base_theme のランキング表を流用するため利回り列は元々載る。

### 検証

- pytest **119 passed**（`test_post_name_block_builds_medal_lines` を新フォーマット＝DOE併記例へ更新。
  key=="dy" 重複なし／dy=None→`配当—` のケースを追加）。
- 全17テーマ本文 **≤250字**（最長 roic_spread 244／配当併記で各行+約9加重字だが余白内）。
- `post-gallery --cohort`=20テーマ通過／`verify --all` golden **18/18 不整合0**。
- コミット `ae66a35`。関連: [[12-theme-layer-trap-filters]]（同日の武田型トラップ拡張）。

## 7. 追補（2026-06-21）: 本文上限を実文字数140字へ再修正（§3の撤回）

> 起点: ユーザー指摘「**140文字以上は投稿できない**（全POSTの制約）」。§3で加重250へ上げたが、
> 実運用ではこれを超えると投稿できなかった。バッジ `236/250字` の「236」は加重値（CJK×2）で、
> ユーザーには「236字＝140超」と映り混乱の元でもあった。

### 仕様（現行・恒久）

- 上限判定は **実文字数（改行含む）≤ 140**。新ヘルパー `post_len(s)=len(s)`、`BODY_MAX = 140`。
  ゲート（`_gates` / streak インラインゲート）・ギャラリーのバッジ（`{body_len}/140字`）を実文字数へ統一。
- **なぜ実文字数140が安全か**: 実文字140以内なら最悪（全角のみ）でも X 加重 280（無料枠上限）に収まり、
  数字・ASCII 混在ならさらに余裕＝**実140字以内なら必ず投稿可能**。`weighted_len` は監査用の参考値に降格。

### §6（配当併記）と両立させるための本文短縮

配当併記で各行が約9字増え、トップ3社＋2フックでは140を超えるテーマが出た。フック文を整理して全テーマを
140以内へ収めた:
- 締めの第2フックを削除: div_growth / net_cash / value_quality / fcf_coverage / doe_king / roic_spread /
  nisa_growth、タラレバ future_dividend・road_to_3man の結びの一文。
- `nisa_growth` のテーマ名行を短縮（`NISA永久ホールド・EPS成長…`→`NISA・EPS成長ランキング`）。
- **`roic_minus_wacc` の行ラベルを削除**（`_HEADLINE_LABEL` から除外＝値のみ `配当3.6% ＋34.3%`）。
  ラベル「ROIC−WACC」は9字でテーマ名「価値創造(ROIC−WACC)」に既出＝冗長。ROIC と誤表記はしない
  （定款の数字整合）。ラベル未定義キーは値のみ表示する一般則に整理。

### 検証

- pytest **119 passed**（長さ系テストを `post_len`＋`BODY_MAX`(140) 基準へ更新）。
- 全テーマ本文 **≤140字**（`--cohort`/`--all` 両方で確認・最長140）。
- `post-gallery --cohort`=20テーマ通過／`verify --all` golden **18/18 不整合0**。
- 注: doc05（投稿戦略）の「140字」記述は本修正で再び現行仕様と一致。
