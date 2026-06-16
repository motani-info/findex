"""レート制限に強い取得基盤。

全約4,000銘柄を一気に叩くと多くのサイトでレートリミットに当たる（最大の運用ハードル）。
すべての取得はこの基盤を通し、以下を保証する（requirements.md §9）:
  - 銘柄サブセット指定（--codes）
  - バッチ分割 + バッチ間スリープ
  - チェックポイント / レジューム（取得済みは再取得しない）
  - レート制限検知時の指数バックオフ
"""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generic, Iterable, TypeVar

from .. import config

log = logging.getLogger(__name__)

T = TypeVar("T")


class RateLimitError(Exception):
    """取得側がレート制限を検知したら送出する（429/401など）。"""


@dataclass
class FetchPolicy:
    batch_size: int = 200          # 1バッチの銘柄数
    sleep_between_batches: float = 10.0
    sleep_between_items: float = 0.0
    max_retries: int = 5           # レート制限時の最大リトライ
    backoff_base: float = 2.0      # backoff = base ** attempt
    backoff_cap: float = 120.0     # 1回の待機上限（秒）
    jitter: float = 0.3            # ±30% のゆらぎ
    # サーキットブレーカー: 連続failureがこの数に達したら run を中断する。
    # ブロック/サーバ障害で全件叩き続ける事故（IPブロック）を防ぐ。0で無効。
    max_consecutive_failures: int = 50


class Checkpoint:
    """取得済み銘柄コードをJSONで永続化し、失敗しても再開できるようにする。"""

    def __init__(self, path: Path):
        self.path = path
        self._done: set[str] = set()
        if path.exists():
            try:
                self._done = set(json.loads(path.read_text()))
            except Exception:
                self._done = set()

    @property
    def done(self) -> set[str]:
        return self._done

    def mark(self, code: str) -> None:
        self._done.add(code)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(self._done), ensure_ascii=False))

    def clear(self) -> None:
        self._done.clear()
        if self.path.exists():
            self.path.unlink()


@dataclass
class FetchResult(Generic[T]):
    ok: dict[str, T]
    failed: dict[str, str]        # code -> error message
    skipped: list[str]            # チェックポイント済みで省略

    @property
    def summary(self) -> str:
        return f"ok={len(self.ok)} failed={len(self.failed)} skipped={len(self.skipped)}"


