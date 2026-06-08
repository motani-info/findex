"""システム設計情報 API — テーブル定義・API一覧を返す"""
from fastapi import APIRouter
import sqlite3

router = APIRouter(prefix="/api/system", tags=["system"])

DB_PATH = "/Users/motani/.findex/db/findex.db"

# ── テーブル定義（役割・カラム説明付き）────────────────────────────
TABLES = [
    {
        "name": "stocks",
        "role": "銘柄マスター（全上場銘柄）",
        "updated": "findex run 実行時",
        "columns": [
            {"name": "code",   "type": "TEXT PK", "desc": "銘柄コード（例: 7203）"},
            {"name": "name",   "type": "TEXT",    "desc": "銘柄名"},
            {"name": "market", "type": "TEXT",    "desc": "市場区分（プライム / スタンダード / グロース）"},
            {"name": "sector", "type": "TEXT",    "desc": "業種（東証33業種）"},
        ],
    },
    {
        "name": "price_history",
        "role": "日次株価履歴（全銘柄共通）",
        "updated": "findex update（毎日）/ findex update --backfill（初回）",
        "columns": [
            {"name": "code",   "type": "TEXT PK", "desc": "銘柄コード"},
            {"name": "date",   "type": "TEXT PK", "desc": "日付（YYYY-MM-DD）"},
            {"name": "close",  "type": "REAL",    "desc": "終値"},
            {"name": "volume", "type": "INTEGER", "desc": "出来高（未実装、NULL）"},
        ],
    },
    {
        "name": "stock_fundamentals",
        "role": "財務データ（全銘柄共通）",
        "updated": "findex update --quarterly（四半期）",
        "columns": [
            {"name": "code",                              "type": "TEXT PK", "desc": "銘柄コード"},
            {"name": "eps",                               "type": "REAL",    "desc": "1株当たり利益"},
            {"name": "bps",                               "type": "REAL",    "desc": "1株当たり純資産"},
            {"name": "shares",                            "type": "REAL",    "desc": "発行済株式数"},
            {"name": "net_cash",                          "type": "REAL",    "desc": "ネットキャッシュ"},
            {"name": "equity_ratio",                      "type": "REAL",    "desc": "自己資本比率"},
            {"name": "roe",                               "type": "REAL",    "desc": "自己資本利益率"},
            {"name": "operating_margin",                  "type": "REAL",    "desc": "営業利益率"},
            {"name": "eps_growth_5y",                     "type": "REAL",    "desc": "EPS5年成長率（CAGR）"},
            {"name": "revenue_growth_5y_cagr",            "type": "REAL",    "desc": "売上高5年成長率（CAGR）"},
            {"name": "roic_minus_wacc",                   "type": "REAL",    "desc": "ROIC−WACC"},
            {"name": "fcf_payout_coverage",               "type": "REAL",    "desc": "FCF配当カバレッジ"},
            {"name": "payout_ratio",                      "type": "REAL",    "desc": "配当性向"},
            {"name": "annual_div",                        "type": "REAL",    "desc": "年間配当額"},
            {"name": "consecutive_no_cut_years",          "type": "INTEGER", "desc": "連続非減配年数"},
            {"name": "consecutive_dividend_growth_years", "type": "INTEGER", "desc": "連続増配年数"},
            {"name": "dividend_growth_10y_cagr",          "type": "REAL",    "desc": "配当10年成長率（CAGR）"},
            {"name": "dividend_reliability",              "type": "REAL",    "desc": "配当信頼性スコア"},
            {"name": "fin_updated_at",                    "type": "TEXT",    "desc": "財務データ更新日時"},
            {"name": "div_updated_at",                    "type": "TEXT",    "desc": "配当データ更新日時"},
        ],
    },
    {
        "name": "scores",
        "role": "配当スコア計算結果（スコアリングエンジンの出力）",
        "updated": "findex update（毎日再計算）/ findex rescore",
        "columns": [
            {"name": "code",        "type": "TEXT",    "desc": "銘柄コード"},
            {"name": "scored_at",   "type": "TEXT",    "desc": "スコア計算日"},
            {"name": "total_score", "type": "REAL",    "desc": "配当スコア（100点満点）"},
            {"name": "score_json",  "type": "TEXT",    "desc": "指標別スコア内訳（JSON）"},
            {"name": "raw_json",    "type": "TEXT",    "desc": "計算に使った生データ（JSON）。market_cap・ROE等を含む"},
            {"name": "rule_version_id", "type": "INTEGER", "desc": "適用ルールバージョン"},
        ],
    },
    {
        "name": "rule_versions",
        "role": "rules.yaml のスナップショット履歴",
        "updated": "rules.yaml 変更時に自動記録",
        "columns": [
            {"name": "id",          "type": "INTEGER PK", "desc": "バージョンID"},
            {"name": "hash",        "type": "TEXT",        "desc": "rules.yaml のSHA256ハッシュ"},
            {"name": "content",     "type": "TEXT",        "desc": "rules.yaml の全文"},
            {"name": "created_at",  "type": "TEXT",        "desc": "記録日時"},
        ],
    },
    {
        "name": "run_log",
        "role": "バッチ実行ログ",
        "updated": "findex run / findex update 実行時",
        "columns": [
            {"name": "id",         "type": "INTEGER PK", "desc": "実行ID"},
            {"name": "mode",       "type": "TEXT",        "desc": "実行モード（run / update）"},
            {"name": "started_at", "type": "TEXT",        "desc": "開始日時"},
            {"name": "ended_at",   "type": "TEXT",        "desc": "終了日時"},
            {"name": "succeeded",  "type": "INTEGER",     "desc": "成功件数"},
            {"name": "failed",     "type": "INTEGER",     "desc": "失敗件数"},
        ],
    },
]

