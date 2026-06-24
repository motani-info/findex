"""split 0件のコードだけ再取得（空応答洗替バグの埋め戻し・ゼロリスク）。

現在 stock_splits に1行も無いコードのみを対象に splits を再取得する。これらは既に
空なので、再取得で実データが返れば復活し、空なら現状維持（これ以上悪化しない）。
fetch/splits.py の空応答スキップ修正（2c0314b）と併用。
"""
from __future__ import annotations

import os

from findex.db.database import connect
from findex.fetch.splits import build_splits

DB = os.path.expanduser("~/.findex/db/findex_v2.db")


def main() -> None:
    conn = connect(DB)
    codes = [r[0] for r in conn.execute(
        "SELECT code FROM stocks WHERE code NOT IN (SELECT DISTINCT code FROM stock_splits) "
        "ORDER BY code"
    )]
    print(f"対象(split 0件): {len(codes)} codes")
    # resume=False＝checkpointの「全件done」を無視してこの集合を実取得する。
    res = build_splits(conn, codes, resume=False)
    print(f"完了: ok={res['ok']} failed={res['failed']} splits_rows={res['splits_rows']}")
    n_now = conn.execute("SELECT COUNT(DISTINCT code) FROM stock_splits").fetchone()[0]
    print(f"分割保有コード数(全体): {n_now}")


if __name__ == "__main__":
    main()
