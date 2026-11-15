"""训练与发布（P3a）。

真实训练由 anomalib 承担；这里先用确定性的假训练器把状态机与接口跑通：
创建任务 → 产出候选版本（带指标）→ 人工发布 → 可回滚。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from ..audit import record
from ..inference.onnx import PredictorUnavailable, build_predictor, load_session
from ..training.export import ExportUnavailable, default_export_path, export_stub
from ..inference.service import GATE_MESSAGES, check_gate, label_for
from ..settings import gate_config, get_value
from ..serving.cache import cache
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


class ExportIn(BaseModel):
    backend: str = "stub"


@router.post("/models/{model_id}/versions/{version_no}/export")
def export_onnx(
    model_id: int, version_no: int, body: ExportIn,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """把版本导出为 ONNX 并自动挂载。

    backend=stub：生成真实的亮度均值图（演示/链路验证）；
    真实模型请用 anomalib 在训练机导出后走「挂 ONNX」接口。
    """
    version = conn.execute(
        "SELECT onnx_path FROM model_version WHERE model_id = ? AND version_no = ?",
        (model_id, version_no),
    ).fetchone()
    if version is None:
        raise ApiError("version_not_found", f"版本 v{version_no} 不存在", "刷新", 404)
    if version["onnx_path"]:
        return {"skipped": True, "onnx_path": version["onnx_path"]}

    model = conn.execute("SELECT code FROM model WHERE id = ?", (model_id,)).fetchone()
    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    target = default_export_path(db_file.parent, model["code"], version_no)

    if body.backend != "stub":
        raise ApiError(
            "backend_unsupported", "服务端只支持 stub 导出",
            "真实模型请在训练机导出后用「挂 ONNX」", 400,
        )

    try:
        export_stub(target)
    except ExportUnavailable as exc:
        raise ApiError("export_unavailable", str(exc), "pip install onnx 或改在训练机导出", 503) from exc
    except Exception as exc:  # noqa: BLE001
        raise ApiError("export_failed", f"导出失败: {exc}", "检查磁盘与依赖", 500) from exc

    with tx(conn):
        conn.execute(
            "UPDATE model_version SET onnx_path = ? WHERE model_id = ? AND version_no = ?",
            (str(target), model_id, version_no),
        )
        record(conn, actor="web", action="model.export", entity="model_version",
               entity_id=f"{model_id}:{version_no}",
               payload={"onnx_path": str(target), "backend": body.backend})
    cache.unload(f"{model_id}:{version_no}", force=True)
    return {"model_id": model_id, "version_no": version_no, "onnx_path": str(target),
            "backend": body.backend, "skipped": False}


@router.post("/models/{model_id}/versions/{version_no}/smoke")
def smoke(
    model_id: int,
    version_no: int,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """冒烟：用候选版本试判一张图，不写生产结果、不动绑定。"""
    version = conn.execute(
        "SELECT id, status FROM model_version WHERE model_id = ? AND version_no = ?",
        (model_id, version_no),
    ).fetchone()
    if version is None:
        raise ApiError("version_not_found", f"版本 v{version_no} 不存在", "刷新", 404)

    config = conn.execute(
        "SELECT roi_rect FROM config_rev WHERE model_version_id = ? ORDER BY rev DESC LIMIT 1",
        (version["id"],),
    ).fetchone()
    threshold = conn.execute(
        "SELECT th_lo, th_hi FROM threshold_rev WHERE model_version_id = ?"
        " ORDER BY rev DESC LIMIT 1",
        (version["id"],),
    ).fetchone()
    th_lo, th_hi = (threshold["th_lo"], threshold["th_hi"]) if threshold else (0.45, 0.60)

    payload = file.file.read()
    if not payload:
        raise ApiError("empty_image", "上传内容为空", "重新选择", 400)

    import hashlib

    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    target_dir = db_file.parent / "smoke"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{hashlib.sha256(payload).hexdigest()}.png"
    path.write_bytes(payload)

    gate = check_gate(path, gate_config(conn))
    if gate is not None:
        message, action = GATE_MESSAGES.get(gate, ("裁片不合格", "重新取图"))
        return {"passed": False, "gate": gate, "message": message, "action": action}

    onnx_path = conn.execute(
        "SELECT onnx_path FROM model_version WHERE model_id = ? AND version_no = ?",
        (model_id, version_no),
    ).fetchone()["onnx_path"]
    session = None
    if onnx_path:
        try:
            session = load_session(onnx_path, providers="cpu")
        except PredictorUnavailable as exc:
            raise ApiError("predictor_unavailable", str(exc), "安装 onnxruntime", 503) from exc
    predictor = build_predictor(
        session,
        input_range=get_value(conn, "infer.onnx_input_range"),
        aggregate=get_value(conn, "infer.onnx_aggregate"),
    )
    pred = predictor.predict(path)
    label = label_for(pred.score, th_lo, th_hi)
    with tx(conn):
        record(conn, actor="web", action="model.smoke", entity="model_version",
               entity_id=f"{model_id}:{version_no}",
               payload={"score": pred.score, "label": label})
    return {
        "passed": True,
        "score": pred.score,
        "label": label,
        "th_lo": th_lo,
        "th_hi": th_hi,
        "roi_rect": json.loads(config["roi_rect"]) if config else None,
        "version_status": version["status"],
    }


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
