"""J-Quants API V2 クライアント
認証: x-api-key ヘッダー（ダッシュボードで発行したAPIキーをそのまま使用）
ベースURL: https://api.jquants.com/v2

主要エンドポイント:
  /v2/fins/summary          財務サマリー（売上/営業利益/EPS/BPS/配当など）
  /v2/fins/dividend         配当金情報
  /v2/equities/bars/daily   株価四本値（終値・調整済み）
  /v2/listed/info           上場銘柄一覧
"""
import json
import time
from pathlib import Path

import requests

BASE_URL  = "https://api.jquants.com/v2"
REQ_TIMEOUT = 60


class JQuantsError(Exception):
    pass


class JQuantsClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise JQuantsError("JQUANTS_API_KEY が未設定です。.env または findex setup で設定してください。")
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({"x-api-key": api_key})

    # ── HTTP ──────────────────────────────────────────────────────
    def _get(self, path: str, **params) -> dict:
        """GETリクエスト。ページネーション（pagination_key）を自動で処理する。"""
        all_items: list = []
        list_key:  str  = ""
        pagination_key: str | None = None

        while True:
            p = {k: v for k, v in params.items() if v is not None}
            if pagination_key:
                p["pagination_key"] = pagination_key

            r = self._session.get(f"{BASE_URL}{path}", params=p, timeout=REQ_TIMEOUT)
            if r.status_code == 429:
                time.sleep(5)
                r = self._session.get(f"{BASE_URL}{path}", params=p, timeout=REQ_TIMEOUT)
            if not r.ok:
                raise JQuantsError(f"API エラー {r.status_code}: {r.text[:300]}")

            data = r.json()

            # "data" キーが最優先、なければリスト型のフィールドを自動検出
            if "data" in data and isinstance(data["data"], list):
                list_key = "data"
                all_items.extend(data["data"])
            else:
                for k, v in data.items():
                    if isinstance(v, list):
                        list_key = k
                        all_items.extend(v)
                        break

            pagination_key = data.get("pagination_key")
            if not pagination_key:
                break

        if list_key:
            data[list_key] = all_items
        return data

    # ── API エンドポイント ────────────────────────────────────────
    def listed_info(self) -> list[dict]:
        """全上場銘柄の基本情報（コード、名称、業種など）"""
        d = self._get("/listed/info")
        return d.get("data") or d.get("info", [])

    def fins_summary(
        self,
        code:      str | None = None,
        date:      str | None = None,   # YYYY-MM-DD（開示日指定）
        date_from: str | None = None,
        date_to:   str | None = None,
    ) -> list[dict]:
        """財務サマリー（売上/営業利益/純利益/EPS/BPS/配当性向など）
        codeまたはdateのいずれか必須。
        """
        d = self._get(
            "/fins/summary",
            code=code,
            date=date,
            **{"from": date_from, "to": date_to},
        )
        return d.get("data") or d.get("fins_summary", [])

    def fins_dividend(
        self,
        code:      str | None = None,
        date:      str | None = None,
        date_from: str | None = None,
        date_to:   str | None = None,
    ) -> list[dict]:
        """配当金情報（DivRate=1株配当、RecDate=基準日）"""
        d = self._get(
            "/fins/dividend",
            code=code,
            date=date,
            **{"from": date_from, "to": date_to},
        )
        return d.get("data") or d.get("dividend", [])

    def equities_bars_daily(
        self,
        code:      str | None = None,
        date:      str | None = None,
        date_from: str | None = None,
        date_to:   str | None = None,
    ) -> list[dict]:
        """株価四本値（C=終値、AdjC=調整済み終値）"""
        d = self._get(
            "/equities/bars/daily",
            code=code,
            date=date,
            **{"from": date_from, "to": date_to},
        )
        return d.get("data") or d.get("daily_quotes", [])
