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

## 3. 本文上限ゲートの引き上げ（140 → 250）

- 旧ゲート `weighted_len(body) <= 140` は X の実上限（加重 **280**＝日本語140字）の**半分**で過度に保守的。
  社名3行を入れると 140 を超える（ユーザー版は加重160）。
- `BODY_MAX = 250`（実上限280に余白）に統一。`_gates` / streak ゲート / ギャラリー表示（`/250字`）を更新。
- 全17テーマの実測: 最大 188/250（roic_spread/doe_king/net_cash）。2桁トップNでも安全。

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
