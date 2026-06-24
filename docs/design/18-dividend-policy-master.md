# 18 - 配当方針マスターの取り込み（A=生テキスト保持 ＋ B=構造化シグナル）

> 起点: ユーザー要望「配当方針をマスターデータとして追加したい」（2026-06-24）。
> findex は **配当性向（payout_ratio）は既に導出済**（`computed_metrics.payout_ratio` = DPS/EPS・
> [[04-indicator-system]]）。本書が扱うのは別物の **配当方針**（会社が開示する配当の基本方針テキスト）。
>
> **★ステータス: 実装＋全銘柄(--all)取得＋スケール是正＋柱3テーマ化 完了（2026-06-24）。A=全件・B=偽陽性一掃済み。**
> 取得: 全3734社処理（policy_text 3525社 verbatim・残は政策ブロック不在＝missing）。golden 18/18 不整合0。pytest 149 passed。
> **柱3反映（§6実装済）**: `fetch_rows` に方針シグナル(progressive/stable/payout_target/doe_target/total_payout_target)を
> 露出（目標%は%数値格納→/100で小数化し既存pct描画と単位統一）。新テーマ **`progressive`（累進配当宣言の高配当株）**
> ＝会社が有報で「減配せず維持か増配」を明言した社(progressive_flag)×gd≠D×利回り3%・利回り降順。固有列に
> 「配当性向目標」を出しコアの実績「配当性向」と対比。eligible 126社規模・本文115字でゲート通過。回帰テスト
> `tests/test_post_themes.py::test_progressive_requires_declared_policy`。
> 監査ハイライト: 4452花王=payout目標 missing が正／5947リンナイ=40%目標が正／9532大阪ガス=実績配当性向28.5%・
> 実績純資産配当率2.3%・DOE目標3.0% 混在文から **DOE目標だけ** を正しく採取。
>
> **★スケール検証で判明した罠（定款「小サンプル成功≠スケール安全／naive実装は罠」の実例・要記録）**:
> cohort 35社では出ず、全3734社で**Bの偽陽性**が顕在化した。①「配当性向を加味しDOE2.5%」型＝DOE値の payout 混入、
> ②「（配当性向：100.9%）といたしました／実施することを決定／120%となります」型＝**方針語と共起する実績/確定値**、
> ③「配当性向100%以下/以内」型＝上限を目標と誤認。**A（生テキスト）は無傷**、B のみ。`policy_text` を verbatim 保持して
> いたため**新規フェッチ無しの再パース（`findex policy-reparse`）で全件是正**。パーサ強化＝実績マーカー拡充（…ました/
> …決定の確定形のみ・裸の「実施し/実施する/となる」は将来意図に当たり過剰除外なので不可）／上限「以下・以内」除外／
> 配当性向と数値の間に別指標語があれば不採用（block_between）。是正後 payout目標は 10〜100%・中央値35%、DOE中央値3.0%、
> 総還元中央値50% と分布健全化、両端も全件本物の目標。回帰テストに3型を固定（tests/test_dividend_policy.py）。
>
> 関連: データ源は [[02_5-feasibility-findings]] の EDINET。確証主義は [[00-charter-and-data-integrity]]。
> 取得の堅牢化は既存 EDINET フェッチャ（[[data-workflow]] / `fetch/edinet.py`）に相乗り。

## 1. 何を足すか — 配当性向との区別

- **配当性向（既存・導出値）**: `payout_ratio = DPS/EPS`。数値・status付き。タコ足除外等で使用中。
- **配当方針（本書・新規マスター）**: 「安定的・継続的な増配」「連結配当性向◯％を目指す」「累進配当」
  「DOE◯％目標」など、会社が有報で開示する**自由記述の方針**。数値ではなくテキストが一次データ。

土台原則（[[00-charter-and-data-integrity]]）: **正確でないデータは有害**。方針は自由記述なので、
原文の verbatim 保持（A）と、そこから数値/フラグを起こす構造化（B）を**層として分離**する。
B は捏造リスクが高く、status で「確証あり」だけを ok にする。

## 2. データ源 — 既DL済みレコード内（新規フェッチなし）＝鉄則適合

EDINET 有報 XBRL の **`jpcrp_cor:DividendPolicyTextBlock`（項目名「配当政策」）**。

### 実データ裏取り（スパイク・2026-06-24）
| 銘柄 | 基準 | 要素ID | 原文長 | 抽出 |
|---|---|---|---|---|
| 4452 花王 | IFRS | `jpcrp_cor:DividendPolicyTextBlock` | 686字 | ✅ |
| 5947 リンナイ | JGAAP | `jpcrp_cor:DividendPolicyTextBlock` | 740字 | ✅ |

- **決定的事実**: 配当政策テキストブロックは **IFRS / JGAAP で同一要素ID**。財務数値（jppfs/jpigp で
  基準別に分裂・[[02_5-feasibility-findings]]）と違い、jpcrp（企業内容開示）の**統一タグ**＝抽出が単純。
- `fetch/edinet.py:fetch_csv_records` は有報CSV(zip)を**丸ごとDL**しており、テキストブロックも既に
  レコード内に在る（`_index()` が `float()` できる数値だけ拾い**テキストを捨てている**だけ）。
  → 財務取得と**同じ書類を再利用**できる＝**新規ネットワーク負荷ゼロ**（鉄則: レート制限＝最大の運用ハードル）。
