"""审计归档导入：把归档 CSV 读回 audit_log。

- 只接受本系统导出的列（id/actor/action/entity/entity_id/payload/created_at）；
- 按 (actor, action, entity, entity_id, created_at) 去重，重复导入不会翻倍；
- 保留原 created_at，id 由数据库重新分配；
- 先预检（行数/重复/非法行），再执行；导入动作写一条 audit.import。
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .audit import record
from .store import tx

REQUIRED = ["actor", "action", "entity", "created_at"]
MAX_ROWS = 20000


class ImportError_(Exception):
    pass


def inspect_csv(path: str | Path) -> dict:
    file = Path(path).expanduser()
    if not file.is_file():
        raise ImportError_(f"归档文件不存在: {file}")
    if file.suffix.lower() != ".csv":
        raise ImportError_("只支持 .csv 归档文件")

    problems: list[str] = []
    rows: list[dict] = []
    try:
        with file.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            header = reader.fieldnames or []
            missing = [c for c in REQUIRED if c not in header]
            if missing:
                raise ImportError_(f"缺少列: {', '.join(missing)}")
            for row in reader:
                if len(rows) >= MAX_ROWS:
                    problems.append(f"超过单次导入上限 {MAX_ROWS} 行，请拆分文件")
                    break
                if not (row.get("created_at") or "").strip():
                    continue
                rows.append(row)
    except csv.Error as exc:
        raise ImportError_(f"CSV 解析失败: {exc}") from exc

    return {"path": str(file), "rows": rows, "count": len(rows), "problems": problems}


def _exists(conn: sqlite3.Connection, row: dict) -> bool:
    hit = conn.execute(
        "SELECT 1 FROM audit_log WHERE actor = ? AND action = ? AND entity = ?"
        " AND COALESCE(entity_id, '') = ? AND created_at = ? LIMIT 1",
        (row.get("actor") or "", row.get("action") or "", row.get("entity") or "",
         row.get("entity_id") or "", row.get("created_at")),
    ).fetchone()
    return hit is not None


def import_csv(conn: sqlite3.Connection, path: str | Path, apply: bool = False,
               actor: str = "web") -> dict:
    info = inspect_csv(path)
    if info["problems"]:
        raise ImportError_("；".join(info["problems"]))

    duplicates = sum(1 for row in info["rows"] if _exists(conn, row))
    fresh = info["count"] - duplicates

    if not apply:
        return {**info, "rows": None, "duplicates": duplicates, "fresh": fresh, "imported": 0}

    inserted = 0
    with tx(conn):
        for row in info["rows"]:
            if _exists(conn, row):
                continue
            conn.execute(
                "INSERT INTO audit_log (actor, action, entity, entity_id, payload, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (row.get("actor") or "", row.get("action") or "", row.get("entity") or "",
                 row.get("entity_id") or None, row.get("payload") or None, row["created_at"]),
            )
            inserted += 1
        record(conn, actor=actor, action="audit.import", entity="audit_log",
               payload={"path": str(Path(path).expanduser()), "inserted": inserted,
                        "duplicates": info["count"] - inserted})

    return {**info, "rows": None, "duplicates": info["count"] - inserted,
            "fresh": inserted, "imported": inserted}
