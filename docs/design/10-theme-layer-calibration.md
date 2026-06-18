# 10 - 投稿テーマ層への較正波及（v4較正＋doc09をテーマ層へ）

> 起点: 2026-06-17（夜）、外部レビュー（Gemini）が `docs/html/posts.html` 全17テーマを
> 検証し「重大バグ多数」と報告。実コード（themes.py / compute.py / report.py）と設計書
> （[[00-charter-and-data-integrity]] / [[04_5-indicator-calibration]] / [[02_7-result-override-layer]] /
> [[05-x-posting-strategy]] / [[09-scale-data-quality-remediation]]）を照合して検証した。
>
> **★ステータス: 完了（2026-06-18）** — P1（テーマ層較正3件）・P2（DOEサニティ＋分母崩壊/
> 金融除外）・P3-1（数理不変条件 nc>=g の表示担保）を実装・実データ検証済み。
> golden 18/18 死守・pytest 94 passed。コミット: P1=`b7dd135` / P2=`c23c5d1` / P3-1=`2b319ef`。
>
> 関連: 本書は [[09-scale-data-quality-remediation]] の続き。doc09 は derive層（採点/status）の
> スケール是正、本書 doc10 は**その品質思想を投稿テーマ層（themes.py）へ波及**させる。

## 1. 根本原因 — 「レイヤのズレ」

findex は品質を2段で固めてきた:
- **採点 / derive層**: v4較正（[[04_5-indicator-calibration]]）＋ スケール是正（doc09）で
  失敗モードを潰し済み。
- **投稿テーマ層（`themes.py`）**: doc09 §4-5 の一部（`n_scored≥8` ＋ 利回りフロア `_yield_ok`）
  だけ適用され、**v4較正の思想が未波及**。

→ Gemini が見つけた問題＝**採点層では解決済みの欠陥が投稿ランキング層に持ち越されている**
構造。新種バグではなく、findex 自身の設計書が既に認識・解決済みの失敗モードがテーマ層に
降りていないだけ。修正は既存原則の延長＝設計リスク低。

### 指摘ごとの判定（設計書ベース・調査結論）

| 指摘 | 判定 | 設計書の根拠／正しい原因 |
|---|---|---|
| div_growth が増配率CAGRでランキング | ✅問題 | [[04_5-indicator-calibration]] 較正①が **CAGRを採点から廃止し YoC＋質ゲートに置換済み**（低ベース/一過性を過大評価＝イクヨ66x/日鉄36x）。テーマは廃止済み生CAGRを使用＝設計違反 |
| high_yield_safe の安全性が形骸化 | ✅問題 | [[05-x-posting-strategy]] 差別化テーゼ「増配率に騙されない／その配当は続くのか・罠か」。eligible が `rel is not None` の存在チェックのみ＋sortは利回り降順＝**安全性の実フィルタ未実装** |
| doe_king に DOE>100% | ✅問題 | DOE=配当÷自己資本ゆえ「自己資本が安定」が前提。ミンカブ（自己資本比率3.2%）は分母崩壊＝doc09が `\|roe\|≤100%` で潰した型と同型。**DOEはv4で後追加のため doc09サニティ対象外**＝取りこぼし |
| roic_spread に ROE=— の銘柄 | ✅問題 | ROIC−WACC も分母崩壊系。eligible が `roic_minus_wacc>0` のみで財務健全性（ROE算出可能性）を要求せず |
| fcf_coverage が銀行独占 | ✅問題 | [[04_5-indicator-calibration]] 較正③が sector33 で業種構造差を扱う＝設計は業種を意識。CF系で金融除外が未実装 |
| 連続増配 > 連続非減配 の逆転 | ⚠️表示の正直性 | [[02_7-result-override-layer]]: override は「昇格のみ・claim単位」が設計。連続増配のみ ZAi override、非減配は自前計算＝設計どおり。数理不変条件（nc≥g）が併示で破れて**見える**だけ。「N年以上」化で解消 |
| UTグループ PER0.8/PBR0.24 | ❓要データ確認 | 設計書に記載なし。fetch/derive層の株数基準ミスマッチ（データ問題）＝**本書スコープ外**・後送り |

### 鵜呑みにしない点（外部FBの誤診）
- Gemini の「原因診断」は2件誤り: ① div_growth の一致を「株式分割バグ」とした→実は ZAi override／
  ② 「ハードコードcap」とした→実は低基底復配CAGR。**Gemini の推測した修正方法には従わない**。
- 65% サニティ閾値（doc09 §4）は素案50%→65% にユーザーが意図的に緩めた較正。締めるなら再度
  ユーザー判断が必要（本書では触らない）。

## 2. 対応方針

**「v4較正の思想を投稿テーマ層へ波及させる」**。原則は doc09 と同じ＝可能な限り上流（derive層）の
単一ゲートで直し、テーマ層は eligibility / sort の宣言的修正に留める。derive層に属する是正
（DOEサニティ）は `compute.py` に置き、表示の正直性に属する是正（nc≥g）は表示層に置く。

## 3. 実施内容（P1〜P3）

### P1 — テーマ層較正3件（採点層の思想を eligibility / sort へ）コミット `b7dd135`

