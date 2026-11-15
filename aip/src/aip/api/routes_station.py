"""站位接口（T1-2）：配置下发、心跳、白名单校验。

站位是"薄"的：只拿配置、只上报心跳，不做判定、不加载模型。
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from .. import whitelist
from ..settings import get_value
from ..serving.cache import cache
from ..store import tx
from .deps import get_conn
from .errors import ApiError

router = APIRouter(prefix="/station", tags=["station"])

ACTIVE_STAGES = ("shadow", "assist")


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"station": "S1", "config_rev": "1"}]})

    station: str = Field(min_length=1, max_length=64)
    config_rev: str | None = None


def _latest_config(conn: sqlite3.Connection, version_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT rev, roi_rect, preprocessing_json FROM config_rev"
        " WHERE model_version_id = ? ORDER BY rev DESC LIMIT 1",
        (version_id,),
    ).fetchone()


def _latest_threshold(
    conn: sqlite3.Connection, version_id: int, roi_rev: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT rev, th_lo, th_hi, mode FROM threshold_rev"
        " WHERE model_version_id = ? AND roi_rev = ? ORDER BY rev DESC LIMIT 1",
        (version_id, roi_rev),
    ).fetchone()


@router.get("/config")
def station_config(
    code: str,
    station_token: str | None = Header(None, alias="X-Station-Token"),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    expected = get_value(conn, "station.token")
    if expected and station_token != expected:
        raise ApiError("bad_station_token", "站位令牌缺失或错误", "检查客户端令牌配置", 401)
    if not whitelist.is_allowed(code):
        raise ApiError(
            code="not_in_shift",
            message=f"编码 {code} 不在本班白名单",
            action="联系技师确认班次范围，或换用本班编码",
            status=403,
        )

    row = conn.execute(
        "SELECT id, active, archived_at FROM product_code WHERE code = ?", (code,)
    ).fetchone()
    if row is None:
        raise ApiError(
            code="unknown_code",
            message=f"未知编码 {code}",
            action="核对标签或让技师先建编码",
            status=422,
        )
    if row["archived_at"] is not None:
        raise ApiError(
            code="code_archived",
            message=f"编码 {code} 已归档",
            action="联系技师恢复，或换用当前编码",
            status=410,
        )
    if not row["active"]:
        raise ApiError(
            code="code_inactive",
            message=f"编码 {code} 已停用",
            action="联系技师启用或换型号",
            status=410,
        )

    binding = conn.execute(
        "SELECT model_id FROM binding WHERE product_code_id = ? AND active_to IS NULL",
        (row["id"],),
    ).fetchone()
    if binding is None:
        raise ApiError(
            code="no_binding",
            message=f"编码 {code} 未绑定模型",
            action="让技师在管理页绑定模型",
            status=409,
        )

    version = conn.execute(
        "SELECT id, version_no FROM model_version"
        " WHERE model_id = ? AND status IN ('shadow','assist')"
        " ORDER BY version_no DESC LIMIT 1",
        (binding["model_id"],),
    ).fetchone()
    if version is None:
        raise ApiError(
            code="no_active_version",
            message=f"模型 {binding['model_id']} 没有可用版本",
            action="让技师发布一个版本，或检查版本状态",
            status=409,
        )

    config = _latest_config(conn, version["id"])
    if config is None:
        raise ApiError(
            code="no_config",
            message="该版本没有 ROI 配置",
            action="让技师补一条 ROI 配置",
            status=409,
        )

    threshold = _latest_threshold(conn, version["id"], config["rev"])
    return {
        "code": code,
        "model_id": binding["model_id"],
        "model_version_id": version["id"],
        "version_no": version["version_no"],
        "roi_rev": config["rev"],
        "roi_rect": json.loads(config["roi_rect"]),
        "preprocessing": json.loads(config["preprocessing_json"])
        if config["preprocessing_json"]
        else None,
        "threshold": {
            "th_lo": threshold["th_lo"],
            "th_hi": threshold["th_hi"],
            "mode": threshold["mode"],
        }
        if threshold
        else None,
    }


@router.post("/heartbeat")
def heartbeat(
    body: HeartbeatIn,
    station_token: str | None = Header(None, alias="X-Station-Token"),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    expected = get_value(conn, "station.token")
    if expected and station_token != expected:
        raise ApiError("bad_station_token", "站位令牌缺失或错误", "检查客户端令牌配置", 401)
    cache.touch(body.station)
    with tx(conn):
        existing = conn.execute(
            "SELECT id FROM station WHERE name = ?", (body.station,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO station (name, last_config_rev, health, last_seen_at)"
                " VALUES (?, ?, 'ok', strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (body.station, body.config_rev),
            )
        else:
            conn.execute(
                "UPDATE station SET last_config_rev = ?, last_seen_at ="
                " strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                (body.config_rev, existing["id"]),
            )
    return {"station": body.station, "config_rev": body.config_rev, "ok": True}
