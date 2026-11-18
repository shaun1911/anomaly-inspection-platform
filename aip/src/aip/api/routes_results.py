"""结果与复核（T1-4）。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from ..audit import record
from ..store import tx
from .deps import get_conn
from .errors import ApiError

router = APIRouter(tags=["results"])


@router.get("/results")
def list_results(
    code: str | None = None,
    label: str | None = None,
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[dict]:
    sql = (
        "SELECT r.id, j.code, j.part_no, r.score, r.label, r.created_at,"
        " r.confirmed_by, r.confirmed_at"
        " FROM inference_result r JOIN inference_job j ON j.id = r.job_id"
    )
    clauses: list[str] = []
    params: list[object] = []
    if code is not None:
        clauses.append("j.code = ?")
        params.append(code)
    if label is not None:
        clauses.append("r.label = ?")
        params.append(label)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY r.id DESC LIMIT ? OFFSET ?"
    params.extend([max(1, min(limit, 500)), max(0, offset)])
    return [
        {
            "id": row["id"],
            "code": row["code"],
            "part_no": row["part_no"],
            "score": row["score"],
            "label": row["label"],
            "created_at": row["created_at"],
            "confirmed_by": row["confirmed_by"],
            "confirmed_at": row["confirmed_at"],
        }
        for row in conn.execute(sql, params).fetchall()
    ]


@router.get("/results/{result_id}")
def get_result(result_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    row = conn.execute(
        "SELECT r.*, j.code, j.part_no, j.status AS job_status"
        " FROM inference_result r JOIN inference_job j ON j.id = r.job_id"
        " WHERE r.id = ?",
        (result_id,),
    ).fetchone()
    if row is None:
        raise ApiError("result_not_found", f"结果 {result_id} 不存在", "刷新列表", 404)

    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "code": row["code"],
        "part_no": row["part_no"],
        "job_status": row["job_status"],
        "score": row["score"],
        "label": row["label"],
        "boxes": json.loads(row["boxes_json"]) if row["boxes_json"] else [],
        "roi": json.loads(row["roi_json"]) if row["roi_json"] else None,
        "crop_path": row["crop_path"],
        "thumb_path": row["thumb_path"],
        "original_w": row["original_w"],
        "original_h": row["original_h"],
        "model_version_id": row["model_version_id"],
        "decode_ms": row["decode_ms"],
        "latency_ms": row["latency_ms"],
        "source": row["source"],
        "confirmed_by": row["confirmed_by"],
        "confirmed_at": row["confirmed_at"],
        "confirm_note": row["confirm_note"],
        "review_status": row["review_status"],
    }


@router.get("/results/{result_id}/image")
def result_image(result_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> FileResponse:
    """返回裁片原图，仅限数据目录内；目录外一律拒绝。"""
    row = conn.execute(
        "SELECT crop_path FROM inference_result WHERE id = ?", (result_id,)
    ).fetchone()
    if row is None:
        raise ApiError("result_not_found", f"结果 {result_id} 不存在", "刷新列表", 404)
    if not row["crop_path"]:
        raise ApiError("no_image", "这条结果没有裁片", "检查入库流程", 404)

    path = Path(row["crop_path"]).resolve()
    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    allowed_root = db_file.parent
    if not str(path).startswith(str(allowed_root)):
        raise ApiError("image_outside_root", "裁片路径不在数据目录内", "检查存储配置", 403)
    if not path.exists():
        raise ApiError("image_missing", "裁片文件已不存在", "可能已被清理", 404)

    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


@router.get("/review/pending")
def pending(
    station: str | None = None,
    limit: int = 50,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    sql = (
        "SELECT r.id, r.score, r.label, r.created_at, j.code, j.part_no"
        " FROM inference_result r"
        " JOIN inference_job j ON j.id = r.job_id"
        " LEFT JOIN station s ON s.id = j.station_id"
        " WHERE r.label IN ('ng','gray') AND r.confirmed_at IS NULL"
    )
    params: list[object] = []
    if station is not None:
        sql += " AND s.name = ?"
        params.append(station)
    sql += " ORDER BY r.id DESC LIMIT ?"
    params.append(max(1, min(limit, 50)))
    rows = conn.execute(sql, params).fetchall()
    return {
        "count": len(rows),
        "items": [
            {
                "result_id": r["id"],
                "code": r["code"],
                "part_no": r["part_no"],
                "score": r["score"],
                "label": r["label"],
                "created_at": r["created_at"],
            }
            for r in rows
        ],
    }


class ConfirmIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"verdict": "ok", "flip": False, "note": "划痕可接受", "confirmed_by": "admin"}]})

    verdict: str | None = None     # 不传 = 保留系统原结论
    flip: bool = False             # true = 各自翻转到相反结论
    note: str | None = None
    confirmed_by: str


@router.post("/review/{result_id}/confirm")
def confirm(
    result_id: int, body: ConfirmIn, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    if body.verdict is not None and body.verdict not in ("ok", "ng", "gray"):
        raise ApiError("bad_verdict", "verdict 只能是 ok/gray/ng", "重选", 400)
    row = conn.execute(
        "SELECT id, label FROM inference_result WHERE id = ?", (result_id,)
    ).fetchone()
    if row is None:
        raise ApiError("result_not_found", f"结果 {result_id} 不存在", "刷新列表", 404)

    if body.flip:
        verdict = "ok" if row["label"] == "ng" else "ng"
    elif body.verdict is None:
        verdict = row["label"]
    else:
        verdict = body.verdict

    with tx(conn):
        conn.execute(
            "UPDATE inference_result SET label = ?, confirmed_by = ?,"
            " confirmed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), confirm_note = ?,"
            " review_status = 'done', claimed_by = COALESCE(claimed_by, ?),"
            " claimed_at = COALESCE(claimed_at, strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
            " WHERE id = ?",
            (verdict, body.confirmed_by, body.note, body.confirmed_by, result_id),
        )
        record(
            conn,
            actor=body.confirmed_by,
            action="review.confirm",
            entity="inference_result",
            entity_id=result_id,
            payload={"verdict": body.verdict, "note": body.note},
        )
    return {"result_id": result_id, "verdict": verdict, "confirmed_by": body.confirmed_by}


@router.get("/results/{result_id}/references")
def references(result_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """复核参考样例：同编码下已裁决的 OK/NG 各最多 2 张，等量、不暗示结论。"""
    job = conn.execute(
        "SELECT j.code FROM inference_result r JOIN inference_job j ON j.id = r.job_id"
        " WHERE r.id = ?",
        (result_id,),
    ).fetchone()
    if job is None:
        raise ApiError("result_not_found", f"结果 {result_id} 不存在", "刷新", 404)

    def pick(verdict: str) -> list[dict]:
        rows = conn.execute(
            "SELECT c.id, c.verdict, c.reason FROM case_item c"
            " JOIN product_code p ON p.id = c.product_code_id"
            " WHERE p.code = ? AND c.verdict = ? ORDER BY c.id DESC LIMIT 2",
            (job["code"], verdict),
        ).fetchall()
        return [
            {
                "case_id": r["id"],
                "verdict": r["verdict"],
                "reason": r["reason"],
                "image_url": f"/api/cases/{r['id']}/image",
            }
            for r in rows
        ]

    ok = pick("ok")
    ng = pick("ng")
    return {
        "code": job["code"],
        "ok": ok,
        "ng": ng,
        "enough": len(ok) > 0 and len(ng) > 0,
        "note": "" if (ok and ng) else "该编码的判例还不够，参考价值有限",
    }
