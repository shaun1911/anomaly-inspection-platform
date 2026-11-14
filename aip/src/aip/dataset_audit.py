"""数据集成员快照与事后核对。

冻结时记录每条判例的 verdict / sha256；之后判例被改判、换图、归档或删除，
都能在核对视图里列出来——这是"训练可复现"的最后一环。
"""

from __future__ import annotations

import sqlite3

from .datasets import DatasetError


def snapshot(conn: sqlite3.Connection, dataset_id: int) -> None:
    """冻结时调用：把每条的 verdict 与 sha256 写进 dataset_item。"""
    conn.execute(
        "UPDATE dataset_item SET"
        " verdict_at_freeze = (SELECT c.verdict FROM case_item c WHERE c.id = dataset_item.case_id),"
        " sha256_at_freeze = (SELECT c.sha256 FROM case_item c WHERE c.id = dataset_item.case_id)"
        " WHERE dataset_id = ?",
        (dataset_id,),
    )


def audit(conn: sqlite3.Connection, dataset_id: int) -> dict:
    ds = conn.execute("SELECT status FROM dataset WHERE id = ?", (dataset_id,)).fetchone()
    if ds is None:
        raise DatasetError("dataset_not_found", f"数据集 {dataset_id} 不存在", status=404)

    rows = conn.execute(
        "SELECT i.case_id, i.verdict_at_freeze, i.sha256_at_freeze,"
        " c.verdict, c.sha256, c.archived_at, c.part_no, p.code"
        " FROM dataset_item i"
        " LEFT JOIN case_item c ON c.id = i.case_id"
        " LEFT JOIN product_code p ON p.id = c.product_code_id"
        " WHERE i.dataset_id = ? ORDER BY i.case_id",
        (dataset_id,),
    ).fetchall()

    changed, image_changed, archived, missing = [], [], [], []
    for r in rows:
        item = {
            "case_id": r["case_id"],
            "code": r["code"],
            "part_no": r["part_no"],
            "before": r["verdict_at_freeze"],
            "after": r["verdict"],
        }
        if r["verdict"] is None and r["sha256"] is None:
            missing.append({"case_id": r["case_id"], "code": r["code"], "part_no": r["part_no"]})
            continue
        if r["verdict_at_freeze"] is not None and r["verdict"] != r["verdict_at_freeze"]:
            changed.append(item)
        if r["sha256_at_freeze"] is not None and r["sha256"] != r["sha256_at_freeze"]:
            image_changed.append(item)
        if r["archived_at"] is not None:
            archived.append(item)

    no_snapshot = sum(1 for r in rows if r["verdict_at_freeze"] is None)
    return {
        "dataset_id": dataset_id,
        "no_snapshot": no_snapshot,
        "status": ds["status"],
        "total": len(rows),
        "verdict_changed": changed,
        "image_changed": image_changed,
        "archived": archived,
        "missing": missing,
        "clean": not (changed or image_changed or archived or missing) and no_snapshot == 0,
    }
