"""存储目录迁移（启动级配置的受控变更）。

为什么不热切换：数据库连接、裁片路径、静态文件服务都绑定在当前目录上，
运行中改根目录会让正在跑的请求写到两个地方。正确流程是：
预检 → 复制（DB 用 sqlite backup 做一致性快照）→ 校验 → 用新目录重启 → 人工删旧目录。
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .audit import record
from .store import tx

COPY_DIRS = ("crops", "cases", "smoke")
_LOCK = threading.RLock()
_locked = False


def is_locked() -> bool:
    """迁移期间为 True：写入类接口应返回 503，避免数据落两处。"""
    return _locked


@contextmanager
def maintenance():
    global _locked
    with _LOCK:
        _locked = True
        try:
            yield
        finally:
            _locked = False


class StorageError(Exception):
    pass


def _dir_size(path: Path) -> tuple[int, int]:
    files = bytes_ = 0
    for item in path.rglob("*"):
        if item.is_file() and not item.name.endswith(("-wal", "-shm")):
            files += 1
            bytes_ += item.stat().st_size
    return files, bytes_


def info(conn: sqlite3.Connection) -> dict:
    db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    root = db_path.parent
    files, size = _dir_size(root)
    free = shutil.disk_usage(str(root)).free
    return {
        "root": str(root),
        "db": str(db_path),
        "files": files,
        "bytes": size,
        "free": free,
    }


def plan_move(conn: sqlite3.Connection, target: str) -> dict:
    current = Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve().parent
    dest = Path(target).expanduser()
    if not dest.is_absolute():
        raise StorageError("目标目录必须是绝对路径")
    dest = dest.resolve()

    problems: list[str] = []
    if dest == current:
        problems.append("目标目录与当前目录相同")
    if str(dest).startswith(str(current) + "\\") or str(dest).startswith(str(current) + "/"):
        problems.append("目标目录不能位于当前目录内部")
    if str(current).startswith(str(dest) + "\\") or str(current).startswith(str(dest) + "/"):
        problems.append("当前目录不能位于目标目录内部")
    if dest.exists():
        if not dest.is_dir():
            problems.append("目标路径已存在且不是目录")
        elif any(dest.iterdir()):
            problems.append("目标目录非空，请换一个空目录")

    try:
        parent = dest if dest.exists() else dest.parent
        free = shutil.disk_usage(str(parent)).free
    except OSError as exc:
        raise StorageError(f"目标路径不可用: {exc}") from exc

    files, size = _dir_size(current)
    need = int(size * 1.1) + 50 * 1024 * 1024
    if free < need:
        problems.append(
            f"目标磁盘可用空间不足：需要约 {(need / 1048576):.0f} MB，可用 {(free / 1048576):.0f} MB"
        )

    return {
        "source": str(current),
        "target": str(dest),
        "files": files,
        "bytes": size,
        "free": free,
        "problems": problems,
        "ok": not problems,
    }


def apply_move(conn: sqlite3.Connection, target: str, actor: str = "web") -> dict:
    plan = plan_move(conn, target)
    if not plan["ok"]:
        raise StorageError("；".join(plan["problems"]))

    src = Path(plan["source"])
    dst = Path(plan["target"])
    with maintenance():
        return _copy_all(conn, src, dst, plan, actor)


def _copy_all(conn: sqlite3.Connection, src: Path, dst: Path, plan: dict, actor: str) -> dict:
    dst.mkdir(parents=True, exist_ok=True)

    # 1) DB 一致性快照（sqlite backup，不阻塞读）
    dest_conn = sqlite3.connect(dst / "aip.db")
    try:
        conn.backup(dest_conn)
    finally:
        dest_conn.close()

    # 2) 文件目录
    copied: dict[str, int] = {}
    for sub in COPY_DIRS:
        source = src / sub
        if not source.is_dir():
            continue
        target_dir = dst / sub
        if target_dir.exists():
            raise StorageError(f"目标已存在 {sub} 目录，请换空目录")
        shutil.copytree(source, target_dir)
        copied[sub] = sum(1 for p in target_dir.rglob("*") if p.is_file())

    # 3) 校验大小与 DB 完整性
    src_files, src_bytes = _dir_size(src)
    dst_files, dst_bytes = _dir_size(dst)
    problems = []
    if dst_files < src_files:
        problems.append(f"文件数不一致：源 {src_files} / 目标 {dst_files}")
    if dst_bytes < int(src_bytes * 0.95):
        problems.append(f"字节数明显偏少：源 {src_bytes} / 目标 {dst_bytes}")

    check = sqlite3.connect(dst / "aip.db")
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if integrity != "ok":
        problems.append(f"目标数据库完整性检查失败: {integrity}")

    with tx(conn):
        record(conn, actor=actor, action="storage.move", entity="data",
               payload={"source": str(src), "target": str(dst),
                        "files": dst_files, "bytes": dst_bytes, "copied": copied})

    return {
        "moved": not problems,
        "problems": problems,
        "source": str(src),
        "target": str(dst),
        "files": dst_files,
        "bytes": dst_bytes,
        "restart_hint": f'python scripts/dev_server.py --port 8100 --data-dir "{dst}"',
    }
