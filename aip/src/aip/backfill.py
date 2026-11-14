"""存量批次回填（L1 完整性）。

历史判定没有批次号。补录必须可识别（batch_source='backfill'）并留审计，
否则"按批统计"分不清哪些是真批次、哪些是推断出来的。

规则：
- daily : LEGACY-YYYYMMDD
- shift : LEGACY-YYYYMMDD-D / -N（07:00–19:00 白班，其余夜班）
- csv   : 外部映射（job_id,batch_no），最精确，优先用于有 MES 导出的场景
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

from .audit import record
from .store import tx

RULES = ("daily", "shift", "csv")


def _day(created_at: str) -> str:
    return created_at[:10].replace("-", "")


def derive_batch(created_at: str, rule: str) -> str:
    stamp = _day(created_at)
    if rule == "daily":
        return f"LEGACY-{stamp}"
    if rule == "shift":
        try:
            hour = datetime.fromisoformat(created_at.replace("Z", "+00:00")).hour
        except ValueError:
            hour = 0
        shift = "D" if 7 <= hour < 19 else "N"
        return f"LEGACY-{stamp}-{shift}"
    raise ValueError(f"未知规则: {rule}")


def load_mapping(path: str | Path) -> dict[int, str]:
    mapping: dict[int, str] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                mapping[int(row["job_id"])] = str(row["batch_no"]).strip()
            except (KeyError, ValueError):
                continue
    return mapping


def plan(conn: sqlite3.Connection, rule: str, mapping: dict[int, str] | None = None) -> list[dict]:
    """返回将要补录的行（不写库）。"""
    rows = conn.execute(
        "SELECT id, created_at, code FROM inference_job WHERE batch_no IS NULL ORDER BY id"
    ).fetchall()
    out = []
    for r in rows:
        if mapping is not None:
            batch = mapping.get(int(r["id"]))
            if not batch:
                continue
        else:
            batch = derive_batch(r["created_at"], rule)
        out.append({"job_id": int(r["id"]), "code": r["code"], "batch_no": batch})
    return out


def backfill(
    conn: sqlite3.Connection,
    rule: str = "daily",
    mapping: dict[int, str] | None = None,
    apply: bool = False,
    actor: str = "backfill",
) -> dict:
    if mapping is not None:
        rule = "csv"
    if rule not in RULES:
        raise ValueError(f"未知规则: {rule}")

    items = plan(conn, rule, mapping)
    jobs = len(items)
    orphans = (
        conn.execute(
            "SELECT id, created_at FROM case_item WHERE batch_no IS NULL AND result_id IS NULL"
        ).fetchall()
        if apply
        else []
    )
    if not apply:
        return {"rule": rule, "jobs": jobs, "cases": 0, "applied": False, "sample": items[:5]}
    if jobs == 0 and not orphans:
        return {"rule": rule, "jobs": 0, "cases": 0, "applied": False, "sample": []}

    case_count = 0
    with tx(conn):
        for it in items:
            conn.execute(
                "UPDATE inference_job SET batch_no = ?, batch_source = 'backfill' WHERE id = ?",
                (it["batch_no"], it["job_id"]),
            )
            cur = conn.execute(
                "UPDATE case_item SET batch_no = ?, batch_source = 'backfill'"
                " WHERE batch_no IS NULL AND result_id IN"
                " (SELECT id FROM inference_result WHERE job_id = ?)",
                (it["batch_no"], it["job_id"]),
            )
            case_count += cur.rowcount

        # 没有回指 result 的老判例：按创建时间套同一规则
        if mapping is None:
            for r in orphans:
                conn.execute(
                    "UPDATE case_item SET batch_no = ?, batch_source = 'backfill' WHERE id = ?",
                    (derive_batch(r["created_at"], rule), r["id"]),
                )
                case_count += 1

        record(
            conn,
            actor=actor,
            action="batch.backfill",
            entity="inference_job",
            payload={"rule": rule, "jobs": jobs, "cases": case_count},
        )
    return {"rule": rule, "jobs": jobs, "cases": case_count, "applied": True, "sample": items[:5]}
