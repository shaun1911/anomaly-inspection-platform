"""备份与还原（整目录）。

- 备份：迁移写锁 → sqlite backup 出临时库 → 打包 zip（含 manifest）→ 校验
- 还原：只解到**空目录**，先做 manifest/完整性/路径穿越检查，再解压并复核
- 两者共用 storage.maintenance() 的写锁，避免复制期间出现新文件
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import storage
from .audit import record
from .store import tx

FORMAT_VERSION = 1
COPY_DIRS = storage.COPY_DIRS


class BackupError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _count(root: Path) -> tuple[int, int]:
    return storage._dir_size(root)


def create(conn: sqlite3.Connection, target: str, actor: str = "web") -> dict:
    dest = Path(target).expanduser()
    if not dest.is_absolute():
        raise BackupError("备份文件路径必须是绝对路径")
    if dest.suffix.lower() != ".zip":
        raise BackupError("备份文件必须以 .zip 结尾")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise BackupError("目标文件已存在，请换一个名字")

    db_path = Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    root = db_path.parent

    with storage.maintenance():
        with tempfile.TemporaryDirectory() as tmp:
            tmp_db = Path(tmp) / "aip.db"
            snap = sqlite3.connect(tmp_db)
            try:
                conn.backup(snap)
            finally:
                snap.close()

            files, bytes_ = _count(root)
            manifest = {
                "format_version": FORMAT_VERSION,
                "created_at": _now(),
                "source_root": str(root),
                "files": files,
                "bytes": bytes_,
                "app": "aip",
            }
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                zf.write(tmp_db, "aip.db")
                for sub in COPY_DIRS:
                    folder = root / sub
                    if not folder.is_dir():
                        continue
                    for item in folder.rglob("*"):
                        if item.is_file():
                            zf.write(item, f"{sub}/{item.relative_to(folder).as_posix()}")

    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    with tx(conn):
        record(conn, actor=actor, action="storage.backup", entity="data",
               payload={"archive": str(dest), "files": files, "bytes": bytes_, "sha256": digest})
    return {"archive": str(dest), "files": files, "bytes": bytes_, "sha256": digest,
            "size": dest.stat().st_size}


def inspect(archive: str) -> dict:
    path = Path(archive).expanduser()
    if not path.is_file():
        raise BackupError(f"备份文件不存在: {path}")
    problems: list[str] = []
    manifest: dict = {}

    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            for name in names:
                parts = Path(name).parts
                if name.startswith(("/", "\\")) or ".." in parts:
                    problems.append(f"压缩包包含非法路径: {name}")
            if "manifest.json" not in names:
                problems.append("缺少 manifest.json")
            else:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            if "aip.db" not in names:
                problems.append("缺少 aip.db")

            if "aip.db" in names:
                with tempfile.TemporaryDirectory() as tmp:
                    zf.extract("aip.db", tmp)
                    check = sqlite3.connect(Path(tmp) / "aip.db")
                    try:
                        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
                        version = check.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
                    finally:
                        check.close()
                    if integrity != "ok":
                        problems.append(f"数据库完整性检查失败: {integrity}")
                    manifest["schema_version"] = version

            if manifest.get("format_version") != FORMAT_VERSION:
                problems.append(f"备份格式版本不支持: {manifest.get('format_version')}")
    except zipfile.BadZipFile as exc:
        raise BackupError(f"不是有效的 zip 备份: {exc}") from exc

    return {"archive": str(path), "manifest": manifest, "problems": problems, "ok": not problems}


def restore(archive: str, target: str, conn: sqlite3.Connection | None = None,
            actor: str = "web") -> dict:
    info = inspect(archive)
    if not info["ok"]:
        raise BackupError("；".join(info["problems"]))

    dest = Path(target).expanduser()
    if not dest.is_absolute():
        raise BackupError("还原目标目录必须是绝对路径")
    dest = dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise BackupError("还原目标目录必须为空")

    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(Path(archive)) as zf:
        for name in zf.namelist():
            if name == "manifest.json":
                continue
            zf.extract(name, dest)

    # 复核
    files, bytes_ = _count(dest)
    problems = []
    expected = int(info["manifest"].get("files", 0))
    if expected and files < expected:
        problems.append(f"文件数少于备份记录：备份 {expected} / 还原 {files}")
    check = sqlite3.connect(dest / "aip.db")
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if integrity != "ok":
        problems.append(f"还原后数据库完整性检查失败: {integrity}")

    if problems:
        return {"restored": False, "problems": problems, "target": str(dest),
                "files": files, "bytes": bytes_}

    if conn is not None:
        with tx(conn):
            record(conn, actor=actor, action="storage.restore", entity="data",
                   payload={"archive": str(archive), "target": str(dest), "files": files})

    return {"restored": True, "problems": [], "target": str(dest), "files": files,
            "bytes": bytes_,
            "restart_hint": f'python scripts/dev_server.py --port 8100 --data-dir "{dest}"'}
