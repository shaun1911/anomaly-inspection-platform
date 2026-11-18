"""误判上报与处理。

工位发现服务端结论错误时上报；后台接受则改判（可同时生成判例），
拒绝则保留原结论。所有动作写审计。
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict

from .. import cases as cases_mod
from ..audit import record
from ..settings import get_value
from ..store import tx
from .deps import get_conn
from .errors import ApiError

router = APIRouter(tags=["feedback"])
admin_router = APIRouter(prefix="/api", tags=["feedback"])


def _check_station(conn: sqlite3.Connection, token: str | None) -> None:
    expected = get_value(conn, "station.token")
    if expected and token != expected:
        raise ApiError("bad_station_token", "站位令牌缺失或错误", "检查客户端令牌配置", 401)


class MisjudgeIn(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "result_id": 123, "expected_verdict": "ok", "reason_code": "误报",
        "note": "现场复判可接受", "station": "S1", "reported_by": "张三",
    }]})

    result_id: int
    expected_verdict: str
    reason_code: str | None = None
    note: str | None = None
    station: str | None = None
    reported_by: str | None = None


@router.post("/station/misjudge", status_code=201)
def report_misjudge(
    body: MisjudgeIn,
    station_token: str | None = Header(None, alias="X-Station-Token"),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    _check_station(conn, station_token)
    if body.expected_verdict not in ("ok", "ng"):
        raise ApiError("bad_verdict", "expected_verdict 只能是 ok/ng", "重选", 400)

    result = conn.execute(
        "SELECT r.id, r.label, r.confirmed_by, r.review_status, j.code, j.part_no,"
        " j.batch_no, j.station_id FROM inference_result r JOIN inference_job j ON j.id = r.job_id"
        " WHERE r.id = ?",
        (body.result_id,),
    ).fetchone()
    if result is None:
        raise ApiError("result_not_found", f"结果 {body.result_id} 不存在", "刷新后重试", 404)

    station = body.station
    if not station and result["station_id"]:
        row = conn.execute("SELECT name FROM station WHERE id = ?", (result["station_id"],)).fetchone()
        station = row["name"] if row else None

    existing = conn.execute(
        "SELECT id, status FROM feedback WHERE result_id = ? AND source = 'online'",
        (body.result_id,),
    ).fetchone()
    if existing is not None and existing["status"] == "open":
        raise ApiError("feedback_open", "该结果已有一条待处理的误判上报", "等后台处理或撤回", 409)

    with tx(conn):
        if existing is None:
            cur = conn.execute(
                "INSERT INTO feedback (result_id, verdict, note, source, station, reported_by,"
                " reason_code, status) VALUES (?, ?, ?, 'online', ?, ?, ?, 'open')",
                (body.result_id, body.expected_verdict, body.note, station,
                 body.reported_by, body.reason_code),
            )
            feedback_id = int(cur.lastrowid)
        else:
            feedback_id = int(existing["id"])
            conn.execute(
                "UPDATE feedback SET verdict = ?, note = ?, station = ?, reported_by = ?,"
                " reason_code = ?, status = 'open', handled_by = NULL, handled_at = NULL,"
                " resolution = NULL, created_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                (body.expected_verdict, body.note, station, body.reported_by,
                 body.reason_code, feedback_id),
            )
        record(conn, actor=body.reported_by or station or "station", action="feedback.report",
               entity="feedback", entity_id=feedback_id,
               payload={"result_id": body.result_id, "verdict": body.expected_verdict,
                        "reason": body.reason_code})
    return {"id": feedback_id, "result_id": body.result_id,
            "expected_verdict": body.expected_verdict, "status": "open"}


@admin_router.get("/feedback")
def list_feedback(
    status: str = "open",
    code: str | None = None,
    station: str | None = None,
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    where = ["f.source = 'online'"]
    params: list[object] = []
    if status and status != "all":
        where.append("f.status = ?")
        params.append(status)
    if code:
        where.append("j.code = ?")
        params.append(code)
    if station:
        where.append("f.station = ?")
        params.append(station)
    where_sql = " WHERE " + " AND ".join(where)
    total = conn.execute(
        "SELECT count(*) c FROM feedback f JOIN inference_result r ON r.id = f.result_id"
        " JOIN inference_job j ON j.id = r.job_id" + where_sql,
        params,
    ).fetchone()["c"]
    rows = conn.execute(
        "SELECT f.id, f.result_id, f.verdict expected_verdict, f.reason_code, f.note,"
        " f.status, f.station, f.reported_by, f.handled_by, f.handled_at, f.resolution,"
        " f.created_at, r.score, r.label system_label, r.review_status,"
        " j.code, j.part_no, j.batch_no"
        " FROM feedback f JOIN inference_result r ON r.id = f.result_id"
        " JOIN inference_job j ON j.id = r.job_id" + where_sql +
        " ORDER BY f.created_at DESC LIMIT ? OFFSET ?",
        params + [max(1, min(limit, 200)), max(0, offset)],
    ).fetchall()
    summary = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, count(*) c FROM feedback WHERE source = 'online' GROUP BY status"
    ).fetchall()}
    items = []
    for r in rows:
        item = dict(r)
        item["image_url"] = f"/results/{r['result_id']}/image"
        items.append(item)
    return {"items": items, "total": total, "summary": summary,
            "limit": limit, "offset": offset}


class HandleIn(BaseModel):
    action: str                    # accept | reject
    note: str | None = None
    handled_by: str = "admin"
    create_case: bool = False
    verdict: str | None = None     # accept 时可覆盖上报结论


@admin_router.post("/feedback/{feedback_id}/handle")
def handle_feedback(
    feedback_id: int, body: HandleIn, conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    if body.action not in ("accept", "reject"):
        raise ApiError("bad_action", "action 只能是 accept/reject", "重选", 400)
    fb = conn.execute(
        "SELECT f.*, f.verdict AS expected_verdict, r.label, r.crop_path, r.model_version_id,"
        " j.code, j.part_no, j.batch_no"
        " FROM feedback f JOIN inference_result r ON r.id = f.result_id"
        " JOIN inference_job j ON j.id = r.job_id WHERE f.id = ?",
        (feedback_id,),
    ).fetchone()
    if fb is None:
        raise ApiError("feedback_not_found", f"误判上报 {feedback_id} 不存在", "刷新", 404)
    if fb["status"] != "open":
        raise ApiError("feedback_closed", "该上报已处理", "刷新列表", 409)

    if body.action == "reject":
        with tx(conn):
            conn.execute(
                "UPDATE feedback SET status = 'rejected', handled_by = ?,"
                " handled_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), resolution = ? WHERE id = ?",
                (body.handled_by, body.note, feedback_id),
            )
            record(conn, actor=body.handled_by, action="feedback.handle", entity="feedback",
                   entity_id=feedback_id, payload={"action": "reject", "note": body.note})
        return {"id": feedback_id, "status": "rejected"}

    verdict = body.verdict or fb["expected_verdict"]
    if verdict not in ("ok", "ng"):
        raise ApiError("bad_verdict", "verdict 只能是 ok/ng", "重选", 400)
    note = body.note or fb["note"]
    case_id = None
    case_error = None
    if body.create_case and fb["crop_path"]:
        try:
            case_id = cases_mod.create_case(
                conn,
                product_code=fb["code"],
                crop_path=fb["crop_path"],
                verdict=verdict,
                adjudicator=body.handled_by,
                reason=note or fb["reason_code"],
                source="result",
                result_id=fb["result_id"],
                model_version_id=fb["model_version_id"],
                part_no=fb["part_no"],
            )
        except cases_mod.DuplicateCase as exc:
            case_error = str(exc)
    with tx(conn):
        conn.execute(
            "UPDATE inference_result SET label = ?, confirmed_by = ?, confirmed_at ="
            " strftime('%Y-%m-%dT%H:%M:%fZ','now'), confirm_note = ?, review_status = 'done',"
            " claimed_by = COALESCE(claimed_by, ?),"
            " claimed_at = COALESCE(claimed_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')) WHERE id = ?",
            (verdict, body.handled_by, note, body.handled_by, fb["result_id"]),
        )
        conn.execute(
            "UPDATE feedback SET status = 'accepted', handled_by = ?,"
            " handled_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), resolution = ? WHERE id = ?",
            (body.handled_by, note, feedback_id),
        )
        record(conn, actor=body.handled_by, action="review.confirm",
               entity="inference_result", entity_id=fb["result_id"],
               payload={"verdict": verdict, "note": note, "source": "misjudge", "feedback_id": feedback_id})
        record(conn, actor=body.handled_by, action="feedback.handle", entity="feedback",
               entity_id=feedback_id, payload={"action": "accept", "verdict": verdict,
                                              "case_id": case_id, "note": note})
    return {"id": feedback_id, "status": "accepted", "result_id": fb["result_id"],
            "verdict": verdict, "case_id": case_id, "case_error": case_error}
