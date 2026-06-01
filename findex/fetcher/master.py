"""JPX上場銘柄マスターの取得"""
import io
import requests
import pandas as pd

JPX_EXCEL_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"


def fetch_stock_master() -> pd.DataFrame:
    """JPX公式Excelから全上場銘柄リストを取得する"""
    resp = requests.get(JPX_EXCEL_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_excel(io.BytesIO(resp.content), engine="xlrd")
    df = df.rename(columns={
        "コード": "code",
        "銘柄名": "name",
        "市場・商品区分": "market",
        "33業種区分": "sector",
    })
    df["code"] = df["code"].astype(str).str.zfill(4)
    return df[["code", "name", "market", "sector"]].dropna(subset=["code"])
