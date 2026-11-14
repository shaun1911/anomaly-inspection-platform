"""数据集（L3 快照层）。

一个数据集 = 一个族 + 一个模型 + 一组判例。冻结后成员不可变，
checksum 让"这版模型用了哪些数据"可复现。
"""

from __future__ import annotations

import hashlib
import sqlite3

from .audit import record
from .store import tx


class DatasetError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _family_for_model(conn: sqlite3.Connection, model_id: int) -> int | None:
    """模型被哪些编码绑定 → 这些编码的族；多于一个族就报错。"""
    rows = conn.execute(
        "SELECT DISTINCT p.family_id FROM binding b"
        " JOIN product_code p ON p.id = b.product_code_id"
        " WHERE b.model_id = ? AND b.active_to IS NULL",
        (model_id,),
    ).fetchall()
    families = {int(r["family_id"]) for r in rows if r["family_id"] is not None}
    if len(families) > 1:
        raise DatasetError(
            "model_multi_family",
            "该模型同时服务多个族，无法自动确定数据集所属族",
            status=409,
        )
    return next(iter(families), None)


def create_dataset(
    conn: sqlite3.Connection,
    *,
    model_id: int,
    name: str,
    note: str | None = None,
    actor: str = "web",
) -> int:
    name = (name or "").strip()
    if not name:
        raise DatasetError("bad_name", "数据集名称不能为空")
    model = conn.execute("SELECT id, archived_at FROM model WHERE id = ?", (model_id,)).fetchone()
    if model is None:
        raise DatasetError("model_not_found", f"模型 {model_id} 不存在", status=404)
    if model["archived_at"] is not None:
        raise DatasetError("model_archived", "模型已归档", status=409)

    family_id = _family_for_model(conn, model_id)
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO dataset (name, family_id, model_id, note, created_by)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, family_id, model_id, note, actor),
        )
        dataset_id = int(cur.lastrowid)
        record(conn, actor=actor, action="dataset.create", entity="dataset",
               entity_id=dataset_id, payload={"model_id": model_id, "family_id": family_id})
    return dataset_id


def add_items(
    conn: sqlite3.Connection, dataset_id: int, case_ids: list[int], *, actor: str = "web"
) -> dict:
    ds = conn.execute("SELECT * FROM dataset WHERE id = ?", (dataset_id,)).fetchone()
    if ds is None:
        raise DatasetError("dataset_not_found", f"数据集 {dataset_id} 不存在", status=404)
    if ds["status"] != "draft":
        raise DatasetError("dataset_frozen", "数据集已冻结，不能再改", status=409)

    added, skipped = [], []
    for cid in case_ids:
        row = conn.execute(
            "SELECT c.id, c.archived_at, p.family_id FROM case_item c"
            " JOIN product_code p ON p.id = c.product_code_id WHERE c.id = ?",
            (cid,),
        ).fetchone()
        if row is None or row["archived_at"] is not None:
            skipped.append(cid)
            continue
        if ds["family_id"] is not None and row["family_id"] != ds["family_id"]:
            skipped.append(cid)
            continue
        try:
            with tx(conn):
                conn.execute(
                    "INSERT INTO dataset_item (dataset_id, case_id) VALUES (?, ?)",
                    (dataset_id, cid),
                )
            added.append(cid)
        except sqlite3.IntegrityError:
            skipped.append(cid)
    if added:
        with tx(conn):
            record(conn, actor=actor, action="dataset.add", entity="dataset",
                   entity_id=dataset_id, payload={"added": added})
    return {"added": added, "skipped": skipped}


def freeze(conn: sqlite3.Connection, dataset_id: int, *, actor: str = "web") -> str:
    ds = conn.execute("SELECT * FROM dataset WHERE id = ?", (dataset_id,)).fetchone()
    if ds is None:
        raise DatasetError("dataset_not_found", f"数据集 {dataset_id} 不存在", status=404)
    if ds["status"] == "frozen":
        raise DatasetError("already_frozen", "数据集已冻结", status=409)

    rows = conn.execute(
        "SELECT i.case_id, c.sha256 FROM dataset_item i JOIN case_item c ON c.id = i.case_id"
        " WHERE i.dataset_id = ? ORDER BY i.case_id",
        (dataset_id,),
    ).fetchall()
    if not rows:
        raise DatasetError("empty_dataset", "空数据集不能冻结")

    digest = hashlib.sha256()
    for r in rows:
        digest.update(f"{r['case_id']}:{r['sha256'] or ''}\n".encode())
    checksum = digest.hexdigest()

    with tx(conn):
        conn.execute(
            "UPDATE dataset SET status = 'frozen', checksum = ?,"
            " frozen_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
            (checksum, dataset_id),
        )
        from .dataset_audit import snapshot

        snapshot(conn, dataset_id)
        record(conn, actor=actor, action="dataset.freeze", entity="dataset",
               entity_id=dataset_id, payload={"checksum": checksum, "count": len(rows)})
    return checksum


def get_dataset(conn: sqlite3.Connection, dataset_id: int) -> dict:
    ds = conn.execute(
        "SELECT d.*, f.name AS family, m.code AS model_code FROM dataset d"
        " LEFT JOIN family f ON f.id = d.family_id"
        " JOIN model m ON m.id = d.model_id WHERE d.id = ?",
        (dataset_id,),
    ).fetchone()
    if ds is None:
        raise DatasetError("dataset_not_found", f"数据集 {dataset_id} 不存在", status=404)
    items = conn.execute(
        "SELECT i.case_id, i.split, c.part_no, c.batch_no, c.verdict, c.reason,"
        " p.code FROM dataset_item i"
        " JOIN case_item c ON c.id = i.case_id"
        " JOIN product_code p ON p.id = c.product_code_id"
        " WHERE i.dataset_id = ? ORDER BY i.case_id",
        (dataset_id,),
    ).fetchall()
    out = dict(ds)
    out["items"] = [dict(r) for r in items]
    out["count"] = len(items)
    return out


def list_datasets(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT d.id, d.name, d.status, d.checksum, d.frozen_at, d.created_at,"
        " f.name AS family, m.code AS model_code,"
        " (SELECT count(*) FROM dataset_item i WHERE i.dataset_id = d.id) AS count"
        " FROM dataset d LEFT JOIN family f ON f.id = d.family_id"
        " JOIN model m ON m.id = d.model_id"
        " ORDER BY d.id DESC LIMIT ?",
        (max(1, min(limit, 500)),),
    ).fetchall()
    return [dict(r) for r in rows]
