"""主数据接口（T1-5）：编码、模型、版本、配置、阈值、绑定。

这些是低频配置操作，接口只做校验与落库，不做业务编排。
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..audit import record
from ..store import tx
from .errors import ApiError
from .deps import get_conn

router = APIRouter(prefix="/api", tags=["catalog"])

STAGES = ("candidate", "shadow", "assist", "disabled")


class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    family: str | None = None
    family_id: int | None = None
    part: str | None = None
    seq: str | None = None


class ModelIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str | None = None


class VersionIn(BaseModel):
    version_no: int = Field(ge=1)
    onnx_path: str | None = None


class StatusIn(BaseModel):
    status: str


class BindingIn(BaseModel):
    code: str
    model_id: int


class ConfigIn(BaseModel):
    model_version_id: int
    rev: int = Field(ge=1)
    roi_rect: list[int] = Field(min_length=4, max_length=4)
    preprocessing: dict | None = None


class ThresholdIn(BaseModel):
    model_version_id: int
    roi_rev: int = Field(ge=1)
    rev: int | None = None          # 不传则由后端按 (version, roi_rev) 自增
    th_lo: float
    th_hi: float
    mode: str = "normal"


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def _resolve_family_id(conn: sqlite3.Connection, name: str | None) -> int | None:
    """族名 → id；不存在则建。族是实体，编码只能挂已有或新建的族。"""
    if not name or not str(name).strip():
        return None
    clean = str(name).strip()
    row = conn.execute("SELECT id FROM family WHERE name = ?", (clean,)).fetchone()
    if row is not None:
        return int(row["id"])
    cur = conn.execute("INSERT INTO family (name) VALUES (?)", (clean,))
    return int(cur.lastrowid)


@router.post("/codes", status_code=201)
def create_code(body: CodeIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    with tx(conn):
        family_id = body.family_id if body.family_id is not None else _resolve_family_id(conn, body.family)
        try:
            cur = conn.execute(
                "INSERT INTO product_code (code, family_id, part, seq) VALUES (?, ?, ?, ?)",
                (body.code, family_id, body.part, body.seq),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error_code": "code_exists", "message": str(exc), "action": "换一个编码或停用旧编码"},
            ) from exc
    return {"id": cur.lastrowid, "code": body.code}


@router.get("/codes")
def list_codes(
    include_archived: bool = False, conn: sqlite3.Connection = Depends(get_conn)
) -> list[dict]:
    sql = (
        "SELECT p.*, f.name AS family FROM product_code p"
        " LEFT JOIN family f ON f.id = p.family_id"
    )
    if not include_archived:
        sql += " WHERE p.archived_at IS NULL"
    rows = conn.execute(sql + " ORDER BY p.code").fetchall()
    return [_row_to_dict(r) for r in rows]


class CodePatch(BaseModel):
    family: str | None = None
    family_id: int | None = None
    part: str | None = None
    seq: str | None = None


class ActiveIn(BaseModel):
    active: bool


@router.put("/codes/{code}")
def patch_code(
    code: str, body: CodePatch, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    """编码字符串不可改，只能改族/零件/序号这些描述字段。"""
    with tx(conn):
        family_id = body.family_id
        if family_id is None and body.family is not None:
            family_id = _resolve_family_id(conn, body.family)
        cur = conn.execute(
            "UPDATE product_code SET family_id = COALESCE(?, family_id),"
            " part = COALESCE(?, part), seq = COALESCE(?, seq) WHERE code = ?",
            (family_id, body.part, body.seq, code),
        )
        if cur.rowcount == 0:
            raise LookupError(f"未知编码: {code}")
        record(conn, actor="web", action="code.patch", entity="product_code", entity_id=code,
               payload=body.model_dump())
    return {"code": code}


@router.post("/codes/{code}/active")
def set_code_active(
    code: str, body: ActiveIn, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    """停用而非删除：已打印的标签仍能查出历史。"""
    with tx(conn):
        cur = conn.execute(
            "UPDATE product_code SET active = ? WHERE code = ?",
            (1 if body.active else 0, code),
        )
        if cur.rowcount == 0:
            raise LookupError(f"未知编码: {code}")
        record(conn, actor="web", action="code.active", entity="product_code", entity_id=code,
               payload={"active": body.active})
    return {"code": code, "active": body.active}


class ModelPatch(BaseModel):
    name: str | None = None


@router.post("/codes/{code}/archive")
def archive_code(code: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """归档：从默认列表与选择器消失。仍被绑定时禁止，避免现场扫码扫到空入口。"""
    row = conn.execute(
        "SELECT id, archived_at FROM product_code WHERE code = ?", (code,)
    ).fetchone()
    if row is None:
        raise LookupError(f"未知编码: {code}")
    if row["archived_at"] is not None:
        return {"code": code, "archived": True}
    bound = conn.execute(
        "SELECT count(*) c FROM binding WHERE product_code_id = ? AND active_to IS NULL",
        (row["id"],),
    ).fetchone()["c"]
    if bound:
        raise ApiError(
            code="code_in_use",
            message=f"编码 {code} 仍绑定着模型",
            action="先解绑，或只停用不归档",
            status=409,
        )
    with tx(conn):
        conn.execute(
            "UPDATE product_code SET archived_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'),"
            " active = 0 WHERE code = ?",
            (code,),
        )
        record(conn, actor="web", action="code.archive", entity="product_code", entity_id=code)
    return {"code": code, "archived": True}


@router.post("/codes/{code}/restore")
def restore_code(code: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    with tx(conn):
        cur = conn.execute(
            "UPDATE product_code SET archived_at = NULL, active = 1 WHERE code = ?", (code,)
        )
        if cur.rowcount == 0:
            raise LookupError(f"未知编码: {code}")
        record(conn, actor="web", action="code.restore", entity="product_code", entity_id=code)
    return {"code": code, "archived": False}


@router.put("/models/{model_id}")
def patch_model(
    model_id: int, body: ModelPatch, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    with tx(conn):
        cur = conn.execute(
            "UPDATE model SET name = COALESCE(?, name) WHERE id = ?", (body.name, model_id)
        )
        if cur.rowcount == 0:
            raise LookupError(f"未知模型: {model_id}")
        record(conn, actor="web", action="model.patch", entity="model", entity_id=model_id,
               payload=body.model_dump())
    return {"id": model_id}


@router.post("/models/{model_id}/archive")
def archive_model(model_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """有生效绑定时不归档，避免现场扫码扫到空模型。"""
    bound = conn.execute(
        "SELECT count(*) c FROM binding WHERE model_id = ? AND active_to IS NULL", (model_id,)
    ).fetchone()["c"]
    if bound:
        raise ApiError(
            code="model_in_use",
            message=f"模型仍被 {bound} 个编码绑定",
            action="先解除绑定再归档",
            status=409,
        )
    with tx(conn):
        cur = conn.execute(
            "UPDATE model SET archived_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            " WHERE id = ? AND archived_at IS NULL",
            (model_id,),
        )
        if cur.rowcount == 0:
            raise LookupError(f"模型不存在或已归档: {model_id}")
        record(conn, actor="web", action="model.archive", entity="model", entity_id=model_id)
    return {"id": model_id, "archived": True}


@router.delete("/bindings/{binding_id}")
def unbind(binding_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    with tx(conn):
        cur = conn.execute(
            "UPDATE binding SET active_to = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            " WHERE id = ? AND active_to IS NULL",
            (binding_id,),
        )
        if cur.rowcount == 0:
            raise LookupError(f"绑定不存在或已解除: {binding_id}")
        record(conn, actor="web", action="binding.unbind", entity="binding", entity_id=binding_id)
    return {"id": binding_id, "active": False}


@router.post("/models", status_code=201)
def create_model(body: ModelIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    with tx(conn):
        try:
            cur = conn.execute(
                "INSERT INTO model (code, name) VALUES (?, ?)", (body.code, body.name)
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error_code": "model_exists", "message": str(exc), "action": "使用已有模型"},
            ) from exc
    return {"id": cur.lastrowid, "code": body.code}


@router.post("/models/{model_id}/versions", status_code=201)
def create_version(
    model_id: int, body: VersionIn, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    with tx(conn):
        try:
            cur = conn.execute(
                "INSERT INTO model_version (model_id, version_no, onnx_path)"
                " VALUES (?, ?, ?)",
                (model_id, body.version_no, body.onnx_path),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error_code": "version_exists", "message": str(exc), "action": "换版本号"},
            ) from exc
    return {"id": cur.lastrowid, "version_no": body.version_no}


@router.put("/models/{model_id}/versions/{version_no}/status")
def set_version_status(
    model_id: int,
    version_no: int,
    body: StatusIn,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    if body.status not in STAGES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "bad_status",
                "message": f"status 只能是 {STAGES}",
                "action": "检查状态值",
            },
        )
    with tx(conn):
        cur = conn.execute(
            "UPDATE model_version SET status = ? WHERE model_id = ? AND version_no = ?",
            (body.status, model_id, version_no),
        )
        if cur.rowcount == 0:
            raise LookupError("版本不存在")
        if body.status == "assist":
            # 同一模型同一时间只允许一个 assist，旧的自动降为 disabled（回滚栈就靠它）
            conn.execute(
                "UPDATE model_version SET status = 'disabled'"
                " WHERE model_id = ? AND version_no != ? AND status = 'assist'",
                (model_id, version_no),
            )
        # 编码的"阶段"跟随模型版本状态，避免时间线里显示过期的 candidate
        updated = conn.execute(
            "UPDATE binding SET stage = ? WHERE model_id = ? AND active_to IS NULL",
            (body.status, model_id),
        ).rowcount
        record(
            conn,
            actor="web",
            action="version.status",
            entity="model_version",
            entity_id=f"{model_id}:{version_no}",
            payload={"status": body.status, "bindings_updated": updated},
        )
    return {"model_id": model_id, "version_no": version_no, "status": body.status, "bindings_updated": updated}


@router.post("/bindings", status_code=201)
def bind_code(body: BindingIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    code_row = conn.execute(
        "SELECT id FROM product_code WHERE code = ?", (body.code,)
    ).fetchone()
    if code_row is None:
        raise LookupError(f"未知产品编码: {body.code}")
    if conn.execute("SELECT 1 FROM model WHERE id = ?", (body.model_id,)).fetchone() is None:
        raise LookupError(f"未知模型: {body.model_id}")

    with tx(conn):
        conn.execute(
            "UPDATE binding SET active_to = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            " WHERE product_code_id = ? AND active_to IS NULL",
            (code_row["id"],),
        )
        cur = conn.execute(
            "INSERT INTO binding (product_code_id, model_id, stage) VALUES (?, ?, 'candidate')",
            (code_row["id"], body.model_id),
        )
        record(
            conn,
            actor="web",
            action="binding.create",
            entity="product_code",
            entity_id=body.code,
            payload={"model_id": body.model_id},
        )
    return {"id": cur.lastrowid, "code": body.code, "model_id": body.model_id}


@router.get("/bindings")
def list_bindings(
    code: str | None = None, conn: sqlite3.Connection = Depends(get_conn)
) -> list[dict]:
    sql = (
        "SELECT b.id, p.code, b.model_id, b.stage, b.active_from, b.active_to"
        " FROM binding b JOIN product_code p ON p.id = b.product_code_id"
    )
    params: list[object] = []
    if code is not None:
        sql += " WHERE p.code = ?"
        params.append(code)
    sql += " ORDER BY b.id DESC"
    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


@router.post("/configs", status_code=201)
def create_config(body: ConfigIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    with tx(conn):
        try:
            cur = conn.execute(
                "INSERT INTO config_rev (model_version_id, rev, roi_rect, preprocessing_json)"
                " VALUES (?, ?, ?, ?)",
                (
                    body.model_version_id,
                    body.rev,
                    json.dumps(body.roi_rect),
                    json.dumps(body.preprocessing) if body.preprocessing else None,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={"error_code": "config_rev_exists", "message": str(exc), "action": "换 rev"},
            ) from exc
        record(
            conn,
            actor="web",
            action="config.create",
            entity="model_version",
            entity_id=str(body.model_version_id),
            payload={"rev": body.rev, "roi_rect": body.roi_rect},
        )
    return {"id": cur.lastrowid, "rev": body.rev}


@router.post("/thresholds", status_code=201)
def create_threshold(body: ThresholdIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    rev = body.rev
    if rev is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(rev), 0) AS r FROM threshold_rev"
            " WHERE model_version_id = ? AND roi_rev = ?",
            (body.model_version_id, body.roi_rev),
        ).fetchone()
        rev = int(row["r"]) + 1
    with tx(conn):
        try:
            cur = conn.execute(
                "INSERT INTO threshold_rev"
                " (model_version_id, roi_rev, rev, th_lo, th_hi, mode)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    body.model_version_id,
                    body.roi_rev,
                    rev,
                    body.th_lo,
                    body.th_hi,
                    body.mode,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "threshold_conflict",
                    "message": str(exc),
                    "action": "检查 rev 或阈值方向（th_hi 需 >= th_lo，否则用 high_overkill）",
                },
            ) from exc
        record(
            conn,
            actor="web",
            action="threshold.create",
            entity="model_version",
            entity_id=str(body.model_version_id),
            payload={"rev": rev, "th_lo": body.th_lo, "th_hi": body.th_hi, "mode": body.mode},
        )
    return {"id": cur.lastrowid}
