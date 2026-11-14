"""运行时配置接口（P2）。"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from pathlib import Path

from .. import retention
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
    return {"dry_run": False, **retention.apply(
        conn, db_file.parent, crop_days=crop_days, smoke_days=smoke_days, actor=body.actor
    )}
