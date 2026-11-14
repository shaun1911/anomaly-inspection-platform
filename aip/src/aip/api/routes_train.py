"""训练与发布（P3a）。

真实训练由 anomalib 承担；这里先用确定性的假训练器把状态机与接口跑通：
创建任务 → 产出候选版本（带指标）→ 人工发布 → 可回滚。
"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..audit import record
from ..store import tx
from .deps import get_conn
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["train"])


def _fake_metrics(model_id: int, version_no: int) -> dict:
    """确定性假指标：只为验证链路，不代表模型能力。"""
    seed = (model_id * 17 + version_no * 31) % 100
    recall = round(0.90 + seed / 1000, 3)
    overkill = round(0.02 + (seed % 7) / 1000, 3)
    return {
        "recall": recall,
        "overkill": overkill,
        "val_samples": 15,
        "train_samples": 40 + seed,
        "note": "simulated",
    }


class TrainIn(BaseModel):
    model_id: int
    dataset_id: int
    note: str | None = None


@router.post("/train", status_code=201)
def start_training(body: TrainIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    model = conn.execute("SELECT id, archived_at FROM model WHERE id = ?", (body.model_id,)).fetchone()
    if model is None:
        raise ApiError("unknown_model", f"未知模型 {body.model_id}", "先建模型", 404)
    if model["archived_at"] is not None:
        raise ApiError("model_archived", "模型已归档，不能训练", "恢复模型或换一个", 409)

    dataset = conn.execute("SELECT * FROM dataset WHERE id = ?", (body.dataset_id,)).fetchone()
    if dataset is None:
        raise ApiError("dataset_not_found", f"数据集 {body.dataset_id} 不存在", "先建数据集", 404)
    if dataset["status"] != "frozen":
        raise ApiError("dataset_not_frozen", "数据集尚未冻结，不能用于训练", "先冻结数据集", 409)
    if int(dataset["model_id"]) != body.model_id:
        raise ApiError("dataset_model_mismatch", "数据集属于另一个模型", "换数据集或换模型", 409)

    next_no = conn.execute(
        "SELECT COALESCE(MAX(version_no), 0) + 1 AS n FROM model_version WHERE model_id = ?",
        (body.model_id,),
    ).fetchone()["n"]
    metrics = _fake_metrics(body.model_id, next_no)

    with tx(conn):
        cur = conn.execute(
            "INSERT INTO train_job (model_id, dataset_id, status, started_at)"
            " VALUES (?, ?, 'running', strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
            (body.model_id, body.dataset_id),
        )
        job_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO model_version (model_id, version_no, status, metrics_json, dataset_id)"
            " VALUES (?, ?, 'candidate', ?, ?)",
            (body.model_id, next_no, json.dumps(metrics, ensure_ascii=False), body.dataset_id),
        )
        conn.execute(
            "UPDATE train_job SET status = 'succeeded', metrics_json = ?,"
            " finished_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (json.dumps(metrics, ensure_ascii=False), job_id),
        )
        record(conn, actor="web", action="train.start", entity="model", entity_id=body.model_id,
               payload={"version_no": next_no, "job_id": job_id, "dataset_id": body.dataset_id})
    return {"job_id": job_id, "model_id": body.model_id, "version_no": next_no, "metrics": metrics}


@router.get("/train")
def list_train(
    model_id: int | None = None, limit: int = 50, conn: sqlite3.Connection = Depends(get_conn)
) -> list[dict]:
    sql = (
        "SELECT t.id, t.model_id, m.code model_code, t.dataset_id, d.name dataset_name,"
        " t.status, t.error_code, t.metrics_json, t.started_at, t.finished_at, t.created_at"
        " FROM train_job t JOIN model m ON m.id = t.model_id"
        " LEFT JOIN dataset d ON d.id = t.dataset_id"
    )
    params: list[object] = []
    if model_id is not None:
        sql += " WHERE t.model_id = ?"
        params.append(model_id)
    sql += " ORDER BY t.id DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["metrics"] = json.loads(r["metrics_json"]) if r["metrics_json"] else None
        item.pop("metrics_json", None)
        out.append(item)
    return out


@router.post("/train/{job_id}/cancel")
def cancel_training(job_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    job = conn.execute("SELECT status FROM train_job WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ApiError("unknown_job", f"任务 {job_id} 不存在", "刷新", 404)
    if job["status"] != "queued":
        raise ApiError("not_cancellable", f"任务状态为 {job['status']}，无法取消", "只能取消排队中的任务", 409)
    with tx(conn):
        conn.execute("UPDATE train_job SET status = 'cancelled' WHERE id = ?", (job_id,))
        record(conn, actor="web", action="train.cancel", entity="train_job", entity_id=job_id)
    return {"id": job_id, "status": "cancelled"}


@router.post("/models/{model_id}/rollback")
def rollback(model_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """回滚：当前 assist 降为 disabled，上一个版本升回 assist，绑定同步。"""
    current = conn.execute(
        "SELECT version_no FROM model_version WHERE model_id = ? AND status = 'assist'"
        " ORDER BY version_no DESC LIMIT 1",
        (model_id,),
    ).fetchone()
    if current is None:
        raise ApiError("no_active", "该模型没有 assist 版本", "先发布一个版本", 409)

    previous = conn.execute(
        "SELECT version_no FROM model_version WHERE model_id = ? AND version_no < ?"
        " AND status = 'disabled' ORDER BY version_no DESC LIMIT 1",
        (model_id, current["version_no"]),
    ).fetchone()
    if previous is None:
        raise ApiError("no_previous", "没有可回退的版本", "先发布过旧版本才能回滚", 409)

    with tx(conn):
        conn.execute(
            "UPDATE model_version SET status = 'disabled' WHERE model_id = ? AND version_no = ?",
            (model_id, current["version_no"]),
        )
        conn.execute(
            "UPDATE model_version SET status = 'assist' WHERE model_id = ? AND version_no = ?",
            (model_id, previous["version_no"]),
        )
        conn.execute(
            "UPDATE binding SET stage = 'assist' WHERE model_id = ? AND active_to IS NULL",
            (model_id,),
        )
        record(conn, actor="web", action="model.rollback", entity="model", entity_id=model_id,
               payload={"from": current["version_no"], "to": previous["version_no"]})
    return {"model_id": model_id, "from": current["version_no"], "to": previous["version_no"]}
