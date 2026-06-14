"""findex — 日本株スコアリング・ランキングツール（v2）。

レイヤ構成（一方向データフロー。後段は前段だけを読む）:
    fetch  → 取得層（外部ソース → 生テーブル）
    derive → 導出層（生テーブル → computed_metrics）
    score  → 評価層（computed_metrics + rules.yaml → スコア）
    post   → 出力層（スコア → CLI / X投稿）

設計: docs/requirements.md, docs/design/pre2000-data.md
"""

__version__ = "0.2.0"
