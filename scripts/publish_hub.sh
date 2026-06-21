#!/usr/bin/env bash
# 投稿ハブ（柱3 X発信）を再生成し、GitHub Pages（gh-pages ブランチ）へ公開する。
#
# 公開URL: https://motani-info.github.io/findex/
# 方式: 本リポ findex を public 化済みのため、別リポを作らず gh-pages ブランチ
#       （生成物のみのorphan系）で配信。main にはバイナリPNGを載せない。
#
# 使い方:
#   bash scripts/publish_hub.sh           # 既定 = 全銘柄(--all)
#   bash scripts/publish_hub.sh --cohort  # コホート35社で確認用
#
# 前提: gh 認証(motani-info・repo権限) が通っていること（git push は
#       ローカルの credential.helper=gh 設定経由で motani-info を使う）。
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

SCOPE="${1:---all}"
HUB="$HOME/.findex/hub"
WT="$(mktemp -d)/ghpages"

echo "── 1) ハブ生成 ($SCOPE) ─────────────────────────────"
uv run findex publish-hub "$SCOPE"

echo "── 2) gh-pages へ反映 ───────────────────────────────"
git fetch -q origin gh-pages || true
# gh-pages を origin の最新に合わせて専用worktreeへチェックアウト（無ければ新規）。
if git show-ref --verify --quiet refs/remotes/origin/gh-pages; then
  git worktree add -q -B gh-pages "$WT" origin/gh-pages
else
  git worktree add -q --detach "$WT"
  ( cd "$WT" && git checkout -q --orphan gh-pages )
fi
trap 'cd "$ROOT" 2>/dev/null; git worktree remove --force "$WT" 2>/dev/null || true; git worktree prune 2>/dev/null || true' EXIT
cd "$WT"
git rm -rqf . >/dev/null 2>&1 || true
cp "$HUB/index.html" .
cp "$HUB"/post_*.png .
touch .nojekyll
git add -A
if git diff --cached --quiet; then
  echo "変更なし（再公開不要）"; exit 0
fi
git commit -q -m "publish findex 投稿ハブ $(date '+%F %T')"
git push -q origin gh-pages
echo "✓ 公開完了 → https://motani-info.github.io/findex/"
