#!/bin/bash
# findex 日次パイプライン
# 株価更新 → compute → score（fetch quarterlyは四半期のみ）
set -e

FINDEX="/Users/motani/Develop/github/findex/.venv/bin/findex"
LOG="/tmp/findex_daily_$(date +%Y%m%d).log"

echo "=== findex daily $(date) ===" >> "$LOG"

# 日次株価更新（既存コマンド）
"$FINDEX" update >> "$LOG" 2>&1

# 新パイプライン: compute + score
"$FINDEX" pipeline --skip-fetch >> "$LOG" 2>&1

echo "=== done $(date) ===" >> "$LOG"
