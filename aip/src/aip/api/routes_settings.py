"""运行时配置接口（P2）。"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

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
