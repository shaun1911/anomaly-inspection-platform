"""每日维护任务：审计归档 + 过期证据清理。

开关在「设置 → 存储」：
- maintenance.auto_audit      自动归档审计（默认关）
- maintenance.auto_retention  自动清理过期证据（默认关）
- maintenance.auto_hour       每天几点执行（UTC，默认 3）

只在 dev_server 启动时拉起一个守护线程；测试直接调 run_once，不启线程。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import audit_archive, retention
from .audit import record
from .settings import get_value
from .storage import is_locked
from .store import connect, tx


def next_run(now: datetime, hour: int) -> datetime:
    hour = max(0, min(23, hour))
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def run_once(conn: sqlite3.Connection, data_dir: Path, actor: str = "maintenance") -> dict:
    if is_locked():
        return {"skipped": "storage_maintenance"}

    result: dict = {}
    if bool(get_value(conn, "maintenance.auto_audit")):
        try:
            out = audit_archive.archive(
                conn, data_dir, days=int(get_value(conn, "audit.retention_days")), actor=actor
            )
            result["audit_archived"] = out["archived"]
            result["audit_path"] = out["path"]
        except Exception as exc:  # noqa: BLE001
            result["audit_error"] = str(exc)

    if bool(get_value(conn, "maintenance.auto_retention")):
        try:
            out = retention.apply(
                conn,
                data_dir,
                crop_days=int(get_value(conn, "retention.crop_days")),
                smoke_days=int(get_value(conn, "retention.smoke_days")),
                actor=actor,
            )
            result["retention_removed"] = out.get("removed", 0)
            result["retention_freed"] = out.get("freed", 0)
        except Exception as exc:  # noqa: BLE001
            result["retention_error"] = str(exc)

    if result:
        with tx(conn):
            record(conn, actor=actor, action="maintenance.auto", entity="data", payload=result)
    return result


class Scheduler(threading.Thread):
    def __init__(self, db_path: str | Path) -> None:
        super().__init__(daemon=True, name="aip-maintenance")
        self.db_path = Path(db_path)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            conn = connect(self.db_path)
            try:
                hour = int(get_value(conn, "maintenance.auto_hour"))
            except Exception:  # noqa: BLE001
                hour = 3
            conn.close()

            now = datetime.now(timezone.utc)
            wait = (next_run(now, hour) - now).total_seconds()
            if self._stop.wait(min(wait, 3600)):
                return
            if wait > 3600:
                continue  # 每小时醒一次重新计算，避免时钟漂移

            conn = connect(self.db_path)
            try:
                run_once(conn, self.db_path.parent)
            except Exception:  # noqa: BLE001 - 守护线程不能死
                pass
            finally:
                conn.close()


def start_scheduler(db_path: str | Path) -> Scheduler:
    scheduler = Scheduler(db_path)
    scheduler.start()
    return scheduler
