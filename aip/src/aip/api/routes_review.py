"""复核队列（状态机版）。

设计要点：
- 一条队列项 = 一个"件"（code + part_no + 时间窗），不是一条结果；
- 领取（claim）后才允许确认，领取 15 分钟未处理自动可被他人接手；
- 默认最旧优先，避免老件被新件淹没；
- 批量只允许"领取/暂缓"，确认必须逐件。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..audit import record
from ..store import tx
from .deps import get_conn
from .errors import ApiError

router = APIRouter(prefix="/review", tags=["review"])

CLAIM_TTL_MINUTES = 15
PENDING_LABELS = ("ng", "gray")
OPEN_STATES = ("pending", "claimed")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _is_stale(claimed_at: str | None) -> bool:
    if not claimed_at:
        return True
    try:
        ts = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - ts > timedelta(minutes=CLAIM_TTL_MINUTES)


@router.get("/queue")
def queue(
    code: str | None = None,
    label: str | None = None,
    station: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    sort: str = "oldest",
    group_by: str = "part",
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    if label is not None and label not in ("ng", "gray"):
        raise ApiError("bad_label", "label 只能是 ng/gray", "重选", 400)
    if sort not in ("oldest", "newest", "score_desc", "score_asc"):
        raise ApiError("bad_sort", "sort 取值不合法", "重选", 400)
    if group_by not in ("part", "result"):
        raise ApiError("bad_group", "group_by 只能是 part/result", "重选", 400)

    where = [
        "r.label IN ('ng','gray')",
        "r.review_status IN ('pending','claimed')",
        "r.confirmed_at IS NULL",
    ]
    params: list[object] = []
    if code:
        where.append("j.code = ?")
        params.append(code)
    if label:
        where.append("r.label = ?")
        params.append(label)
    if station:
        where.append("s.name = ?")
        params.append(station)
    if min_score is not None:
        where.append("r.score >= ?")
        params.append(min_score)
    if max_score is not None:
        where.append("r.score <= ?")
        params.append(max_score)
    where_sql = " WHERE " + " AND ".join(where)
    joins = (
        " FROM inference_result r"
        " JOIN inference_job j ON j.id = r.job_id"
        " LEFT JOIN station s ON s.id = j.station_id"
    )

    order = {
        "oldest": "ORDER BY r.created_at ASC",
        "newest": "ORDER BY r.created_at DESC",
        "score_desc": "ORDER BY r.score DESC",
        "score_asc": "ORDER BY r.score ASC",
    }[sort]
    part_order = {
        "oldest": "ORDER BY first_at ASC",
        "newest": "ORDER BY first_at DESC",
        "score_desc": "ORDER BY max_score DESC",
        "score_asc": "ORDER BY min_score ASC",
    }[sort]

    summary = {
        "total": conn.execute("SELECT count(*) c" + joins + where_sql, params).fetchone()["c"],
        "by_code": [
            {"code": r["code"], "count": r["c"]}
            for r in conn.execute(
                "SELECT j.code, count(*) c" + joins + where_sql + " GROUP BY j.code ORDER BY c DESC",
                params,
            ).fetchall()
        ],
    }
    oldest = conn.execute(
        "SELECT min(r.created_at) m" + joins + where_sql, params
    ).fetchone()["m"]
    summary["oldest_at"] = oldest
    summary["skipped_count"] = conn.execute(
        "SELECT count(*) c FROM inference_result WHERE review_status = 'skipped'"
    ).fetchone()["c"]

    if group_by == "part":
        rows = conn.execute(
            "SELECT j.code, COALESCE(j.part_no,'-') part_no, count(*) n,"
            " min(r.score) min_score, max(r.score) max_score,"
            " min(r.created_at) first_at, group_concat(r.id) ids"
            + joins
            + where_sql
            + " GROUP BY j.code, COALESCE(j.part_no,'-')"
            + " " + part_order
            + " LIMIT ? OFFSET ?",
            params + [max(1, min(limit, 200)), max(0, offset)],
        ).fetchall()
        items = [
            {
                "kind": "part",
                "code": r["code"],
                "part_no": r["part_no"],
                "count": r["n"],
                "min_score": r["min_score"],
                "max_score": r["max_score"],
                "first_at": r["first_at"],
                "result_ids": [int(x) for x in str(r["ids"]).split(",")],
            }
            for r in rows
        ]
    else:
        rows = conn.execute(
            "SELECT r.id, r.score, r.label, r.created_at, r.review_status,"
            " r.claimed_by, r.claimed_at, j.code, j.part_no"
            + joins
            + where_sql
            + " " + order
            + " LIMIT ? OFFSET ?",
            params + [max(1, min(limit, 200)), max(0, offset)],
        ).fetchall()
        items = [dict(r) for r in rows]

    return {"summary": summary, "group_by": group_by, "items": items, "limit": limit, "offset": offset}


@router.get("/skipped")
def skipped(
    code: str | None = None,
    limit: int = 100,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """暂缓件回收站：可恢复回队列，否则会永远消失。"""
    where = ["r.review_status = 'skipped'"]
    params: list[object] = []
    if code:
        where.append("j.code = ?")
        params.append(code)
    sql = (
        "SELECT r.id, r.score, r.label, r.confirm_note reason, r.claimed_by,"
        " r.claimed_at, j.code, j.part_no"
        " FROM inference_result r JOIN inference_job j ON j.id = r.job_id"
        " WHERE " + " AND ".join(where) +
        " ORDER BY r.claimed_at DESC LIMIT ?"
    )
    rows = conn.execute(sql, params + [max(1, min(limit, 500))]).fetchall()
    return {"count": len(rows), "items": [dict(r) for r in rows]}


@router.post("/{result_id}/restore")
def restore_skipped(
    result_id: int, body: ActorIn, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    with tx(conn):
        cur = conn.execute(
            "UPDATE inference_result SET review_status = 'pending', claimed_by = NULL,"
            " claimed_at = NULL, confirm_note = NULL"
            " WHERE id = ? AND review_status = 'skipped'",
            (result_id,),
        )
        if cur.rowcount == 0:
            raise ApiError("not_skipped", "该件不在暂缓状态", "刷新回收站", 409)
        record(conn, actor=body.actor, action="review.restore", entity="inference_result",
               entity_id=result_id)
    return {"id": result_id, "restored": True}


class ActorIn(BaseModel):
    actor: str


@router.post("/{result_id}/claim")
def claim(result_id: int, body: ActorIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    row = conn.execute(
        "SELECT claimed_by, claimed_at, review_status FROM inference_result WHERE id = ?",
        (result_id,),
    ).fetchone()
    if row is None:
        raise ApiError("result_not_found", f"结果 {result_id} 不存在", "刷新", 404)
    if row["review_status"] in ("done", "skipped"):
        raise ApiError("already_closed", "该件已处理", "刷新队列", 409)
    if row["claimed_by"] and row["claimed_by"] != body.actor and not _is_stale(row["claimed_at"]):
        raise ApiError(
            "claimed_by_other",
            f"已被 {row['claimed_by']} 领取",
            "等对方释放，或 15 分钟后自动可领",
            409,
        )
    with tx(conn):
        conn.execute(
            "UPDATE inference_result SET review_status = 'claimed', claimed_by = ?,"
            " claimed_at = ? WHERE id = ?",
            (body.actor, _now(), result_id),
        )
        record(conn, actor=body.actor, action="review.claim", entity="inference_result", entity_id=result_id)
    return {"id": result_id, "claimed_by": body.actor}


@router.post("/{result_id}/release")
def release(result_id: int, body: ActorIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    with tx(conn):
        cur = conn.execute(
            "UPDATE inference_result SET review_status = 'pending', claimed_by = NULL,"
            " claimed_at = NULL WHERE id = ? AND review_status = 'claimed'",
            (result_id,),
        )
        if cur.rowcount == 0:
            raise ApiError("not_claimed", "该件不在领取状态", "刷新", 409)
        record(conn, actor=body.actor, action="review.release", entity="inference_result", entity_id=result_id)
    return {"id": result_id, "released": True}


class SkipIn(BaseModel):
    actor: str
    reason: str


@router.post("/{result_id}/skip")
def skip(result_id: int, body: SkipIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if not body.reason.strip():
        raise ApiError("reason_required", "暂缓需要写原因", "补一句原因", 400)
    with tx(conn):
        cur = conn.execute(
            "UPDATE inference_result SET review_status = 'skipped', claimed_by = ?,"
            " claimed_at = ?, confirm_note = ? WHERE id = ?"
            " AND review_status IN ('pending','claimed')",
            (body.actor, _now(), body.reason, result_id),
        )
        if cur.rowcount == 0:
            raise ApiError("already_closed", "该件已处理", "刷新队列", 409)
        record(conn, actor=body.actor, action="review.skip", entity="inference_result",
               entity_id=result_id, payload={"reason": body.reason})
    return {"id": result_id, "skipped": True}


class BatchIn(BaseModel):
    actor: str
    result_ids: list[int]


@router.post("/claim-batch")
def claim_batch(body: BatchIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    claimed, skipped = [], []
    for rid in body.result_ids:
        row = conn.execute(
            "SELECT claimed_by, claimed_at, review_status FROM inference_result WHERE id = ?",
            (rid,),
        ).fetchone()
        if row is None or row["review_status"] not in OPEN_STATES:
            skipped.append(rid)
            continue
        if row["claimed_by"] and row["claimed_by"] != body.actor and not _is_stale(row["claimed_at"]):
            skipped.append(rid)
            continue
        with tx(conn):
            conn.execute(
                "UPDATE inference_result SET review_status = 'claimed', claimed_by = ?,"
                " claimed_at = ? WHERE id = ?",
                (body.actor, _now(), rid),
            )
        claimed.append(rid)
    return {"claimed": claimed, "skipped": skipped}


class BatchSkipIn(BaseModel):
    actor: str
    reason: str
    result_ids: list[int]


@router.post("/skip-batch")
def skip_batch(body: BatchSkipIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if not body.reason.strip():
        raise ApiError("reason_required", "暂缓需要写原因", "补一句原因", 400)
    done = []
    for rid in body.result_ids:
        with tx(conn):
            cur = conn.execute(
                "UPDATE inference_result SET review_status = 'skipped', claimed_by = ?,"
                " claimed_at = ?, confirm_note = ? WHERE id = ?"
                " AND review_status IN ('pending','claimed')",
                (body.actor, _now(), body.reason, rid),
            )
        if cur.rowcount:
            done.append(rid)
    return {"skipped": done}
