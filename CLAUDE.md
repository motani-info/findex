# findex 開発ルール（毎回読む）

## このPJの目的（定款）
findex は日本株のスコアリング・ランキングツール。土台原則は
**「あらゆる上場株式の、あらゆるデータが正確に保持されていること」**。その上に3本の柱:
- **柱1 データ完全性** — 全銘柄・全フィールドの正確性が土台（旧PJはここが破綻して切り離した）
- **柱2 分析** — 進化する独自指標で多角評価
- **柱3 発信** — Xユーザーの興味を引く切り口で投稿し続ける

正本: `docs/design/00-charter-and-data-integrity.md`。現在地: `docs/PROGRESS.md`。

## 🚨 データ取得の鉄則（レート制限＝最大の運用ハードル・過去何度も事故）
1. **小サンプルの成功＝スケール安全 ではない。** レート制限/ブロックは量で発火する。
   数件動いても3,734件は別物。「数件叩けたから全件いける」は禁止。
2. **yfinance / Yahoo!JP は高頻度で 429/5xx ブロックを返す（既知事実）。** 当たる前提で組む。
3. **全銘柄スキャンは監視下で1回だけ。** 保守レートから始め `findex progress` で監視。
   開発・反復は常に `--cohort`（約35社・`data/verification_cohort.csv`）。
4. **取得は必ず `RateLimitedFetcher`(findex/fetch/base.py) 経由**＝backoff/resume/完全性ゲート/
   サーキットブレーカーに乗せる。単発 requests を直書きしない。
5. 新しい取得を書く前に前提を棚卸し: このファイル → docs/requirements.md「レート制限」→
   既存fetcherの防御構造 → データ源の周知の挙動。

## 品質の鉄則（定款由来）
- **確証(status=ok)のない数字は出さない。** 連続年数の打ち切りは「N年以上」（裸の数字で断定しない）。
- 出典・as_of を明示。claim別グレードを混同しない。免責必須。数字は全てDB由来。
- **naive実装は罠を踏む。実データで必ず検証**（小手先で通さない）。

## 📒 ドキュメント／ログの置き場ルール（毎回守る・docsとlogsを混ぜない）
継続性の仕組みは3層。役割を混ぜない。
- **`docs/`（git追跡＝確定した正本）**: `docs/design/`（設計正本）/ `docs/PROGRESS.md`（進捗ダッシュボード）/
  `docs/PROJECT-LOG.md`（フェーズ履歴・公式ログ）/ `docs/requirements.md`。
  **ここにセッション作業メモ・RESUMEスクラッチを置かない**（過去 `docs/findex-project.md` を誤って置いた→logsへ移動済み）。
- **`logs/`（git非追跡＝流動的な作業ログ）**:
  - `logs/DEVLOG.md` … セッション作業メモ／再開ポイント（やったこと・次の一手・ユーザー承認待ち）。
    最新の RESUME 節を上書き更新し、常に最新の1箇所だけ見れば再開できる状態を保つ。再開フレーズ＝「findex 再開」。
  - `logs/<job>_<timestamp>.log` … 取得ジョブの実行ログ。
- **昇格ルール**: フェーズが一区切りしたら `logs/DEVLOG.md` の確定内容を要約し、`docs/PROJECT-LOG.md` に
  1フェーズとして積む（logsは流動・docsは確定）。**logsは捨ててよい／docsは消さない。**
- **Claude自動メモリ（リポジトリ外・git管理外）**: `~/.claude/projects/-Users-motani-Develop-github-findex/memory/`。
  Claudeがセッションをまたいで思い出すための要点。docs/logsとは別物（同期しない）。

## コマンド
```bash
uv run findex <cmd> --cohort     # 開発・検証は常にコホート
uv run findex progress [name]    # 背景取得の進捗（実行中/停止/応答なし・ETA・最新エラー）
uv run findex verify --cohort    # 洗替の検収（カバレッジ/golden/seam穴/status）
uv run pytest -q                 # テスト
```
