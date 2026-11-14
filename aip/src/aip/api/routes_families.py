"""产品族（P3·族建模）。

族是"设计族"：结构相似、可共用模型的一组编码。
件号不挂族——件属于编码，编码属于族，族决定用哪个模型。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..audit import record
from ..store import tx
from .deps import get_conn
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["family"])


class FamilyIn(BaseModel):
    name: str
    note: str | None = None


@router.get("/families")
def list_families(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    rows = conn.execute(
        "SELECT f.id, f.name, f.note, f.created_at,"
        " (SELECT count(*) FROM product_code p WHERE p.family_id = f.id) AS code_count"
        " FROM family f ORDER BY f.name"
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/families", status_code=201)
def create_family(body: FamilyIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    name = body.name.strip()
    if not name:
        raise ApiError("bad_name", "族名不能为空", "补一个名字", 400)
    try:
        with tx(conn):
            cur = conn.execute(
                "INSERT INTO family (name, note) VALUES (?, ?)", (name, body.note)
            )
            fid = int(cur.lastrowid)
            record(conn, actor="web", action="family.create", entity="family", entity_id=fid,
                   payload={"name": name})
    except sqlite3.IntegrityError as exc:
        raise ApiError("family_exists", f"族 {name} 已存在", "选已有的族", 409) from exc
    return {"id": fid, "name": name}


@router.get("/families/{family_id}/models")
def family_models(family_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """族 → 模型：同族编码应共用同一个模型；不一致就报冲突。"""
    fam = conn.execute("SELECT id, name FROM family WHERE id = ?", (family_id,)).fetchone()
    if fam is None:
        raise ApiError("family_not_found", f"族 {family_id} 不存在", "刷新", 404)

    codes = conn.execute(
        "SELECT id, code FROM product_code WHERE family_id = ? ORDER BY code", (family_id,)
    ).fetchall()
    out_codes: list[dict[str, Any]] = []
    model_ids: set[int] = set()
    for c in codes:
        binding = conn.execute(
            "SELECT b.model_id, m.code, m.name FROM binding b JOIN model m ON m.id = b.model_id"
            " WHERE b.product_code_id = ? AND b.active_to IS NULL",
            (c["id"],),
        ).fetchone()
        out_codes.append(
            {
                "code": c["code"],
                "model_id": binding["model_id"] if binding else None,
                "model_code": binding["code"] if binding else None,
                "model_name": binding["name"] if binding else None,
            }
        )
        if binding:
            model_ids.add(int(binding["model_id"]))

    return {
        "family_id": family_id,
        "family": fam["name"],
        "codes": out_codes,
        "model_ids": sorted(model_ids),
        "conflict": len(model_ids) > 1,
        "note": "" if len(model_ids) <= 1 else "同族编码绑定了不同模型，抽样与发布口径会分裂",
    }
