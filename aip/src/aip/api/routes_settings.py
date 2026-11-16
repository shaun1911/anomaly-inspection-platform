"""运行时配置接口（P2）。"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from pathlib import Path

from .. import retention
from .. import audit_archive
from .. import audit_import
from .. import backup as backup_mod
from .. import storage as storage_mod
from ..storage import is_locked
from .. import settings as settings_mod
from .deps import get_conn
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["settings"])


class SettingIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"value": 30, "actor": "web"}]})

    value: Any
    actor: str = "web"


@router.get("/settings")
def list_settings(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    return settings_mod.all_settings(conn)


class BulkIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"values": {"retention.crop_days": 30, "review.gray_route": "queue"}, "actor": "web"}]})

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
    model_config = ConfigDict(json_schema_extra={"examples": [{"dry_run": True, "actor": "web"}]})

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


class PickPathIn(BaseModel):
    kind: str = "dir"          # dir | open | save
    title: str | None = None
    default: str | None = None


@router.post("/system/pick-path")
def pick_path(body: PickPathIn) -> dict:
    """在服务端桌面弹出系统选择框，返回本机绝对路径（仅 Windows）。"""
    import os
    import subprocess
    import tempfile

    if os.name != "nt":
        raise ApiError("picker_unsupported", "当前系统不支持本地路径选择", "手动输入路径", 400)
    kind = body.kind if body.kind in ("dir", "open", "save") else "dir"
    out_file = Path(tempfile.mkstemp(suffix=".txt")[1])
    script = r"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$kind = $env:AIP_PICK_KIND
$title = $env:AIP_PICK_TITLE
$default = $env:AIP_PICK_DEFAULT
$out = $env:AIP_PICK_OUT
$path = ""
if ($kind -eq "dir") {
  $d = New-Object System.Windows.Forms.FolderBrowserDialog
  if ($title) { $d.Description = $title }
  if ($default -and (Test-Path -LiteralPath $default)) { $d.SelectedPath = $default }
  if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $path = $d.SelectedPath }
} elseif ($kind -eq "open") {
  $f = New-Object System.Windows.Forms.OpenFileDialog
  if ($title) { $f.Title = $title }
  $f.Filter = "备份/文件 (*.zip;*.csv)|*.zip;*.csv|所有文件 (*.*)|*.*"
  if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $path = $f.FileName }
} else {
  $f = New-Object System.Windows.Forms.SaveFileDialog
  if ($title) { $f.Title = $title }
  $f.Filter = "Zip (*.zip)|*.zip"
  if ($default) { $f.FileName = $default }
  if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $path = $f.FileName }
}
[System.IO.File]::WriteAllText($out, $path, [System.Text.Encoding]::UTF8)
"""
    env = dict(os.environ)
    env.update({
        "AIP_PICK_KIND": kind,
        "AIP_PICK_TITLE": body.title or "选择路径",
        "AIP_PICK_DEFAULT": body.default or "",
        "AIP_PICK_OUT": str(out_file),
    })
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            env=env, capture_output=True, timeout=180, check=False,
        )
        picked = out_file.read_text(encoding="utf-8").strip() if out_file.exists() else ""
    except FileNotFoundError as exc:
        raise ApiError("picker_unavailable", "服务端找不到 powershell，无法弹出选择框", "手动输入路径", 503) from exc
    except subprocess.TimeoutExpired as exc:
        raise ApiError("picker_timeout", "选择框超时未操作", "可手动输入路径", 408) from exc
    finally:
        out_file.unlink(missing_ok=True)
    if not picked:
        raise ApiError("picker_cancelled", "没有选择路径", "可手动输入路径", 400)
    return {"path": picked}


class MoveIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"target": "D:\\aip-data", "dry_run": True}]})

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
    model_config = ConfigDict(json_schema_extra={"examples": [{"target": "D:\\aip-backup-20261115.zip", "actor": "web"}]})

    target: str
    actor: str = "web"


class RestoreIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"archive": "D:\\aip-backup-20261115.zip", "target": "D:\\aip-data", "dry_run": True}]})

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


class ArchiveIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"days": 180, "apply": False, "actor": "web"}]})

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


class AuditImportIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"path": "F:\\anomaly\\data\\audit-archive\\audit-20261115.csv", "apply": False, "actor": "web"}]})

    path: str
    apply: bool = False
    actor: str = "web"


@router.post("/maintenance/audit/import")
def audit_import_csv(body: AuditImportIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        return {"dry_run": not body.apply, **audit_import.import_csv(
            conn, body.path, apply=body.apply, actor=body.actor
        )}
    except audit_import.ImportError_ as exc:
        raise ApiError("audit_import_failed", str(exc), "检查 CSV 是否为系统导出的归档", 400) from exc