class RateLimitedFetcher(Generic[T]):
    """サブクラスは name と fetch_one() を実装するだけでよい。"""

    name: str = "base"
    policy: FetchPolicy = FetchPolicy()

    def fetch_one(self, code: str) -> T:
        """1銘柄を取得して返す。レート制限なら RateLimitError を送出。"""
        raise NotImplementedError

    def is_rate_limit(self, exc: Exception) -> bool:
        """例外がレート制限由来か判定（サブクラスで上書き可）。"""
        if isinstance(exc, RateLimitError):
            return True
        msg = str(exc).lower()
        return "429" in msg or "rate limit" in msg or "too many requests" in msg

    def is_complete(self, code: str, result: T) -> bool:
        """取得結果を done として確定してよい完全性を持つか（完全性ゲート・F1）。

        False を返すと ok でなく failed に回し、**チェックポイントに done を刻まない**。
        ＝次回 resume で再取得される。「例外を投げなかった＝成功」では空/部分データを
        黙って done 扱いしてしまう（silent-drop）ため、フェッチャは必須フィールドの
        充足をここで宣言する。デフォルトは True（不完全を例外で表すフェッチャ向け）。
        """
        return True

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def _backoff(self, attempt: int) -> float:
        raw = min(self.policy.backoff_base ** attempt, self.policy.backoff_cap)
        return raw * (1 + random.uniform(-self.policy.jitter, self.policy.jitter))

    def run(self, codes: Iterable[str], *, resume: bool = True) -> FetchResult[T]:
        codes = list(dict.fromkeys(codes))  # 重複除去・順序維持
        ckpt = Checkpoint(config.CHECKPOINT_DIR / f"{self.name}.json")
        if not resume:
            ckpt.clear()

        todo = [c for c in codes if c not in ckpt.done]
        skipped = [c for c in codes if c in ckpt.done]
        ok: dict[str, T] = {}
        failed: dict[str, str] = {}
        started = time.time()
        last_error = ""
        consecutive_failures = 0
        breaker = self.policy.max_consecutive_failures

        bs = self.policy.batch_size
        batches = [todo[i : i + bs] for i in range(0, len(todo), bs)]
        log.info("[%s] %d codes (%d skipped) in %d batches", self.name, len(todo), len(skipped), len(batches))
        self._write_progress(len(todo), len(skipped), 0, 0, started, "", running=True)

        aborted = False
        try:
            for bi, batch in enumerate(batches):
                if aborted:
                    break
                for code in batch:
                    try:
                        result = self._fetch_with_retry(code)
                        if self.is_complete(code, result):
                            ok[code] = result
                            ckpt.mark(code)          # 完全なときだけ done を刻む
                            consecutive_failures = 0
                        else:
                            # 完全性ゲート不通過＝空/部分データ。done にせず再取得対象に残す。
                            failed[code] = "incomplete (completeness gate)"
                            last_error = f"{code}: incomplete"
                            consecutive_failures += 1
                            log.warning("[%s] %s incomplete — 再取得対象", self.name, code)
                    except Exception as exc:  # noqa: BLE001 — 1銘柄の失敗で全体を止めない
                        failed[code] = str(exc)
                        last_error = f"{code}: {exc}"
                        consecutive_failures += 1
                        log.warning("[%s] %s failed: %s", self.name, code, exc)
                    # 進捗を逐次書き出す（背景実行を `findex progress` で確認できる）
                    self._write_progress(len(todo), len(skipped), len(ok), len(failed),
                                         started, last_error, running=True)
                    # サーキットブレーカー: 連続失敗が続く＝ブロック/障害。叩き続けず中断（resume可能）。
                    if breaker and consecutive_failures >= breaker:
                        last_error = (f"CIRCUIT BREAKER: {consecutive_failures}連続失敗で中断"
                                      f"（ブロック/障害の疑い・原因解消後に resume 再実行）/ {last_error}")
                        log.error("[%s] %s", self.name, last_error)
                        aborted = True
                        break
                    self._sleep(self.policy.sleep_between_items)
                if not aborted and bi < len(batches) - 1:
                    self._sleep(self.policy.sleep_between_batches)
        finally:
            # 想定外の中断でも「実行中でない」状態を残す（途中経過は保持）
            self._write_progress(len(todo), len(skipped), len(ok), len(failed),
                                 started, last_error, running=False)

        return FetchResult(ok=ok, failed=failed, skipped=skipped)

    def _write_progress(self, todo: int, skipped: int, ok: int, failed: int,
                        started: float, last_error: str, *, running: bool) -> None:
        """進捗を {name}.progress.json に書き出す。AIを介さず CLI で確認できる軽量ファイル。"""
        path = config.CHECKPOINT_DIR / f"{self.name}.progress.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        processed = ok + failed
        elapsed = max(time.time() - started, 1e-6)
        rate = processed / elapsed  # 件/秒
        remaining = max(todo - processed, 0)
        eta = round(remaining / rate) if rate > 0 and remaining else (0 if not remaining else None)
        total = todo + skipped
        done_overall = skipped + processed
        path.write_text(json.dumps({
            "name": self.name,
            "running": running,
            "total": total,                 # 全対象（resume済 + 今回分）
            "done_overall": done_overall,    # 全体の完了数（resume済含む）
            "percent": round(done_overall / total * 100, 1) if total else 100.0,
            "this_run_todo": todo,
            "processed": processed,
            "ok": ok,
            "failed": failed,
            "skipped_resume": skipped,
            "rate_per_min": round(rate * 60, 1),
            "elapsed_sec": round(elapsed),
            "eta_sec": eta,
            "last_error": last_error[:300],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False), encoding="utf-8")

    def _fetch_with_retry(self, code: str) -> T:
        attempt = 0
        while True:
            try:
                return self.fetch_one(code)
            except Exception as exc:  # noqa: BLE001
                if not self.is_rate_limit(exc) or attempt >= self.policy.max_retries:
                    raise
                wait = self._backoff(attempt)
                log.info("[%s] rate-limited on %s, backoff %.1fs (attempt %d)", self.name, code, wait, attempt + 1)
                self._sleep(wait)
                attempt += 1
