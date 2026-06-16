#!/usr/bin/env bash
# 全データ洗替の仕上げ runbook（Part2 ⑤〜⑦）。
#
# 前提: listing/prices は完了済み。financials_build と dividends_yfinance の
#       取得が ~100% 完走している（`uv run findex progress <name>` で確認）。
#
# 本スクリプトは「取りこぼし治癒 → 導出 → 採点 → 検収」を順に流し、最後に
# golden / カバレッジ / status 穴のゲートを表示する。途中で失敗したら止まる。
#
# 使い方:  bash scripts/finish_refresh.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "════════════════════════════════════════════════════════════"
echo " 全データ洗替 仕上げ runbook  $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════════════════"

echo
echo "── 0) 取得の完走確認（未完なら中断推奨）────────────────────"
uv run findex progress financials_build | head -2 || true
uv run findex progress dividends_yfinance | head -2 || true
echo "※ 上が ~100% で 停止/完了 でなければ Ctrl-C して取得完走を待つこと。"
echo "   5秒後に続行..."; sleep 5

echo
echo "── 1) 取りこぼし治癒（resume パス: failed/未書込だけ再取得）──"
# resume（--no-resume を付けない）= checkpoint 済みはskip、failed だけ再取得。
uv run findex financials --all
uv run findex dividends  --all

echo
echo "── 2) 導出層 derive --what all（全銘柄）──────────────────"
uv run findex derive --all --what all

echo
echo "── 3) 採点 score（全銘柄・上位30表示）────────────────────"
uv run findex score --all --top 30

echo
echo "── 4) 検収 verify（全銘柄・golden/カバレッジ/seam/status）─"
uv run findex verify --all

echo
echo "════════════════════════════════════════════════════════════"
echo " 仕上げ完了。verify の golden整合=✓ / 不整合0 を必ず確認すること。"
echo " 不整合や想定外の穴があれば derive/score/verify のログを精査。"
echo "════════════════════════════════════════════════════════════"
