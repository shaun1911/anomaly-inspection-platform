"""推理入口（T1-3）：提交、查询、反馈。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from PIL import Image

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from pydantic import BaseModel

from .. import whitelist
from ..inference.service import GATE_MESSAGES, FakePredictor, check_gate, process_job
from ..settings import gate_config, get_value
from ..storage import is_locked
from ..inference.onnx import PredictorUnavailable, build_predictor
from ..serving.cache import acquire_and_audit, cache
from ..store import tx
from .deps import get_conn
from .errors import ApiError

router = APIRouter(tags=["infer"])

_BATCH_RE = re.compile(r"^[A-Za-z0-9._\-/]+$")


def _normalize_batch(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if len(text) > 64:
        raise ApiError("batch_too_long", "批次号超过 64 字符", "核对批次号", 400)
    if not _BATCH_RE.match(text):
        raise ApiError("batch_invalid", "批次号只能包含字母、数字、. _ - /", "核对批次号", 400)
    return text

DEFAULT_TH = (0.4, 0.7)


def _crop_dir(db_path: Path) -> Path:
    path = db_path.parent / "crops"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve(conn: sqlite3.Connection, code: str) -> tuple[int, int, float, float]:
    """返回 (model_version_id, roi_rev, th_lo, th_hi)。"""
    row = conn.execute(
        "SELECT b.model_id, p.active FROM product_code p"
        " JOIN binding b ON b.product_code_id = p.id AND b.active_to IS NULL"
        " WHERE p.code = ?",
        (code,),
    ).fetchone()
    if row is None:
        raise ApiError("unknown_code", f"未知或未绑定的编码 {code}", "核对标签或让技师绑定", 422)

    version = conn.execute(
        "SELECT id FROM model_version WHERE model_id = ? AND status IN ('shadow','assist')"
        " ORDER BY version_no DESC LIMIT 1",
        (row["model_id"],),
    ).fetchone()
    if version is None:
        raise ApiError("no_active_version", "该模型没有可用版本", "让技师发布版本", 409)

    config = conn.execute(
        "SELECT rev FROM config_rev WHERE model_version_id = ? ORDER BY rev DESC LIMIT 1",
        (version["id"],),
    ).fetchone()
    if config is None:
        raise ApiError("no_config", "该版本没有 ROI 配置", "让技师补配置", 409)

    threshold = conn.execute(
        "SELECT th_lo, th_hi FROM threshold_rev WHERE model_version_id = ? AND roi_rev = ?"
        " ORDER BY rev DESC LIMIT 1",
        (version["id"], config["rev"]),
    ).fetchone()
    th_lo, th_hi = (threshold["th_lo"], threshold["th_hi"]) if threshold else DEFAULT_TH
    return version["id"], config["rev"], th_lo, th_hi


@router.post("/infer", status_code=202)
def submit(
    code: str = Form(...),
    station: str = Form("unknown"),
    part_no: str | None = Form(None),
    batch_no: str | None = Form(None),
    image: UploadFile = File(...),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    station_token: str | None = Header(None, alias="X-Station-Token"),
    sync: bool = Query(False, description="同步返回完整结果（HTTP 200），供产线客户端一次往返"),
    response: Response = None,  # type: ignore[assignment]
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    if is_locked():
        raise ApiError("maintenance", "存储迁移中，暂停推图", "等迁移完成后重试", 503)
    expected_token = get_value(conn, "station.token")
    if expected_token and station_token != expected_token:
        raise ApiError("bad_station_token", "站位令牌缺失或错误", "检查客户端令牌配置", 401)
    batch = _normalize_batch(batch_no)
    part = (part_no or "").strip() or None

    if get_value(conn, "infer.require_part_no") and not part:
        raise ApiError("missing_part_no", "缺少件号 part_no", "客户端必须上报件号", 400)
    if get_value(conn, "infer.require_batch_no") and not batch:
        raise ApiError("missing_batch_no", "缺少批次 batch_no", "客户端必须上报批次", 400)

    if not whitelist.is_allowed(code):
        raise ApiError("not_in_shift", f"编码 {code} 不在本班白名单", "联系技师或换件", 403)

    payload = image.file.read()
    if not payload:
        raise ApiError("empty_image", "上传内容为空", "重新拍照", 400)

    key = idempotency_key or hashlib.sha256(payload).hexdigest()
    existing = conn.execute(
        "SELECT id, status FROM inference_job WHERE idempotency_key = ?", (key,)
    ).fetchone()
    if existing is not None:
        payload = _job_payload(conn, existing["id"]) or {
            "job_id": existing["id"], "status": existing["status"], "result": None
        }
        payload["duplicate"] = True
        if sync:
            response.status_code = 200
        return payload

    sha = hashlib.sha256(payload).hexdigest()
    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    crop_path = _crop_dir(db_file) / f"{sha}.png"
    crop_path.write_bytes(payload)

    reason = check_gate(crop_path, gate_config(conn))
    if reason is not None:
        message, action = GATE_MESSAGES.get(reason, ("裁片不合格", "重新取图"))
        raise ApiError(reason, message, action, 422)

    version_id, roi_rev, th_lo, th_hi = _resolve(conn, code)
    ver = conn.execute(
        "SELECT model_id, version_no, onnx_path FROM model_version WHERE id = ?",
        (version_id,),
    ).fetchone()
    cache.configure(
        get_value(conn, "serving.cache_ttl_min"), get_value(conn, "serving.cache_max")
    )
    try:
        session, _ = acquire_and_audit(
            conn, ver["model_id"], ver["version_no"], ver["onnx_path"], station
        )
    except PredictorUnavailable as exc:
        raise ApiError(
            "predictor_unavailable", str(exc),
            "安装 onnxruntime 或先把版本设为假预测器", 503,
        ) from exc
    except Exception as exc:  # CacheFull 或加载失败
        raise ApiError("model_load_failed", str(exc), "稍后重试或联系技师", 503) from exc

    predictor = build_predictor(
        session,
        input_range=get_value(conn, "infer.onnx_input_range"),
        aggregate=get_value(conn, "infer.onnx_aggregate"),
    )
    tolerance = get_value(conn, "infer.crop_size_tolerance")
    if tolerance:
        roi = conn.execute(
            "SELECT roi_rect FROM config_rev WHERE model_version_id = ? AND rev = ?",
            (version_id, roi_rev),
        ).fetchone()
        if roi is not None:
            x1, y1, x2, y2 = json.loads(roi["roi_rect"])
            with Image.open(crop_path) as img:
                cw, ch = img.size
            if abs(cw - (x2 - x1)) > tolerance or abs(ch - (y2 - y1)) > tolerance:
                raise ApiError(
                    "crop_roi_mismatch",
                    f"裁片 {cw}x{ch} 与 ROI {x2 - x1}x{y2 - y1} 不一致",
                    "客户端需按 ROI 裁剪后再上传",
                    422,
                )

    with tx(conn):
        st = conn.execute("SELECT id FROM station WHERE name = ?", (station,)).fetchone()
        if st is None:
            st_cur = conn.execute("INSERT INTO station (name) VALUES (?)", (station,))
            station_id = int(st_cur.lastrowid)
        else:
            station_id = int(st["id"])
        cur = conn.execute(
            "INSERT INTO inference_job"
            " (code, part_no, batch_no, batch_source, station_id, idempotency_key, status)"
            " VALUES (?, ?, ?, ?, ?, ?, 'queued')",
            (code, part, batch, "station" if batch else None, station_id, key),
        )
        job_id = int(cur.lastrowid)

    process_job(
        conn,
        job_id=job_id,
        model_version_id=version_id,
        crop_path=crop_path,
        predictor=predictor,
        th_lo=th_lo,
        th_hi=th_hi,
    )
    payload = _job_payload(conn, job_id) or {"job_id": job_id, "status": "done", "result": None}
    payload.update({"model_version_id": version_id, "roi_rev": roi_rev})
    if sync:
        response.status_code = 200
    return payload


def _job_payload(conn: sqlite3.Connection, job_id: int) -> dict:
    job = conn.execute("SELECT * FROM inference_job WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        return None
    result = conn.execute(
        "SELECT id, score, label, boxes_json FROM inference_result WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    return {
        "job_id": job_id,
        "status": job["status"],
        "error_code": job["error_code"],
        "code": job["code"],
        "part_no": job["part_no"],
        "batch_no": job["batch_no"],
        "result": {
            "id": result["id"],
            "score": result["score"],
            "label": result["label"],
            "boxes": result["boxes_json"],
        }
        if result
        else None,
    }


@router.get("/infer/{job_id}")
def get_job(job_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    payload = _job_payload(conn, job_id)
    if payload is None:
        raise ApiError("job_not_found", f"任务 {job_id} 不存在", "刷新列表", 404)
    return payload


class FeedbackIn(BaseModel):
    result_id: int
    verdict: str
    note: str | None = None


@router.post("/infer/feedback", status_code=201)
def feedback(body: FeedbackIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if body.verdict not in ("ok", "ng"):
        raise ApiError("bad_verdict", "verdict 只能是 ok/ng", "重选", 400)
    exists = conn.execute(
        "SELECT 1 FROM inference_result WHERE id = ?", (body.result_id,)
    ).fetchone()
    if exists is None:
        raise ApiError("result_not_found", f"结果 {body.result_id} 不存在", "刷新后重试", 404)
    with tx(conn):
        conn.execute(
            "INSERT OR REPLACE INTO feedback (result_id, verdict, note, source)"
            " VALUES (?, ?, ?, 'online')",
            (body.result_id, body.verdict, body.note),
        )
    return {"result_id": body.result_id, "verdict": body.verdict}
