"""キャッシュ読み書きヘルパー: ~/.findex/cache/{fetcher}/{code}.json"""
import json
from datetime import datetime
from pathlib import Path

CACHE_DIR = Path.home() / ".findex" / "cache"
CACHE_VERSION = 1


def load_cache(fetcher: str, code: str, ttl_days: int | None) -> dict | None:
    """キャッシュが有効期限内なら data を返す。期限切れ・存在しない場合は None。
    ttl_days=None は永続キャッシュ（EDINETなど）。
    """
    path = CACHE_DIR / fetcher / f"{code}.json"
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    if envelope.get("version") != CACHE_VERSION:
        return None  # スキーマ変更時は無効扱い

    if ttl_days is not None:
        fetched_at = datetime.fromisoformat(envelope["fetched_at"])
        age_days = (datetime.now() - fetched_at).days
        if age_days >= ttl_days:
            return None

    return envelope.get("data")


def save_cache(fetcher: str, code: str, data: dict, doc_id: str | None = None) -> None:
    """data を JSON エンベロープで保存する。"""
    path = CACHE_DIR / fetcher / f"{code}.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    envelope: dict = {
        "version":    CACHE_VERSION,
        "fetcher":    fetcher,
        "code":       code,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "data":       data,
    }
    if doc_id:
        envelope["doc_id"] = doc_id

    path.write_text(
        json.dumps(envelope, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def invalidate_cache(fetcher: str, code: str) -> None:
    """指定銘柄のキャッシュを削除する（--refresh 用）"""
    path = CACHE_DIR / fetcher / f"{code}.json"
    if path.exists():
        path.unlink()


def invalidate_all(fetcher: str) -> None:
    """fetcher 単位でキャッシュを全削除する"""
    cache_dir = CACHE_DIR / fetcher
    if cache_dir.exists():
        for f in cache_dir.glob("*.json"):
            f.unlink()
