"""API用DB接続ヘルパー"""
import sqlite3
from contextlib import contextmanager

DB_PATH = "/Users/motani/.findex/db/findex.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
