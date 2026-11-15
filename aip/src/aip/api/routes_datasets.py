"""数据集接口（L3）。"""

from __future__ import annotations

import csv
import io
import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, Depends, UploadFile, File, Response
from pydantic import BaseModel, ConfigDict

from .. import dataset_audit
from ..storage import is_locked
from .. import datasets as ds_mod
from ..store import tx
from ..audit import record
from .deps import get_conn
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["dataset"])


class DatasetIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"model_id": 1, "name": "M1-2026-W46", "note": "第 46 周样本"}]})

    model_id: int
    name: str
    note: str | None = None


class ItemsIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"case_ids": [1, 2, 3]}]})

    case_ids: list[int]


class ActorIn(BaseModel):
    actor: str = "web"


@router.get("/datasets")
def list_datasets(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    return ds_mod.list_datasets(conn)


@router.post("/datasets", status_code=201)
def create_dataset(body: DatasetIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        dataset_id = ds_mod.create_dataset(conn, model_id=body.model_id, name=body.name, note=body.note)
    except ds_mod.DatasetError as exc:
        raise ApiError(exc.code, str(exc), "检查模型与族", exc.status) from exc
    return {"id": dataset_id}


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        return ds_mod.get_dataset(conn, dataset_id)
    except ds_mod.DatasetError as exc:
        raise ApiError(exc.code, str(exc), "刷新列表", exc.status) from exc


@router.post("/datasets/{dataset_id}/items")
def add_items(
    dataset_id: int, body: ItemsIn, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    try:
        return ds_mod.add_items(conn, dataset_id, body.case_ids)
    except ds_mod.DatasetError as exc:
        raise ApiError(exc.code, str(exc), "刷新数据集", exc.status) from exc


@router.delete("/datasets/{dataset_id}/items/{case_id}")
def remove_item(
    dataset_id: int, case_id: int, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    ds = conn.execute("SELECT status FROM dataset WHERE id = ?", (dataset_id,)).fetchone()
    if ds is None:
        raise ApiError("dataset_not_found", "数据集不存在", "刷新", 404)
    if ds["status"] != "draft":
        raise ApiError("dataset_frozen", "数据集已冻结，不能改", "新建数据集", 409)
    with tx(conn):
        cur = conn.execute(
            "DELETE FROM dataset_item WHERE dataset_id = ? AND case_id = ?",
            (dataset_id, case_id),
        )
        if cur.rowcount == 0:
            raise ApiError("item_not_found", "该判例不在数据集中", "刷新", 404)
        record(conn, actor="web", action="dataset.remove", entity="dataset",
               entity_id=dataset_id, payload={"case_id": case_id})
    return {"removed": case_id}


@router.get("/datasets/{dataset_id}/audit")
def audit_dataset(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        return dataset_audit.audit(conn, dataset_id)
    except ds_mod.DatasetError as exc:
        raise ApiError(exc.code, str(exc), "刷新列表", exc.status) from exc


@router.post("/datasets/{dataset_id}/freeze")
def freeze(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        checksum = ds_mod.freeze(conn, dataset_id)
    except ds_mod.DatasetError as exc:
        raise ApiError(exc.code, str(exc), "检查数据集内容", exc.status) from exc
    return {"id": dataset_id, "checksum": checksum, "status": "frozen"}


@router.get("/datasets/{dataset_id}/export.csv")
def export_csv(dataset_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    try:
        data = ds_mod.get_dataset(conn, dataset_id)
    except ds_mod.DatasetError as exc:
        raise ApiError(exc.code, str(exc), "刷新", exc.status) from exc
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["case_id", "code", "part_no", "batch_no", "verdict", "reason", "split"])
    for it in data["items"]:
        writer.writerow([it["case_id"], it["code"], it["part_no"] or "", it["batch_no"] or "",
                         it["verdict"], it["reason"] or "", it["split"]])
    name = f"dataset-{dataset_id}.csv"
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}"},
    )


@router.post("/cases/upload")
def upload_case_image(file: UploadFile = File(...), conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """判例裁片上传：落到 data/cases/，返回可用的 crop_path。"""
    import hashlib
    from pathlib import Path

    if is_locked():
        raise ApiError("maintenance", "存储迁移中，暂停上传", "等迁移完成后重试", 503)
    payload = file.file.read()
    if not payload:
        raise ApiError("empty_file", "文件为空", "重选文件", 400)
    if len(payload) > 20 * 1024 * 1024:
        raise ApiError("file_too_large", "文件超过 20 MB", "压缩后再传", 400)

    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    target_dir = db_file.parent / "cases"
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(payload).hexdigest()
    suffix = ".png" if payload[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
    target = target_dir / f"{digest}{suffix}"
    if not target.exists():
        target.write_bytes(payload)
    return {"crop_path": str(target), "sha256": digest}
