# 13 - J-Quants確定無配の取り込み（ghost利回りの根治・Track B）

> 起点: doc12 ①サンウェルズ9229 の ghost利回り9.7%。doc12 はテーマ層（Track A）で②③④を是正したが、
> ①は**取得層**課題として残した（Track B）。本書はその根治。
>
> **★ステータス: 実装＋コホート検証 完了（2026-06-19）。全銘柄(--all)反映は運用ジョブで実行。**
>
> 関連: [[12-theme-layer-trap-filters]] の Track B。データ源は [[02_5-feasibility-findings]] の J-Quants。

## 1. 根本原因（精密化）

ghost利回り＝「無配転落したのに直近の有配DPSを暴落株価で割り続ける」幽霊。真因は取得層の構造欠陥:

- `dividend_annual` は **yfinance の実支払い（過去ex-date）だけ**で構築（`fetch/dividends.py`）。
- yfinance は「**無配＝ex-dateイベント無し**」のため、**構造的に無配年の行を立てられない**。
- 結果、無配転落後も dividend_annual の最新が直近の有配年に固定される（サンウェルズ FY2024=14）。
- 鮮度ゲート `DIVIDEND_RECENCY_YEARS=3` は「最新配当年と株価年の差」で見るため未発火
  （FY2024→価格2026でgap=2）。→ `div_yield = 14/暴落株価 = 9.7%`（status=ok）。

### 実データの裏取り（9229 の J-Quants `/fins/summary`）
| 会計年度 | 種別 | DivAnn | 備考 |
|---|---|---|---|
| FY2024 | FY実績 | 14.0 | dividend_annual に既存（events） |
| FY2025 | **FY実績** | **0.0** | **無配確定が開示済**（yfinanceには行が無い） |
| FY2026 | 予想 | FDivAnn 0.0 | 予想（本実装では未使用） |

## 2. 設計 — 「yfinanceが出せない無配年だけ」を J-Quants から補完

- データ源は**既配線**: `JQuantsClient.fins_summary` は財務取得で毎回叩いており、同じレスポンスに
  `DivAnn`（確定年間配当・0.0=無配含む）が入っている（従来パーサが捨てていた）。新認証・新EP不要。
- パーサ `parse_fy_dividends`（`fetch/jquants.py`）: FY実績レコードの `DivAnn` を年度別に抽出。
  予想（FDivAnn/NxFDivAnn）は採らない＝確定実績のみ。空文字（未開示）は None で除外。
  会計年度キーは `parse_fy_records` と同じ「決算期末年」で整合。
- ビルダー `_JQuantsDividendBuilder` / `build_jquants_dividends`（`fetch/dividends.py`）:
  **fill-absent-無配-only**＝確定無配(0.0)で**既存行が無い年だけ** source=`jquants` で挿入。
  既存系列（events/override/haitoukin/manual/ir）は一切上書きしない＝**golden保護を構造で担保**。
  非ゼロの鮮度補完は対象外（有配年は yfinance が出せるため不要・系列改変リスクを避ける）。
- derive側は**変更不要**: 最新DPS=0.0 → 既存の `div_yield: dps==0 → zero_legit`（利回り非表示）に
  自然に乗る。`_latest_dps` が最大FYのdpsを返す＝無配年が最新なら0.0を拾う。
- CLI: `findex dividends-jq --cohort|--codes|--all`（resume安全・per-stock commit）。

## 3. 検証（コホート・鉄則どおり）

- 9229単体: dividend_annual に FY2025=0.0(jquants) 補完 → derive後 `div_yield=0.0/zero_legit` →
  high_yield/low_pbr_yield/small_value の top10 から消失。
- コホート35社: 補完は **3行/3社（4385メルカリ・7201日産・9229サンウェルズ＝いずれも実無配）** のみ。
  **golden 18/18 不整合0 維持**（正系列無傷）。pytest 108 passed。

## 4. 残・運用

- **全銘柄反映**: `dividends-jq --all` → `derive --all` → `score --all` → `post-gallery --all`。
  J-Quants 1コール/銘柄＝背景 nohup ジョブ（鉄則: 全銘柄スキャンは監視下で1回・`findex progress` で監視）。
- **将来オプション**: `FDivAnn`（当年予想）の捕捉でFY確定前の無配転落も早期検知。本実装は確定実績のみ。
