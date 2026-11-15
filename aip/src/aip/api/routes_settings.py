"""运行时配置接口（P2）。"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from pathlib import Path

from .. import retention
from .. import audit_archive
from .. import backup as backup_mod
from .. import storage as storage_mod
from ..storage import is_locked
from .. import settings as settings_mod
from .deps import get_conn
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["settings"])


class SettingIn(BaseModel):
    value: Any
    actor: str = "web"


@router.get("/settings")
def list_settings(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    return settings_mod.all_settings(conn)


class BulkIn(BaseModel):
    values: dict[str, Any]
    actor: str = "web"


@router.post("/settings/bulk")
def bulk_update(body: BulkIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        saved = settings_mod.set_many(conn, body.values, actor=body.actor)
    except KeyError as exc:
        raise ApiError("unknown_setting", str(exc), "刷新页面重试", 404) from exc
    except ValueError as exc:
        raise ApiError("invalid_setting", str(exc), "按提示范围修正", 400) from exc
    return {"saved": saved, "count": len(saved)}


@router.put("/settings/{key}")
def update_setting(
    key: str, body: SettingIn, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    try:
        value = settings_mod.set_value(conn, key, body.value, actor=body.actor)
    except KeyError as exc:
        raise ApiError("unknown_setting", str(exc), "刷新页面重试", 404) from exc
    except ValueError as exc:
        raise ApiError("invalid_setting", str(exc), "按提示范围修正", 400) from exc
    return {"key": key, "value": value}


class RetentionIn(BaseModel):
    dry_run: bool = True
    actor: str = "web"


@router.post("/maintenance/retention")
def maintenance_retention(body: RetentionIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    crop_days = settings_mod.get_value(conn, "retention.crop_days")
    smoke_days = settings_mod.get_value(conn, "retention.smoke_days")
    if body.dry_run:
        result = retention.plan(conn, db_file.parent, crop_days=crop_days, smoke_days=smoke_days)
        return {"dry_run": True, **{k: result[k] for k in ("count", "bytes", "crop_days", "smoke_days")}}
    if is_locked():
        raise ApiError("maintenance", "存储迁移中，暂停清理", "等迁移完成后重试", 503)
    return {"dry_run": False, **retention.apply(
        conn, db_file.parent, crop_days=crop_days, smoke_days=smoke_days, actor=body.actor
    )}


class MoveIn(BaseModel):
    target: str
    dry_run: bool = True


@router.get("/maintenance/storage")
def storage_info(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return storage_mod.info(conn)


@router.post("/maintenance/storage/move")
def storage_move(body: MoveIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        if body.dry_run:
            return {"dry_run": True, **storage_mod.plan_move(conn, body.target)}
        return {"dry_run": False, **storage_mod.apply_move(conn, body.target)}
    except storage_mod.StorageError as exc:
        raise ApiError("storage_move_failed", str(exc), "换一个空目录或检查磁盘空间", 400) from exc


class BackupIn(BaseModel):
    target: str
    actor: str = "web"


class RestoreIn(BaseModel):
    archive: str
    target: str
    dry_run: bool = True


@router.post("/maintenance/backup")
def storage_backup(body: BackupIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        return backup_mod.create(conn, body.target, actor=body.actor)
    except backup_mod.BackupError as exc:
        raise ApiError("backup_failed", str(exc), "换一个路径或检查磁盘", 400) from exc


@router.post("/maintenance/restore")
def storage_restore(body: RestoreIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        if body.dry_run:
            return {"dry_run": True, **backup_mod.inspect(body.archive)}
        return {"dry_run": False, **backup_mod.restore(body.archive, body.target, conn=conn, actor=body.actor)}
    except backup_mod.BackupError as exc:
        raise ApiError("restore_failed", str(exc), "检查备份文件与目标目录", 400) from exc


@router.get("/maintenance/storage")
def storage_info(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    return storage_mod.info(conn)


class ArchiveIn(BaseModel):
    days: int | None = None
    apply: bool = False
    actor: str = "web"


@router.get("/maintenance/audit")
def audit_archive_plan(days: int | None = None, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    days = days or int(settings_mod.get_value(conn, "audit.retention_days"))
    try:
        return audit_archive.plan(conn, days)
    except audit_archive.ArchiveError as exc:
        raise ApiError("archive_invalid", str(exc), "保留天数至少 30 天", 400) from exc


@router.post("/maintenance/audit/archive")
def audit_archive_apply(body: ArchiveIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    days = body.days or int(settings_mod.get_value(conn, "audit.retention_days"))
    try:
        if not body.apply:
            return {"dry_run": True, **audit_archive.plan(conn, days)}
        return {"dry_run": False, **audit_archive.archive(
            conn, db_file.parent, days=days, actor=body.actor
        )}
    except audit_archive.ArchiveError as exc:
        raise ApiError("archive_invalid", str(exc), "保留天数至少 30 天", 400) from exc
