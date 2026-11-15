"""服务端管理接口：概览、今日指标、模型、站位、判例、编码详情与时间线。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import csv
import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import cases as cases_mod
from .. import metrics as metrics_mod
from ..serving.cache import cache, unload_and_audit
from ..audit import record
from ..store import tx
from .deps import get_conn
from .errors import ApiError

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/overview")
def overview(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    def one(sql: str) -> int:
        return int(conn.execute(sql).fetchone()[0])

    return {
        "codes": one("SELECT count(*) FROM product_code WHERE active = 1"),
        "models": one("SELECT count(*) FROM model WHERE archived_at IS NULL"),
        "versions": one("SELECT count(*) FROM model_version"),
        "results": one("SELECT count(*) FROM inference_result"),
        "pending_review": one(
            "SELECT count(*) FROM inference_result"
            " WHERE label IN ('ng','gray') AND confirmed_at IS NULL"
        ),
        "cases": one("SELECT count(*) FROM case_item"),
        "stations": [
            dict(r)
            for r in conn.execute(
                "SELECT name, health, last_seen_at, last_config_rev FROM station ORDER BY name"
            ).fetchall()
        ],
    }


@router.get("/stats/today")
def stats_today(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    """今日判定分布。created_at 存 UTC ISO8601，用 date('now') 对齐。"""
    rows = conn.execute(
        "SELECT label, count(*) c FROM inference_result"
        " WHERE date(created_at) = date('now') GROUP BY label"
    ).fetchall()
    by_label = {r["label"]: r["c"] for r in rows}
    total = sum(by_label.values())
    pending = conn.execute(
        "SELECT count(*) c FROM inference_result"
        " WHERE label IN ('ng','gray') AND confirmed_at IS NULL"
    ).fetchone()["c"]
    return {
        "total": total,
        "ok": by_label.get("ok", 0),
        "gray": by_label.get("gray", 0),
        "ng": by_label.get("ng", 0),
        "pending_review": pending,
        "ng_rate": round((by_label.get("ng", 0) / total) if total else 0.0, 4),
        "gray_rate": round((by_label.get("gray", 0) / total) if total else 0.0, 4),
    }


@router.get("/audit/recent")
def audit_recent(
    limit: int = 10, conn: sqlite3.Connection = Depends(get_conn)
) -> list[dict]:
    rows = conn.execute(
        "SELECT id, actor, action, entity, entity_id, payload, created_at"
        " FROM audit_log ORDER BY id DESC LIMIT ?",
        (max(1, min(limit, 100)),),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/model-cache")
def model_cache(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    items = []
    for e in cache.entries():
        row = conn.execute(
            "SELECT m.code FROM model m WHERE m.id = ?", (e["model_id"],)
        ).fetchone()
        items.append({
            **e,
            "model_code": row["code"] if row else f"#{e['model_id']}",
            "fake": e["onnx_path"] is None,
        })
    return {
        "items": items,
        "count": len(items),
        "max": cache.max_models,
        "ttl_minutes": round(cache.ttl_s / 60),
        "loads": cache.loads,
        "unloads": cache.unloads,
    }


@router.post("/model-cache/{key}/unload")
def unload_model(key: str, force: bool = False, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    ok = unload_and_audit(conn, key, force=force)
    if not ok:
        raise ApiError(
            "unload_refused",
            "该模型仍被站位引用；如需强制卸载请带 force=true",
            "等站位空闲，或强制卸载",
            409,
        )
    return {"key": key, "unloaded": True, "forced": force}


@router.get("/search")
def global_search(q: str, limit: int = 5, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    term = f"%{(q or '').strip()}%"
    if not (q or "").strip():
        return {"codes": [], "parts": [], "models": []}

    codes = conn.execute(
        "SELECT p.code, f.name AS family FROM product_code p"
        " LEFT JOIN family f ON f.id = p.family_id"
        " WHERE p.code LIKE ? AND p.archived_at IS NULL ORDER BY p.code LIMIT ?",
        (term, limit),
    ).fetchall()
    parts = conn.execute(
        "SELECT part_no, code, max(batch_no) AS batch_no FROM inference_job"
        " WHERE part_no LIKE ? AND part_no IS NOT NULL"
        " GROUP BY part_no, code ORDER BY max(id) DESC LIMIT ?",
        (term, limit),
    ).fetchall()
    models = conn.execute(
        "SELECT id, code, name FROM model"
        " WHERE archived_at IS NULL AND (code LIKE ? OR name LIKE ?)"
        " ORDER BY id LIMIT ?",
        (term, term, limit),
    ).fetchall()
    return {
        "codes": [dict(r) for r in codes],
        "parts": [dict(r) for r in parts],
        "models": [dict(r) for r in models],
    }


@router.get("/metrics")
def system_metrics(conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    data_dir = db_file.parent

    assist = conn.execute(
        "SELECT m.code AS model_code, mv.version_no, mv.onnx_path, mv.dataset_id,"
        " (SELECT count(*) FROM binding b"
        "   WHERE b.model_id = m.id AND b.active_to IS NULL) AS bound_codes"
        " FROM model_version mv JOIN model m ON m.id = mv.model_id"
        " WHERE mv.status = 'assist' ORDER BY m.code"
    ).fetchall()

    entries = cache.entries()
    real = sum(1 for e in entries if not e["fake"])
    predictor = "ONNX Runtime" if real else "FakePredictor"
    note = (
        f"模型按需加载：常驻 {len(entries)} 个（ONNX {real} 个）。"
        "未挂 ONNX 的版本退回假预测器。"
    )

    return {
        "service": {
            "status": "ok",
            "version": "0.1.0",
            "uptime_s": metrics_mod.uptime(),
            "db": "ok",
            "queue_depth": 0,
        },
        "cpu": {"percent": metrics_mod.cpu_percent()},
        "memory": metrics_mod.memory(),
        "process": {"rss": metrics_mod.process_rss()},
        "disk": metrics_mod.disk(data_dir),
        "gpu": metrics_mod.gpu(),
        "models": {
            "predictor": predictor,
            "loaded": len(entries),
            "note": note,
            "items": [
                {
                    "model_code": r["model_code"],
                    "version_no": r["version_no"],
                    "onnx_path": r["onnx_path"],
                    "onnx_ready": bool(r["onnx_path"]),
                    "dataset_id": r["dataset_id"],
                    "bound_codes": r["bound_codes"],
                }
                for r in assist
            ],
        },
    }


@router.get("/models")
def list_models(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    models = conn.execute(
        "SELECT id, code, name, archived_at FROM model ORDER BY id"
    ).fetchall()
    out: list[dict] = []
    for m in models:
        versions = conn.execute(
            "SELECT version_no, status, created_at, metrics_json, dataset_id, onnx_path"
            " FROM model_version WHERE model_id = ? ORDER BY version_no DESC",
            (m["id"],),
        ).fetchall()
        families = [
            r["name"]
            for r in conn.execute(
                "SELECT DISTINCT f.name FROM binding b"
                " JOIN product_code p ON p.id = b.product_code_id"
                " JOIN family f ON f.id = p.family_id"
                " WHERE b.model_id = ? AND b.active_to IS NULL ORDER BY f.name",
                (m["id"],),
            ).fetchall()
        ]
        out.append(
            {
                "id": m["id"],
                "code": m["code"],
                "name": m["name"],
                "archived_at": m["archived_at"],
                "families": families,
                "versions": [
                    {
                        "version_no": v["version_no"],
                        "status": v["status"],
                        "created_at": v["created_at"],
                        "dataset_id": v["dataset_id"],
                        "onnx_path": v["onnx_path"],
                        "metrics": json.loads(v["metrics_json"]) if v["metrics_json"] else None,
                    }
                    for v in versions
                ],
            }
        )
    return out


@router.get("/stations")
def list_stations(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT name, health, last_seen_at, last_config_rev FROM station ORDER BY name"
        ).fetchall()
    ]


def _active_binding(conn: sqlite3.Connection, code_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT b.id, b.model_id, b.stage, b.active_from, m.code AS model_code, m.name AS model_name"
        " FROM binding b JOIN model m ON m.id = b.model_id"
        " WHERE b.product_code_id = ? AND b.active_to IS NULL",
        (code_id,),
    ).fetchone()


def _active_version(conn: sqlite3.Connection, model_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, version_no, status FROM model_version"
        " WHERE model_id = ? AND status IN ('shadow','assist')"
        " ORDER BY version_no DESC LIMIT 1",
        (model_id,),
    ).fetchone()


@router.get("/codes/{code}/detail")
def code_detail(code: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    row = conn.execute(
        "SELECT p.id, p.code, p.family_id, f.name AS family, p.part, p.seq, p.active, p.created_at"
        " FROM product_code p LEFT JOIN family f ON f.id = p.family_id WHERE p.code = ?",
        (code,),
    ).fetchone()
    if row is None:
        raise ApiError("unknown_code", f"未知编码 {code}", "核对编码或去生产页新建", 404)

    binding = _active_binding(conn, row["id"])
    version = _active_version(conn, binding["model_id"]) if binding else None

    config = threshold = None
    if version:
        config = conn.execute(
            "SELECT rev, roi_rect FROM config_rev WHERE model_version_id = ?"
            " ORDER BY rev DESC LIMIT 1",
            (version["id"],),
        ).fetchone()
        if config:
            threshold = conn.execute(
                "SELECT th_lo, th_hi, mode FROM threshold_rev"
                " WHERE model_version_id = ? AND roi_rev = ? ORDER BY rev DESC LIMIT 1",
                (version["id"], config["rev"]),
            ).fetchone()

    results = conn.execute(
        "SELECT r.id, r.score, r.label, r.confirmed_by, r.created_at"
        " FROM inference_result r JOIN inference_job j ON j.id = r.job_id"
        " WHERE j.code = ? ORDER BY r.id DESC LIMIT 20",
        (code,),
    ).fetchall()

    case_count = conn.execute(
        "SELECT count(*) c FROM case_item WHERE product_code_id = ?", (row["id"],)
    ).fetchone()["c"]

    return {
        "code": row["code"],
        "family": row["family"],
        "part": row["part"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "binding": {
            "model_id": binding["model_id"],
            "model_code": binding["model_code"],
            "model_name": binding["model_name"],
            "stage": binding["stage"],
            "since": binding["active_from"],
        }
        if binding
        else None,
        "version": {
            "id": version["id"],
            "version_no": version["version_no"],
            "status": version["status"],
        }
        if version
        else None,
        "config": {
            "rev": config["rev"],
            "roi_rect": json.loads(config["roi_rect"]),
        }
        if config
        else None,
        "threshold": {
            "th_lo": threshold["th_lo"],
            "th_hi": threshold["th_hi"],
            "mode": threshold["mode"],
        }
        if threshold
        else None,
        "recent_results": [dict(r) for r in results],
        "case_count": case_count,
    }


@router.get("/codes/{code}/timeline")
def code_timeline(
    code: str, limit: int = 30, conn: sqlite3.Connection = Depends(get_conn)
) -> list[dict]:
    row = conn.execute("SELECT id FROM product_code WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise ApiError("unknown_code", f"未知编码 {code}", "核对编码", 404)
    code_id = row["id"]

    events: list[dict] = []

    for b in conn.execute(
        "SELECT b.active_from, b.active_to, b.stage, m.code AS model_code"
        " FROM binding b JOIN model m ON m.id = b.model_id"
        " WHERE b.product_code_id = ?",
        (code_id,),
    ).fetchall():
        events.append(
            {
                "at": b["active_from"],
                "kind": "binding",
                "title": f"绑定到模型 {b['model_code']}（{b['stage']}）",
                "detail": f"解除于 {b['active_to']}" if b["active_to"] else "当前生效",
            }
        )

    for v in conn.execute(
        "SELECT mv.version_no, mv.status, mv.created_at FROM model_version mv"
        " JOIN binding b ON b.model_id = mv.model_id"
        " WHERE b.product_code_id = ?",
        (code_id,),
    ).fetchall():
        events.append(
            {
                "at": v["created_at"],
                "kind": "version",
                "title": f"版本 v{v['version_no']} 状态 {v['status']}",
                "detail": "",
            }
        )

    for c in conn.execute(
        "SELECT cr.rev, cr.created_at FROM config_rev cr"
        " JOIN model_version mv ON mv.id = cr.model_version_id"
        " JOIN binding b ON b.model_id = mv.model_id"
        " WHERE b.product_code_id = ?",
        (code_id,),
    ).fetchall():
        events.append(
            {"at": c["created_at"], "kind": "config", "title": f"ROI rev {c['rev']}", "detail": ""}
        )

    for t in conn.execute(
        "SELECT tr.th_lo, tr.th_hi, tr.created_at FROM threshold_rev tr"
        " JOIN model_version mv ON mv.id = tr.model_version_id"
        " JOIN binding b ON b.model_id = mv.model_id"
        " WHERE b.product_code_id = ?",
        (code_id,),
    ).fetchall():
        events.append(
            {
                "at": t["created_at"],
                "kind": "threshold",
                "title": f"阈值 {t['th_lo']:.2f} / {t['th_hi']:.2f}",
                "detail": "",
            }
        )

    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return events[: max(1, min(limit, 100))]


class CaseIn(BaseModel):
    code: str
    crop_path: str
    verdict: str
    adjudicator: str
    reason: str | None = None


class CasePatch(BaseModel):
    verdict: str | None = None
    reason: str | None = None


class CaseIn(BaseModel):
    code: str
    crop_path: str
    verdict: str
    adjudicator: str
    reason: str | None = None
    source: str = "manual"
    result_id: int | None = None
    model_version_id: int | None = None
    part_no: str | None = None


class CasePatch(BaseModel):
    verdict: str | None = None
    reason: str | None = None


@router.put("/cases/{case_id}")
def patch_case(
    case_id: int, body: CasePatch, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    try:
        cases_mod.update_case(conn, case_id, verdict=body.verdict, reason=body.reason)
    except ValueError as exc:
        raise ApiError("bad_verdict", str(exc), "重选", 400) from exc
    except LookupError as exc:
        raise ApiError("case_not_found", str(exc), "刷新列表", 404) from exc
    return {"id": case_id}


@router.delete("/cases/{case_id}")
def remove_case(case_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    if not cases_mod.delete_case(conn, case_id):
        raise ApiError("case_not_found", f"判例不存在: {case_id}", "刷新列表", 404)
    with tx(conn):
        record(conn, actor="web", action="case.delete", entity="case_item", entity_id=case_id)
    return {"id": case_id, "deleted": True}


@router.post("/cases/{case_id}/archive")
def archive_case(case_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        cases_mod.archive_case(conn, case_id)
    except LookupError as exc:
        raise ApiError("case_not_found", str(exc), "刷新列表", 404) from exc
    return {"id": case_id, "archived": True}


@router.post("/cases/{case_id}/restore")
def restore_case(case_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        cases_mod.restore_case(conn, case_id)
    except LookupError as exc:
        raise ApiError("case_not_found", str(exc), "刷新列表", 404) from exc
    return {"id": case_id, "archived": False}


@router.get("/export/dataset")
def export_dataset(
    family: str | None = None,
    verdict: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
) -> Response:
    """按族导出训练集清单（不含图片本体，只给路径与标签）。"""
    rows = cases_mod.list_cases(conn, family=family, verdict=verdict, limit=500)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "code", "part_no", "verdict", "reason", "source", "adjudicator", "crop_path", "created_at"])
    for c in rows:
        writer.writerow([c.id, c.code, c.part_no or "", c.verdict, c.reason or "",
                         c.source, c.adjudicator, c.crop_path, c.created_at])
    name = f"dataset-{family or 'all'}.csv"
    # HTTP 头只能是 latin-1，中文族名按 RFC 5987 编码
    quoted = quote(name, safe="")
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


@router.get("/cases/conflicts")
def list_conflicts(conn: sqlite3.Connection = Depends(get_conn)) -> list[dict]:
    rows = conn.execute(
        "SELECT c.id, p.code, c.verdict, c.reason, c.adjudicator, c.sha256, c.created_at"
        " FROM case_item c JOIN product_code p ON p.id = c.product_code_id"
        " WHERE c.conflict = 1 AND c.archived_at IS NULL ORDER BY c.id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/cases/{case_id}/image")
def case_image(case_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> FileResponse:
    row = conn.execute("SELECT crop_path FROM case_item WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise ApiError("case_not_found", f"判例 {case_id} 不存在", "刷新", 404)
    if not row["crop_path"]:
        raise ApiError("no_image", "该判例没有裁片", "补录路径", 404)

    path = Path(row["crop_path"]).resolve()
    db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    if not str(path).startswith(str(db_file.parent)):
        raise ApiError("image_outside_root", "裁片路径不在数据目录内", "检查存储配置", 403)
    if not path.exists():
        raise ApiError("image_missing", "裁片文件已不存在", "可能已被清理", 404)
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


@router.get("/cases")
def list_cases(
    code: str | None = None,
    adjudicator: str | None = None,
    verdict: str | None = None,
    source: str | None = None,
    part_no: str | None = None,
    batch_no: str | None = None,
    family: str | None = None,
    conflict: bool | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[dict]:
    rows = cases_mod.list_cases(
        conn,
        code=code,
        adjudicator=adjudicator,
        verdict=verdict,
        source=source,
        part_no=part_no,
        batch_no=batch_no,
        family=family,
        conflict=conflict,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return [case.__dict__ for case in rows]


@router.get("/cases/page")
def page_cases(
    code: str | None = None,
    adjudicator: str | None = None,
    verdict: str | None = None,
    source: str | None = None,
    part_no: str | None = None,
    batch_no: str | None = None,
    family: str | None = None,
    conflict: bool | None = None,
    include_archived: bool = False,
    limit: int = 25,
    offset: int = 0,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """分页版判例列表：带总数，供界面翻页；/cases 保留给脚本与小数据量场景。"""
    rows = cases_mod.list_cases(
        conn,
        code=code,
        adjudicator=adjudicator,
        verdict=verdict,
        source=source,
        part_no=part_no,
        batch_no=batch_no,
        family=family,
        conflict=conflict,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    total = cases_mod.count_cases(
        conn,
        code=code,
        adjudicator=adjudicator,
        verdict=verdict,
        source=source,
        part_no=part_no,
        batch_no=batch_no,
        family=family,
        conflict=conflict,
        include_archived=include_archived,
    )
    return {
        "items": [c.__dict__ for c in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/cases", status_code=201)
def create_case(body: CaseIn, conn: sqlite3.Connection = Depends(get_conn)) -> dict:
    try:
        case_id = cases_mod.create_case(
            conn,
            product_code=body.code,
            crop_path=body.crop_path,
            verdict=body.verdict,
            adjudicator=body.adjudicator,
            reason=body.reason,
            source=body.source,
            result_id=body.result_id,
            model_version_id=body.model_version_id,
            part_no=body.part_no,
        )
    except cases_mod.DuplicateCase as exc:
        raise ApiError(
            code="case_duplicate",
            message=str(exc),
            action="这张图已录过，去编辑现有条目结论",
            status=409,
        ) from exc
    except LookupError as exc:
        raise ApiError("unknown_code", str(exc), "先建编码", 404) from exc
    except ValueError as exc:
        raise ApiError("invalid_case", str(exc), "检查字段", 400) from exc
    return {"id": case_id}
