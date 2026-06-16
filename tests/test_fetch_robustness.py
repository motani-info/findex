"""取得層の silent-drop 退治の回帰テスト（基盤整備 F1/F2）。

F1: 完全性ゲート＝空/部分データは done を刻まず再取得対象に残す。
F2: EDINET 日次スキャンの一過性失敗を「空」と断定せず EdinetScanError で再取得対象に。
"""
import datetime as dt

import pytest

from findex import config
from findex.fetch import edinet
from findex.fetch.base import RateLimitedFetcher


# --- F1: 完全性ゲート -------------------------------------------------------
class _FakeFetcher(RateLimitedFetcher):
    """B は「中身が空」を返すフェッチャ。is_complete で done を拒否する。"""
    name = "fake_complete"

    def fetch_one(self, code):
        return {"code": code, "value": None if code == "B" else 1.0}

    def is_complete(self, code, result):
        return result["value"] is not None


def test_f1_incomplete_not_checkpointed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHECKPOINT_DIR", tmp_path)
    f = _FakeFetcher()
    f.policy.sleep_between_items = 0
    f.policy.sleep_between_batches = 0
    res = f.run(["A", "B"])
    assert "A" in res.ok and "B" not in res.ok      # 完全な A だけ ok
    assert "B" in res.failed                          # 空の B は failed
    # done は A のみ＝B は次回 resume で再取得される（silent-drop しない）
    ckpt = (tmp_path / "fake_complete.json").read_text()
    assert '"A"' in ckpt and '"B"' not in ckpt


# --- F2: EDINET スキャン信頼性 ---------------------------------------------
class _Resp:
    def __init__(self, results):
        self._results = results

    def json(self):
        return {"results": self._results}


def test_f2_clean_no_doc_returns_none(monkeypatch):
    # 提出一覧が空＝その日は対象書類が真に無い → None（再取得しない）
    monkeypatch.setattr(edinet, "_request", lambda *a, **k: _Resp([]))
    assert edinet._scan_one_date(dt.date(2025, 6, 20), "E00001") is None


def test_f2_finds_target_doc(monkeypatch):
    doc = {"edinetCode": "E00001", "docTypeCode": "120", "csvFlag": "1",
           "docID": "S123", "periodEnd": "2025-03-31"}
    monkeypatch.setattr(edinet, "_request", lambda *a, **k: _Resp([doc]))
    assert edinet._scan_one_date(dt.date(2025, 6, 20), "E00001") == ("S123", "2025-03-31")


def test_f2_transient_raises_scan_error(monkeypatch):
    # 一過性失敗が解消しなければ「空」と断定せず EdinetScanError（再取得対象）
    monkeypatch.setattr(edinet.time, "sleep", lambda *_: None)

    def boom(*a, **k):
        raise ConnectionError("transient")

    monkeypatch.setattr(edinet, "_request", boom)
    with pytest.raises(edinet.EdinetScanError):
        edinet._scan_one_date(dt.date(2025, 6, 20), "E00001")


def test_f2_scan_error_is_retryable():
    # EdinetFetcher はスキャン失敗を指数バックオフのリトライ対象にする
    f = edinet.EdinetFetcher({}, {})
    assert f.is_rate_limit(edinet.EdinetScanError("x")) is True
    assert f.is_rate_limit(ValueError("other")) is False