| # | テーマ | 修正 | 根拠 |
|---|---|---|---|
| P1-1 | div_growth | 生CAGR順位を廃止し **YoC × 増配の質係数** でソート（`_yoc_quality_key`）。質係数は採点層 `score/engine.py` の `_QUALITY_FACTOR` を**共有＝単一実装**（sound×1.0 / payout_driven×0.5 / cyclical×0.3） | [[04_5-indicator-calibration]] 較正①。一過性（YoC34%/cyclical）を軟減点し持続的増配を上位へ。実装後トップ5が全てEPS牽引に |
| P1-2 | high_yield_safe | 安全フィルタ `_hy_safe_eligible`: 減配信頼性 `rel>=0.6`（減配1回以内）＋ 配当性向 `0<payout<=1.0`（利益で配当を賄える）。透明性のため**配当性向列を追加** | [[05-x-posting-strategy]] 差別化テーゼ。バリューコマース型（rel0.0/性向217%）を排除 |
| P1-3 | growth_room | eligible に `fcf_payout_coverage>0` を追加 | 低配当性向「だけ」では増配余力を担保できない（薄利益/赤字でも性向は低く出る）。現金で配当を賄える裏付けを要求 |

### P2 — 分母崩壊・金融除外（doc09踏襲）コミット `c23c5d1`

| # | 対象 | 修正 | 根拠 |
|---|---|---|---|
| P2-1 | compute.py（derive層） | `SANITY_MAX_DOE=0.6` サニティゲート新設。範囲外を `suspect` 化 | doc09 の単一ゲート原則。DOEはv4後追加で doc09サニティ対象外だった取りこぼし。**ユーザー合意0.6**（実測 DOE p99=20.5%、ZOZO35.6%は保持、薄資本/特配の7社=DOE>60%を除外）。`derive --all` 再計算済み |
| P2-2 | roic_spread（themes.py） | eligible に `roe is not None` を追加 | 千代田化工（ROE算出不能）型の分母崩壊を除外。財務健全性が確証できる銘柄に限定 |
| P2-3 | report.py / themes.py | `fetch_rows` に `stocks.sector33` を追加 ＋ `_non_financial(r)` / `_FINANCIAL_SECTORS`（銀行/証券/保険/その他金融）で fcf_coverage・net_cash から金融を除外 | [[04_5-indicator-calibration]] 較正③の業種考慮。CF系の銀行独占を解消。配当/連続テーマには引き続き登場（除外はCF系2テーマのみ） |

### P3-1 — 数理不変条件 nc≥g の表示担保 コミット `2b319ef`

- **問題**: 連続増配(`g`)は ZAi公表 override（自前計算より長い確証値）になり得るが、連続
  非減配(`nc`)は自前計算（履歴≈12年）。[[02_7-result-override-layer]] の override 昇格は
  claim単位ゆえ `g` だけ伸び `nc` が短いまま残り、「増配36年 > 非減配12年」という**不可能な
  逆転**が画面に出ていた（連続増配は連続非減配の部分集合＝増配した年は必ず非減配年ゆえ
  論理的に常に `nc ≥ g`）。
- **修正**: `report.py` に `_nc_display_floor(r)` を**単一実装**。`g_src=="override"` かつ
  `g>nc` のとき、非減配の表示を「**g年以上**」（打ち切り）へ引き上げる。`nc ≥ g` は論理的
  確実性のみを述べる（[[00-charter-and-data-integrity]] の「捏造しない」に抵触しない）。
  `report.py`（`div_tr`）と `themes.py`（`_streak_td` の nc セル）で共用。
- **実データ効果**: override逆転15社該当。花王（増配36/非減配12→「36年以上」）・小林製薬
  （26/8）・パンパシ（22/0）・ユニチャーム（24/10）等。posts.html 再生成で花王「36年以上」を
  目視確認。

## 4. 変更ファイル（P1〜P3 累積）
- `findex/post/themes.py` — `_yoc_quality_key`（P1-1）/ `_hy_safe_eligible`・配当性向列（P1-2）/
  growth_room eligible（P1-3）/ roic_spread eligible（P2-2）/ `_non_financial`・`_FINANCIAL_SECTORS`（P2-3）/
  `_streak_td` の nc セルを `_nc_display_floor` 経由に（P3-1）
- `findex/post/report.py` — `fetch_rows` に sector33（P2-3）/ `_nc_display_floor` 新設＋`div_tr` 適用（P3-1）
- `findex/derive/compute.py` — `SANITY_MAX_DOE=0.6` サニティゲート（P2-1）
- `findex/score/engine.py` — `_QUALITY_FACTOR` を P1-1 のソートキーと共有（単一実装）
- `tests/test_post_themes.py` — P1〜P3 の回帰テスト（+10件）

## 5. 検収結果
- **回帰**: `pytest` **94 passed**（doc09時点 77 → P1/P2 で 90 → P3-1 で 94）。
  `verify --all` golden 検査18・一致18・**不整合0**（死守）。
- **div_growth**: トップ5が全てEPS牽引（一過性が沈む）。
- **high_yield_safe**: 罠（rel0.0/性向>100%）消滅。配当性向列で透明化。
- **doe_king**: 分母崩壊（DOE>60%）7社を suspect 化。健全DOE降順に。
- **fcf_coverage / net_cash**: 金融除外で銀行独占を解消。
- **roic_spread**: ROE算出済みのみ＝ROE値あり。
- **streak / long_growth / no_cut / high_yield_safe**: override逆転が「N年以上」化。花王 連続増配
  「36年」/ 連続非減配「36年以上」（不可能な逆転を解消）。

## 6. 残・後送り
- **UTグループ型（PER/PBRが異常に低い）への低値側サニティ**: fetch/derive層の株数基準
  ミスマッチ（データ基盤の問題）＝本書スコープ外。net_cash に 2146（PER0.8）として残存。
  別途 fetch/derive 側で対応する。
- doc09 §4 の 65% CAGR サニティ閾値は据え置き（締めるならユーザー判断）。
