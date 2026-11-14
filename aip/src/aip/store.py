"""SQLite 连接与迁移。

设计约束（见设计文档「数据层」）：
- WAL + 短事务 + busy_timeout，靠 SQLite 自身的跨进程写锁，不引入进程内锁；
- 迁移成对出现：``NNNN_name.sql`` 升，``NNNN_down.sql`` 降；
- ``schema_version`` 由本模块维护，迁移脚本不自己插版本行。
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS_DIR = Path(__file__).resolve().parent / "db" / "migrations"
_UP_RE = re.compile(r"^(\d{4})_.+\.sql$")
_DOWN_RE = re.compile(r"^(\d{4})_down\.sql$")


def default_db_path() -> Path:
    """默认库文件放项目内 data/，可用 AIP_DB 覆盖（测试用临时文件）。"""
    override = os.environ.get("AIP_DB")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "data" / "aip.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """打开连接并设置 PRAGMA。调用方负责 close()。"""
    db_path = Path(path) if path is not None else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """短事务：出错回滚并抛出。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
    )


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_version_table(conn)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return int(row["v"] or 0)


def _up_scripts() -> dict[int, Path]:
    found: dict[int, Path] = {}
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if _DOWN_RE.match(path.name):
            continue
        match = _UP_RE.match(path.name)
        if match:
            found[int(match.group(1))] = path
    return found


def _down_script(version: int) -> Path | None:
    for path in sorted(MIGRATIONS_DIR.glob(f"{version:04d}_down.sql")):
        return path
    return None


def _run_atomic(conn: sqlite3.Connection, sql: str) -> None:
    """把脚本包进单个事务执行；脚本内的 PRAGMA 在事务中无效，但连接层已设过。"""
    try:
        conn.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise


def migrate(conn: sqlite3.Connection, target: int | None = None) -> int:
    """升到 target（默认最高版本）。返回最终版本号。"""
    scripts = _up_scripts()
    if not scripts:
        raise RuntimeError(f"找不到迁移脚本: {MIGRATIONS_DIR}")
    version = current_version(conn)
    upper = max(scripts) if target is None else target
    while version < upper:
        nxt = min(v for v in scripts if v > version)
        body = scripts[nxt].read_text(encoding="utf-8")
        _run_atomic(
            conn,
            body + f"\nINSERT INTO schema_version (version) VALUES ({nxt});\n",
        )
        version = nxt
    return version


def rollback(conn: sqlite3.Connection, target: int = 0) -> int:
    """降级到 target（默认 0）。返回最终版本号。"""
    version = current_version(conn)
    while version > target:
        path = _down_script(version)
        if path is None:
            raise RuntimeError(f"缺少 {version:04d}_down.sql")
        _run_atomic(conn, path.read_text(encoding="utf-8"))
        version -= 1
    return version


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r["name"] for r in rows}
