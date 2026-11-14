"""判例库（数据质量版）。

一条判例 = 裁片 + 二元结论 + 一句话理由 + 裁决人 + 时间，另加：
来源、回指的 result/版本、sha256（同码同图唯一）、软删、冲突标记。
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .audit import record
from .store import tx

VERDICTS = ("ok", "ng")
SOURCES = ("manual", "result", "import")


class DuplicateCase(Exception):
    def __init__(self, existing_id: int, conflict: bool) -> None:
        super().__init__(f"判例已存在: {existing_id}")
        self.existing_id = existing_id
        self.conflict = conflict


@dataclass(frozen=True)
class Case:
    id: int
    product_code_id: int
    code: str
    crop_path: str
    verdict: str
    reason: str | None
    adjudicator: str
    created_at: str
    sha256: str | None = None
    source: str = "manual"
    result_id: int | None = None
    model_version_id: int | None = None
    conflict: int = 0
    archived_at: str | None = None
    part_no: str | None = None


def _sha256(path: str) -> str | None:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_case(
    conn: sqlite3.Connection,
    *,
    product_code: str,
    crop_path: str,
    verdict: str,
    adjudicator: str,
    reason: str | None = None,
    source: str = "manual",
    result_id: int | None = None,
    model_version_id: int | None = None,
    part_no: str | None = None,
) -> int:
    if verdict not in VERDICTS:
        raise ValueError(f"verdict 只能是 {VERDICTS}，收到 {verdict!r}")
    if source not in SOURCES:
        raise ValueError(f"source 只能是 {SOURCES}")

    row = conn.execute("SELECT id FROM product_code WHERE code = ?", (product_code,)).fetchone()
    if row is None:
        raise LookupError(f"未知产品编码: {product_code}")

    part_no = (part_no or "").strip() or None

    if part_no is not None:
        existing = conn.execute(
            "SELECT id, verdict FROM case_item WHERE product_code_id = ? AND part_no = ?",
            (row["id"], part_no),
        ).fetchone()
        if existing is not None:
            conflict = existing["verdict"] != verdict
            if conflict:
                with tx(conn):
                    conn.execute("UPDATE case_item SET conflict = 1 WHERE id = ?", (existing["id"],))
                    record(conn, actor=adjudicator, action="case.conflict", entity="case_item",
                           entity_id=existing["id"], payload={"attempted": verdict, "part_no": part_no})
            raise DuplicateCase(existing["id"], conflict)

    sha = _sha256(crop_path)
    if sha is not None:
        existing = conn.execute(
            "SELECT id, verdict FROM case_item WHERE product_code_id = ? AND sha256 = ?",
            (row["id"], sha),
        ).fetchone()
        if existing is not None:
            conflict = existing["verdict"] != verdict
            if conflict:
                with tx(conn):
                    conn.execute("UPDATE case_item SET conflict = 1 WHERE id = ?", (existing["id"],))
                    record(conn, actor=adjudicator, action="case.conflict", entity="case_item",
                           entity_id=existing["id"], payload={"attempted": verdict})
            raise DuplicateCase(existing["id"], conflict)

    with tx(conn):
        cur = conn.execute(
            "INSERT INTO case_item"
            " (product_code_id, crop_path, verdict, reason, adjudicator, sha256, source,"
            "  result_id, model_version_id, part_no)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["id"], crop_path, verdict, reason, adjudicator, sha, source, result_id,
             model_version_id, part_no),
        )
        case_id = int(cur.lastrowid)
        record(conn, actor=adjudicator, action="case.create", entity="case_item",
               entity_id=case_id, payload={"verdict": verdict, "source": source})
    return case_id


def get_case(conn: sqlite3.Connection, case_id: int) -> Case | None:
    row = conn.execute(
        "SELECT c.*, p.code FROM case_item c JOIN product_code p ON p.id = c.product_code_id"
        " WHERE c.id = ?",
        (case_id,),
    ).fetchone()
    return _to_case(row) if row else None


def list_cases(
    conn: sqlite3.Connection,
    *,
    code: str | None = None,
    adjudicator: str | None = None,
    verdict: str | None = None,
    source: str | None = None,
    part_no: str | None = None,
    conflict: bool | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Case]:
    clauses: list[str] = []
    params: list[object] = []
    if code is not None:
        clauses.append("p.code = ?")
        params.append(code)
    if adjudicator is not None:
        clauses.append("c.adjudicator = ?")
        params.append(adjudicator)
    if verdict is not None:
        if verdict not in VERDICTS:
            raise ValueError(f"verdict 只能是 {VERDICTS}")
        clauses.append("c.verdict = ?")
        params.append(verdict)
    if source is not None:
        clauses.append("c.source = ?")
        params.append(source)
    if part_no is not None:
        clauses.append("c.part_no = ?")
        params.append(part_no)
    if conflict is not None:
        clauses.append("c.conflict = ?")
        params.append(1 if conflict else 0)
    if not include_archived:
        clauses.append("c.archived_at IS NULL")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.extend([max(1, min(limit, 500)), max(0, offset)])
    rows = conn.execute(
        "SELECT c.*, p.code FROM case_item c JOIN product_code p ON p.id = c.product_code_id"
        f"{where} ORDER BY c.created_at DESC, c.id DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    return [_to_case(r) for r in rows]


def count_cases(
    conn: sqlite3.Connection, *, code: str | None = None, conflict: bool | None = None
) -> int:
    clauses: list[str] = ["c.archived_at IS NULL"]
    params: list[object] = []
    if code:
        clauses.append("p.code = ?")
        params.append(code)
    if conflict is not None:
        clauses.append("c.conflict = ?")
        params.append(1 if conflict else 0)
    row = conn.execute(
        "SELECT count(*) c FROM case_item c JOIN product_code p ON p.id = c.product_code_id"
        " WHERE " + " AND ".join(clauses),
        params,
    ).fetchone()
    return int(row["c"])


def update_case(
    conn: sqlite3.Connection,
    case_id: int,
    *,
    verdict: str | None = None,
    reason: str | None = None,
    actor: str = "web",
) -> None:
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError(f"verdict 只能是 {VERDICTS}")
    with tx(conn):
        cur = conn.execute(
            "UPDATE case_item SET verdict = COALESCE(?, verdict), reason = COALESCE(?, reason),"
            " conflict = 0 WHERE id = ?",
            (verdict, reason, case_id),
        )
        if cur.rowcount == 0:
            raise LookupError(f"判例不存在: {case_id}")
        record(conn, actor=actor, action="case.patch", entity="case_item", entity_id=case_id,
               payload={"verdict": verdict, "reason": reason})


def archive_case(conn: sqlite3.Connection, case_id: int, actor: str = "web") -> None:
    """软删：训练集可复现，不真删。"""
    with tx(conn):
        cur = conn.execute(
            "UPDATE case_item SET archived_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            " WHERE id = ? AND archived_at IS NULL",
            (case_id,),
        )
        if cur.rowcount == 0:
            raise LookupError(f"判例不存在或已归档: {case_id}")
        record(conn, actor=actor, action="case.archive", entity="case_item", entity_id=case_id)


def restore_case(conn: sqlite3.Connection, case_id: int, actor: str = "web") -> None:
    with tx(conn):
        cur = conn.execute("UPDATE case_item SET archived_at = NULL WHERE id = ?", (case_id,))
        if cur.rowcount == 0:
            raise LookupError(f"判例不存在: {case_id}")
        record(conn, actor=actor, action="case.restore", entity="case_item", entity_id=case_id)


def delete_case(conn: sqlite3.Connection, case_id: int) -> bool:
    with tx(conn):
        cur = conn.execute("DELETE FROM case_item WHERE id = ?", (case_id,))
    return cur.rowcount > 0


def export_for_training(conn: sqlite3.Connection, *, code: str | None = None) -> dict[str, list[int]]:
    rows = list_cases(conn, code=code, limit=500)
    out: dict[str, list[int]] = {"normal": [], "defect": []}
    for case in rows:
        out["normal" if case.verdict == "ok" else "defect"].append(case.id)
    return out


def _to_case(row: sqlite3.Row) -> Case:
    keys = row.keys()
    return Case(
        id=row["id"],
        product_code_id=row["product_code_id"],
        code=row["code"],
        crop_path=row["crop_path"],
        verdict=row["verdict"],
        reason=row["reason"],
        adjudicator=row["adjudicator"],
        created_at=row["created_at"],
        sha256=row["sha256"] if "sha256" in keys else None,
        source=row["source"] if "source" in keys else "manual",
        result_id=row["result_id"] if "result_id" in keys else None,
        model_version_id=row["model_version_id"] if "model_version_id" in keys else None,
        conflict=row["conflict"] if "conflict" in keys else 0,
        archived_at=row["archived_at"] if "archived_at" in keys else None,
        part_no=row["part_no"] if "part_no" in keys else None,
    )
