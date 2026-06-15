"""パス・設定の集約。~/.findex 配下にDB・セッション・チェックポイントを置く。"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()  # リポジトリ直下の .env を読む（X_EMAIL 等）
except Exception:  # python-dotenv 未インストールでも動く
    pass

# プロジェクトルート（このファイルの2つ上）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ユーザーデータ領域
FINDEX_HOME = Path(os.environ.get("FINDEX_HOME", Path.home() / ".findex"))
# v2 は専用DBに構築する（再構築中の汚染を避ける）。
# 旧 findex.db は「収集済みデータの移行元」として温存し、直接は触らない。
DB_PATH = Path(os.environ.get("FINDEX_DB", FINDEX_HOME / "db" / "findex_v2.db"))
LEGACY_DB_PATH = FINDEX_HOME / "db" / "findex.db"  # 移行元（read-only 扱い）
BACKUP_DIR = FINDEX_HOME / "backup"
CHECKPOINT_DIR = Path(os.environ.get("FINDEX_CHECKPOINTS", FINDEX_HOME / "checkpoints"))
X_SESSION_PATH = FINDEX_HOME / "x_session.json"

# リポジトリ内の参照データ
DATA_DIR = PROJECT_ROOT / "data"
RULES_PATH = PROJECT_ROOT / "rules.yaml"
VERIFICATION_COHORT = DATA_DIR / "verification_cohort.csv"
GOLDEN_STREAKS = DATA_DIR / "golden_streaks_zai_20260601.csv"

# 2000年問題の下限band（この年以前で始まる系列は左打ち切りを疑う）。docs/design/pre2000-data.md
DATA_FLOOR_YEAR = 2002

# APIキー（.env 由来。findex/.env は back_findex/.env のコピー＝gitignore済）
JQUANTS_API_KEY = os.environ.get("JQUANTS_API_KEY", "")
EDINET_API_KEY = os.environ.get("EDINET_API_KEY", "")


def ensure_dirs() -> None:
    for d in (FINDEX_HOME, DB_PATH.parent, BACKUP_DIR, CHECKPOINT_DIR):
        d.mkdir(parents=True, exist_ok=True)
