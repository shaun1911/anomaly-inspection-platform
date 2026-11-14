"""盲判抽检（L4 验收）。

规则：
- 抽样时系统结论入库但不展示；判完才允许看系统结论；
- 全部判完才能关闭；人判 NG 少于门槛时需 force 才能低置信关批；
- 关闭时冻结指标 + 三方签字，事后不可改。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..audit import record
from ..settings import get_value
from ..store import tx
from .deps import get_conn
from .errors import ApiError

router = APIRouter(prefix="/api/blind", tags=["blind"])

WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")


class BatchIn(BaseModel):
    week: str
    sample_size: int = 300
    code: str | None = None
    seed: str = "default"
    sampled_by: str = "web"
    note: str | None = None


class JudgeIn(BaseModel):
    human_label: str
    judge: str


class CloseIn(BaseModel):
    signed_quality: str
    signed_line: str
    signed_tech: str
    force: bool = False


@router.post("/batches", status_code=201)
def create_batch(body: BatchIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    week = body.week.strip()
    if not WEEK_RE.match(week):
        raise ApiError("bad_week", "周次格式应为 2026-W46", "按 ISO 周填写", 400)
    if body.sample_size < 1 or body.sample_size > 1000:
        raise ApiError("bad_size", "抽样数应在 1–1000", "调整抽样数", 400)

    where = " WHERE 1=1"
    params: list[object] = []
    if body.code:
        where += " AND j.code = ?"
        params.append(body.code)

    rows = conn.execute(
        "SELECT r.id, r.label, j.part_no FROM inference_result r"
        " JOIN inference_job j ON j.id = r.job_id" + where +
        " ORDER BY random() LIMIT ?",
        params + [body.sample_size],
    ).fetchall()
    if not rows:
        raise ApiError("no_samples", "没有可抽样的判定", "先积累判定再抽样", 409)

    try:
        with tx(conn):
            cur = conn.execute(
                "INSERT INTO blind_batch (week, seed, sampled_by, note) VALUES (?, ?, ?, ?)",
                (week, body.seed, body.sampled_by, body.note),
            )
            batch_id = int(cur.lastrowid)
            for r in rows:
                conn.execute(
                    "INSERT INTO blind_item (batch_id, result_id, part_no, system_label)"
                    " VALUES (?, ?, ?, ?)",
                    (batch_id, r["id"], r["part_no"], r["label"]),
                )
            record(conn, actor=body.sampled_by, action="blind.create", entity="blind_batch",
                   entity_id=batch_id, payload={"week": week, "size": len(rows)})
    except sqlite3.IntegrityError as exc:
        raise ApiError("week_exists", f"周次 {week} 已有批次", "换周次或查看已有批次", 409) from exc
    return {"id": batch_id, "week": week, "sampled": len(rows)}


@router.get("/batches")
def list_batches(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    rows = conn.execute(
        "SELECT b.*, (SELECT count(*) FROM blind_item i WHERE i.batch_id = b.id) total,"
        " (SELECT count(*) FROM blind_item i WHERE i.batch_id = b.id AND i.human_label IS NOT NULL) judged"
        " FROM blind_batch b ORDER BY b.id DESC"
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["metrics"] = json.loads(r["metrics_json"]) if r["metrics_json"] else None
        item.pop("metrics_json", None)
        out.append(item)
    return out


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    b = conn.execute("SELECT * FROM blind_batch WHERE id = ?", (batch_id,)).fetchone()
    if b is None:
        raise ApiError("batch_not_found", f"批次 {batch_id} 不存在", "刷新", 404)
    closed = b["status"] == "closed"
    rows = conn.execute(
        "SELECT i.id, i.part_no, i.human_label, i.judged_by, i.system_label, i.result_id"
        " FROM blind_item i WHERE i.batch_id = ? ORDER BY i.id",
        (batch_id,),
    ).fetchall()
    items = []
    for r in rows:
        item = {"id": r["id"], "part_no": r["part_no"], "human_label": r["human_label"],
                "judged_by": r["judged_by"], "image_url": f"/api/blind/items/{r['id']}/image"}
        if closed:  # 关批后才揭盲
            item["system_label"] = r["system_label"]
        items.append(item)
    out = dict(b)
    out["metrics"] = json.loads(b["metrics_json"]) if b["metrics_json"] else None
    out.pop("metrics_json", None)
    out["items"] = items
    out["judged"] = sum(1 for i in items if i["human_label"])
    out["total"] = len(items)
    return out


@router.post("/items/{item_id}/judge")
def judge(item_id: int, body: JudgeIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if body.human_label not in ("ok", "ng", "gray"):
        raise ApiError("bad_label", "人判结论只能是 ok/gray/ng", "重选", 400)
    row = conn.execute(
        "SELECT i.id, b.status FROM blind_item i JOIN blind_batch b ON b.id = i.batch_id"
        " WHERE i.id = ?",
        (item_id,),
    ).fetchone()
    if row is None:
        raise ApiError("item_not_found", f"抽样项 {item_id} 不存在", "刷新", 404)
    if row["status"] != "open":
        raise ApiError("batch_closed", "批次已关闭，不能再判", "刷新", 409)
    with tx(conn):
        conn.execute(
            "UPDATE blind_item SET human_label = ?, judged_by = ? WHERE id = ?",
            (body.human_label, body.judge, item_id),
        )
    return {"id": item_id, "human_label": body.human_label}


@router.get("/items/{item_id}/image")
def item_image(item_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> FileResponse:
    row = conn.execute(
        "SELECT r.crop_path FROM blind_item i JOIN inference_result r ON r.id = i.result_id"
        " WHERE i.id = ?",
        (item_id,),
    ).fetchone()
    if row is None:
        raise ApiError("item_not_found", f"抽样项 {item_id} 不存在", "刷新", 404)
    path = Path(row["crop_path"]).resolve()
    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    if not str(path).startswith(str(db_file.parent)):
        raise ApiError("image_outside_root", "裁片路径不在数据目录内", "检查存储", 403)
    if not path.exists():
        raise ApiError("image_missing", "裁片文件已不存在", "重新抽样", 404)
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


@router.post("/batches/{batch_id}/close")
def close_batch(batch_id: int, body: CloseIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    b = conn.execute("SELECT * FROM blind_batch WHERE id = ?", (batch_id,)).fetchone()
    if b is None:
        raise ApiError("batch_not_found", f"批次 {batch_id} 不存在", "刷新", 404)
    if b["status"] == "closed":
        raise ApiError("already_closed", "批次已关闭", "查看指标", 409)
    for label, name in (("signed_quality", "质量"), ("signed_line", "产线"), ("signed_tech", "技术")):
        if not getattr(body, label).strip():
            raise ApiError("signoff_required", f"缺少{name}签字", "补齐三方签字", 400)

    rows = conn.execute(
        "SELECT human_label, system_label FROM blind_item WHERE batch_id = ?", (batch_id,)
    ).fetchall()
    total = len(rows)
    judged = sum(1 for r in rows if r["human_label"])
    if judged < total:
        raise ApiError("not_all_judged", f"还有 {total - judged} 件没判", "判完再关批", 409)

    human_ng = sum(1 for r in rows if r["human_label"] == "ng")
    human_ok = sum(1 for r in rows if r["human_label"] == "ok")
    missed = sum(1 for r in rows if r["human_label"] == "ng" and r["system_label"] != "ng")
    overkill = sum(1 for r in rows if r["system_label"] == "ng" and r["human_label"] == "ok")
    gray = sum(1 for r in rows if r["system_label"] == "gray")

    min_ng = int(get_value(conn, "sampling.min_ng"))
    if human_ng < min_ng and not body.force:
        raise ApiError(
            "low_ng",
            f"人判 NG 只有 {human_ng} 件，少于门槛 {min_ng}",
            "延长抽样或加 force 低置信关批",
            409,
        )

    metrics = {
        "total": total,
        "human_ng": human_ng,
        "human_ok": human_ok,
        "missed": missed,
        "recall": round((human_ng - missed) / human_ng, 4) if human_ng else None,
        "overkill": overkill,
        "overkill_rate": round(overkill / human_ok, 4) if human_ok else None,
        "gray": gray,
        "gray_rate": round(gray / total, 4) if total else None,
        "min_ng": min_ng,
        "low_confidence": human_ng < min_ng,
    }
    with tx(conn):
        conn.execute(
            "UPDATE blind_batch SET status = 'closed', metrics_json = ?,"
            " signed_quality = ?, signed_line = ?, signed_tech = ?,"
            " signed_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (json.dumps(metrics, ensure_ascii=False), body.signed_quality, body.signed_line,
             body.signed_tech, batch_id),
        )
        record(conn, actor=body.signed_quality, action="blind.close", entity="blind_batch",
               entity_id=batch_id, payload=metrics)
    return {"id": batch_id, "metrics": metrics}
