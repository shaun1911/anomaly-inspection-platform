"""请求级依赖。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from .. import store


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """每个请求一个短连接；SQLite 打开成本低，省去连接池的复杂度。"""
    conn = store.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()
