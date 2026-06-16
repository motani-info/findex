# findex 開発ルール（最優先・毎回読む）

このファイルは毎セッション自動で文脈に入る。**データ取得を書く/回す前に必ずここを読む。**

## 🚨 データ取得の鉄則（レート制限＝このプロジェクト最大の運用ハードル）

過去に何度も踏んだ罠。**「実データで動いた」と「スケールで安全」は別物**。

1. **小サンプルの成功を、スケール安全の証拠にしない。**
   レート制限・IPブロックは「量で発火」する障害。5〜数十銘柄の成功は3,734銘柄の挙動を
   一切保証しない。「数件叩いて動いたから全件いける」は禁止。**これが過去の事故の根因**
   （2026-06-16: yfinance/Yahoo!JP を5件テストで「安全」と断定し全件起動→IPブロックで
   1000件超失敗）。

2. **yfinance / Yahoo!JP(finance.yahoo.co.jp) は高頻度で 429/5xx ブロックを返す（既知事実）。**
   Yahoo!JPプロフィールは ~100件で 500 のブロックページ。yfinance も持続的高レートで
   `Too Many Requests`。**全銘柄取得は当たる前提で設計する**（当たらない前提で組まない）。

3. **全銘柄スキャンは「監視下の1回だけの実験」。fire-and-forget しない。**
   保守レート（件/分を低く）から始め、`findex progress` で監視し、必要なら上げる。
   設計が固まり golden/コホートが通ってから（docs/requirements.md「検証は30社コホートで回す」）。

4. **開発・反復は常に `--cohort`（約35社）。** 全銘柄は最後に1回。
   `data/verification_cohort.csv`。golden=`data/golden_streaks_zai_20260601.csv`。

5. **取得は必ず `RateLimitedFetcher`(findex/fetch/base.py) 経由。** 単発 requests を直に書かない。
   既に備わっている前提＝バックオフ／チェックポイント・resume／完全性ゲート(is_complete)／
   サーキットブレーカー(max_consecutive_failures)。**この防御インフラが在ること自体が
   「レート制限は既知の中心リスク」という前提の証拠**。新コードもこれに乗せる。

6. **背景実行は進捗を逐次ファイル出力し、`findex progress` で確認する**（AIにポーリングさせない）。
   ログは `~/.findex/logs/`。

> 前提条件の学習手順: 新しい取得を書く前に①このCLAUDE.md ②docs/requirements.md「レート制限」
> ③docs/PROJECT-LOG.md ④既存fetcherの防御構造 ⑤データ源の周知の挙動、を棚卸しする。
> 既存の防御コードと運用ルールは「破ってはならない前提」として扱う。

## 品質の鉄則（定款由来）

- **確証(status=ok)のない数字は出さない。** 連続年数の打ち切りは「N年以上」（裸の数字で言い切らない）。
- 出典・as_of を明示。claim別グレードを混同しない。免責必須。
- naive実装は罠を踏む。**実データが神**（記憶: 実データ検証フィードバック）。

## 現在地・経緯

- 進捗ダッシュボード: `docs/html/progress.html`（正本は `docs/PROGRESS.md`）。
- ノーススター: `docs/design/00-charter-and-data-integrity.md`。
- いまの局面: 基盤整備F1-F5完了 → **Part2 全データ洗替**を実行中（listing→prices→financials→
  dividends→derive→score→verify）。出力本番化は凍結（コホート規模では本番化不可のユーザー判断）。

## よく使うコマンド

```bash
uv run findex <cmd> --cohort        # 開発・検証は常にコホート
uv run findex progress [name]       # 背景取得の進捗（実行中/停止・%・ETA・最新エラー）
uv run findex verify --cohort       # 洗替の検収（カバレッジ/golden/seam穴/status）
uv run pytest -q                    # テスト
```