- US GAAP連結は構造化XBRL不在（[[02_5-feasibility-findings]]）→ 配当政策テキストも無い社は `missing`。

## 3. 設計 — A（生テキスト）／B（構造化）

### スキーマ: 新テーブル `dividend_policy`
責務別テーブルの流儀（dividend_events / dividend_annual / dividend_forecast）に倣う。キー `(code, fiscal_year)`。

| 列 | 内容 | 層 |
|---|---|---|
| `code`, `fiscal_year` | キー | — |
| `policy_text` | 配当政策の verbatim 原文 | A |
| `progressive_flag` | 累進配当（INTEGER 0/1） | B |
| `stable_flag` | 安定配当/安定的還元 | B |
| `payout_target_pct` | 配当性向**目標**% | B |
| `doe_target_pct` | DOE**目標**% | B |
| `total_payout_target_pct` | 総還元性向**目標**% | B |
| `signals_status` | B各シグナルの status（JSON: ok/missing） | B |
| `source` | `edinet` | 来歴 |
| `disclosed_date`, `as_of` | 開示日・決算期末 | 来歴 |
| `collected_at` | 取得時刻 | 来歴 |

### A — 生テキスト保持
`edinet.extract_dividend_policy(records)` で `DividendPolicyTextBlock` の値を verbatim 取得し
`policy_text` に格納。出典(edinet)・as_of付き。**捏造の余地なし**（reference的データ）。

### B — 構造化シグナル（保守的・status付き）
`parse_policy_signals(text)`。**実データで判明した罠を構造で回避する**:

> **★確証主義の核心（スパイクで実証）**: 配当政策テキストには配当性向の数字が出るが、多くは**実績値**
> （花王「配当性向は59.2％と**なりました**」／リンナイ「配当性向は50.1％と**なっております**」）であって
> **目標ではない**。リンナイは別文に**本物の目標**（「2025年度の連結配当性向40％を**目指し**」「総還元性向40％」）。
> 花王には**数値目標が無い**（方針は「安定的・継続的な増配」）。
> → naive な「配当性向＋N%」抽出は、花王で59.2%を目標と誤認、リンナイで実績50.1%と目標40%を取り違える。

パーサ規則:
- **目標%抽出は目標文脈とのみ共起時に採る**: 近傍に `目標 / 目指す / 方針として / 維持 / 以上` 等の
  目標マーカーがあり、かつ実績マーカー（`となりました / となっており / となった / 実施`）に紐づかない場合だけ ok。
  曖昧・不在は **`missing`**（捏造しない）。実績%は**拾わない**（実績は導出の payout_ratio が持つ）。
- **累進/安定はリテラル検出**: `累進配当` の文字列がある → progressive ok。`安定的` `安定した` → stable ok。
  言い換え（花王「安定的・継続的な増配」）からの**推測昇格はしない**（初版は保守）。
- 1テキストに複数年・複数値が混在するので、目標は「方針文」側に限定し、決議明細表（決議年月日…円）は除外。

## 4. 取得・配線

- `edinet.extract_dividend_policy` / `parse_policy_signals` を新規追加（純関数＝単体テスト可能）。
- financials フェッチャ（`fetch/financials.py` の EDINET 経路）に相乗り: 既に取得した `records` から
  policy も抽出して `dividend_policy` へ per-stock commit（[[data-workflow]] の F1 完全性ゲート準拠・
  resume安全）。**同一書類の再利用で新規フェッチなし**。
- CLI: 既存 financials 取得に内包（独立コマンドは検証時のみ `--what` 等で）。

## 5. 検証（コホート・鉄則どおり・全銘柄展開の前提ゲート）

- **約35社で原文＋抽出シグナルを目視**。合格条件:
  1. `policy_text` が全社 verbatim（文字化け/欠落なし）。
  2. **実績%を目標と誤認した行 = 0**（花王 payout_target=missing が正・リンナイ payout_target=40 が正）。
  3. **無い目標を捏造した行 = 0**。
- パーサ単体テスト: コホート原文を fixture 化し、目標/実績の弁別・累進/安定検出を回帰テスト化。
- **golden 18/18 不整合0 を維持**（既存系列は無傷＝新テーブルのみ追加）。
- 合格するまで `--all` は実行しない（鉄則: 全銘柄スキャンは監視下で1回）。

## 6. 利用（柱2/柱3）— 検証後

- `fetch_rows` へ露出 → テーマ層。**「累進配当」は柱3のXテーマに強い**（[[15-eight-axis-standard-all-themes]] の
  8軸併記に方針を1行添える等）。
- 安全性ゲートの補強: 高配当 × payout_target が明示 × 累進フラグ ＝「方針として続ける意思」を裏取り。
  ただし方針は**意思表明であって保証ではない**＝免責は維持（[[00-charter-and-data-integrity]]）。

## 7. 残・運用

- **全銘柄反映**: 検証合格後、financials --all の相乗りで取得（新規ネットワークなし）→ derive/score/verify。
- **B の段階拡張**（将来）: 言い換えからの累進判定、中計の還元方針期間（◯年度〜◯年度）の構造化等。
  初版は「確証できる明示シグナルだけ ok・他は missing」を死守する。
