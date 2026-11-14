"""推理入口（T1-3）：提交、查询、反馈。"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from pydantic import BaseModel

from .. import whitelist
from ..inference.service import GATE_MESSAGES, FakePredictor, check_gate, process_job
from ..settings import gate_config
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
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    batch = _normalize_batch(batch_no)
    part = (part_no or "").strip() or None

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
        return {"job_id": existing["id"], "status": existing["status"], "duplicate": True}

    sha = hashlib.sha256(payload).hexdigest()
    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    crop_path = _crop_dir(db_file) / f"{sha}.png"
    crop_path.write_bytes(payload)

    reason = check_gate(crop_path, gate_config(conn))
    if reason is not None:
        message, action = GATE_MESSAGES.get(reason, ("裁片不合格", "重新取图"))
        raise ApiError(reason, message, action, 422)

    version_id, roi_rev, th_lo, th_hi = _resolve(conn, code)

    with tx(conn):
        st = conn.execute("SELECT id FROM station WHERE name = ?", (station,)).fetchone()
        if st is None:
            st_cur = conn.execute("INSERT INTO station (name) VALUES (?)", (station,))
            station_id = int(st_cur.lastrowid)
        else:
            station_id = int(st["id"])
        cur = conn.execute(
            "INSERT INTO inference_job"
            " (code, part_no, batch_no, station_id, idempotency_key, status)"
            " VALUES (?, ?, ?, ?, ?, 'queued')",
            (code, part, batch, station_id, key),
        )
        job_id = int(cur.lastrowid)

    process_job(
        conn,
        job_id=job_id,
        model_version_id=version_id,
        crop_path=crop_path,
        predictor=FakePredictor(),
        th_lo=th_lo,
        th_hi=th_hi,
    )
    return {"job_id": job_id, "status": "done", "model_version_id": version_id, "roi_rev": roi_rev}


@router.get("/infer/{job_id}")
def get_job(job_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    job = conn.execute("SELECT * FROM inference_job WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ApiError("job_not_found", f"任务 {job_id} 不存在", "刷新列表", 404)
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
