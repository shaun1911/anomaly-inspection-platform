"""ROI 配置管理 API。"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from .. import roi_profiles
from .deps import get_conn
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["roi"])


class RoiProfileIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "station": "S1", "roi_rect": [0, 0, 280, 400], "note": "S1 相机重装后",
    }]})

    station: str | None = None
    roi_rect: list[int]
    note: str | None = None
    actor: str = "web"


@router.get("/codes/{code}/roi-profiles")
def list_roi_profiles(code: str, conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    try:
        return roi_profiles.list_profiles(conn, code)
    except roi_profiles.RoiError as exc:
        raise ApiError(exc.code, str(exc), "核对编码", exc.status) from exc


@router.put("/codes/{code}/roi-profiles")
def save_roi_profile(
    code: str, body: RoiProfileIn, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    try:
        return roi_profiles.save_profile(
            conn, code, body.roi_rect, station=body.station, note=body.note, actor=body.actor
        )
    except roi_profiles.RoiError as exc:
        raise ApiError(exc.code, str(exc), "检查 ROI 与站位", exc.status) from exc
