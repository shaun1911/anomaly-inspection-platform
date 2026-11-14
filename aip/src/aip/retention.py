"""证据保留（存储维护）。

原则：
1. 判例引用的图**永不自动删**——训练集与审计要用；
2. 待复核（pending/claimed）的判定证据不删；
3. 其余按保留天数清理；冒烟图默认 7 天；
4. 只删数据目录内、且 mtime 早于阈值的文件；
5. 先预览、再执行，执行留审计。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .audit import record
from .store import tx

DAY = 86400


def _referenced(conn: sqlite3.Connection) -> set[str]:
    refs: set[str] = set()
    for row in conn.execute("SELECT crop_path FROM case_item WHERE crop_path IS NOT NULL"):
        refs.add(str(Path(row["crop_path"]).resolve()))
    for row in conn.execute(
        "SELECT r.crop_path FROM inference_result r"
        " WHERE r.crop_path IS NOT NULL AND (r.review_status IN ('pending','claimed')"
        " OR r.confirmed_at IS NULL)"
    ):
        refs.add(str(Path(row["crop_path"]).resolve()))
    return refs


def plan(
    conn: sqlite3.Connection,
    data_dir: Path,
    *,
    crop_days: int = 30,
    smoke_days: int = 7,
    now: float | None = None,
) -> dict:
    root = Path(data_dir).resolve()
    referenced = _referenced(conn)
    now_ts = now if now is not None else time.time()

    deletable: list[dict] = []
    for sub, days in (("crops", crop_days), ("smoke", smoke_days)):
        folder = root / sub
        if not folder.is_dir():
            continue
        cutoff = now_ts - max(0, days) * DAY
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            resolved = str(path.resolve())
            if resolved in referenced:
                continue
            stat = path.stat()
            if stat.st_mtime > cutoff:
                continue
            deletable.append({"path": resolved, "bytes": stat.st_size, "kind": sub})

    return {
        "deletable": deletable,
        "count": len(deletable),
        "bytes": sum(d["bytes"] for d in deletable),
        "crop_days": crop_days,
        "smoke_days": smoke_days,
        "data_dir": str(root),
    }


def apply(conn: sqlite3.Connection, data_dir: Path, *, crop_days: int, smoke_days: int,
          actor: str = "maintenance") -> dict:
    result = plan(conn, data_dir, crop_days=crop_days, smoke_days=smoke_days)
    removed = 0
    freed = 0
    for item in result["deletable"]:
        path = Path(item["path"])
        try:
            if path.is_file():
                path.unlink()
                removed += 1
                freed += item["bytes"]
        except OSError:
            continue
    with tx(conn):
        record(conn, actor=actor, action="storage.retention", entity="data",
               payload={"removed": removed, "bytes": freed,
                        "crop_days": crop_days, "smoke_days": smoke_days})
    return {"removed": removed, "bytes": freed, "planned": result["count"]}
