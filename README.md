# Findex v2

日本の全上場普通株（約3,750銘柄）を18指標・100点満点でスコアリングし、増配継続株を発掘して定期的にXへ自動投稿するCLIツール。**v2は正確性（特に2000年以前データの扱い）を最優先に再構築中。**

旧実装は `../back_findex`（計画は良質だが実装が破綻したため切り離し）。

## ドキュメント
- [docs/requirements.md](docs/requirements.md) — 要件定義書
- [docs/design/pre2000-data.md](docs/design/pre2000-data.md) — 2000年問題の解決設計（最重要）

## セットアップ
```bash
uv sync
uv run findex --help
```

## 開発の前提（レート制限対策）
全銘柄を一気に取得するとレートリミットに当たる。**検証は約30社のコホートで回す。**
```bash
uv run findex cohort              # 検証コホートを表示
uv run findex update --cohort     # コホートだけ取得
uv run findex update --codes 4452,9433
uv run pytest                     # 純粋ロジックのテスト
```

## レイヤ構成（一方向データフロー）
```
fetch  取得層   外部ソース → 生テーブル（RateLimitedFetcher: --codes/バッチ/レジューム/バックオフ）
derive 導出層   生テーブル → computed_metrics（streaks.py = ストリーク計算の正準モジュール）
score  評価層   computed_metrics + rules.yaml → スコア
post   出力層   スコア → CLI / X投稿（品質ゲート必須）
```