# ── APIエンドポイント一覧 ────────────────────────────────────────────
ENDPOINTS = [
    {
        "group": "配当スコア",
        "color": "green",
        "endpoints": [
            {"method": "GET", "path": "/api/dividend/rank",      "desc": "配当スコアランキング。市場・セクター・利回り等でフィルタ可能"},
            {"method": "GET", "path": "/api/dividend/check/{code}", "desc": "単一銘柄の配当スコア詳細・指標内訳"},
        ],
    },
    {
        "group": "モメンタムスコア",
        "color": "blue",
        "endpoints": [
            {"method": "GET", "path": "/api/momentum/rank",         "desc": "モメンタムランキング。price_history + stock_fundamentals から計算"},
            {"method": "GET", "path": "/api/momentum/check/{code}", "desc": "単一銘柄のモメンタムスコア詳細・指標内訳"},
        ],
    },
    {
        "group": "銘柄情報",
        "color": "purple",
        "endpoints": [
            {"method": "GET", "path": "/api/stock/{code}",   "desc": "銘柄の基本情報・スコア・財務データ一覧"},
            {"method": "GET", "path": "/api/stock/search",   "desc": "銘柄名・コードで検索"},
        ],
    },
    {
        "group": "スコアリングルール",
        "color": "amber",
        "endpoints": [
            {"method": "GET", "path": "/api/rules/scoring",    "desc": "配当・モメンタム両スコアの全指標定義（formula・good/warning・閾値等）"},
            {"method": "GET", "path": "/api/rules/indicators", "desc": "指標定義一覧（旧エンドポイント）"},
        ],
    },
    {
        "group": "データ更新",
        "color": "gray",
        "endpoints": [
            {"method": "POST", "path": "/api/update/daily",     "desc": "日次更新（株価取得・再スコアリング）"},
            {"method": "POST", "path": "/api/update/quarterly", "desc": "四半期更新（財務データ再取得）"},
        ],
    },
    {
        "group": "システム",
        "color": "slate",
        "endpoints": [
            {"method": "GET", "path": "/api/system/design", "desc": "テーブル定義・API設計情報（このエンドポイント）"},
            {"method": "GET", "path": "/api/system/stats",  "desc": "DBの件数・最終更新日等のサマリー"},
        ],
    },
]


@router.get("/design")
def get_design():
    """テーブル定義・API設計情報を返す"""
    return {
        "tables":    TABLES,
        "endpoints": ENDPOINTS,
    }


@router.get("/stats")
def get_stats():
    """DBの件数・最終更新日サマリー"""
    conn = sqlite3.connect(DB_PATH)

    def q(sql, *args):
        try:
            return conn.execute(sql, args).fetchone()[0]
        except Exception:
            return None

    stats = {
        "stocks":            q("SELECT COUNT(*) FROM stocks"),
        "price_history": {
            "records":      q("SELECT COUNT(*) FROM price_history"),
            "codes":        q("SELECT COUNT(DISTINCT code) FROM price_history"),
            "latest_date":  q("SELECT MAX(date) FROM price_history"),
            "oldest_date":  q("SELECT MIN(date) FROM price_history"),
        },
        "stock_fundamentals": q("SELECT COUNT(*) FROM stock_fundamentals"),
        "scores": {
            "records":      q("SELECT COUNT(*) FROM scores"),
            "codes":        q("SELECT COUNT(DISTINCT code) FROM scores"),
            "latest_date":  q("SELECT MAX(scored_at) FROM scores"),
        },
    }
    conn.close()
    return stats
