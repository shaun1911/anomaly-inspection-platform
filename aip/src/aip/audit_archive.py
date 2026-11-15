"""审计日志归档：导出旧记录为 CSV，再从库里删除。

- 只处理早于保留期的行（默认 180 天，最少 30 天，防手滑）；
- 先写 CSV 并落盘，再删库；两步在同一个事务语义里（导出成功才删）；
- 归档动作本身写一条审计（不会被立刻删掉）；
- 归档目录：`<data-dir>/audit-archive/`。
"""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .audit import record
from .store import tx

DEFAULT_DAYS = 180
MIN_DAYS = 30


class ArchiveError(Exception):
    pass


def _cutoff(days: int) -> str:
    if days < MIN_DAYS:
        raise ArchiveError(f"保留天数不得小于 {MIN_DAYS} 天")
    ts = datetime.now(timezone.utc) - timedelta(days=days)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def plan(conn: sqlite3.Connection, days: int = DEFAULT_DAYS) -> dict:
    cutoff = _cutoff(days)
    row = conn.execute(
        "SELECT count(*) c, min(created_at) oldest, max(created_at) newest"
        " FROM audit_log WHERE created_at < ?",
        (cutoff,),
    ).fetchone()
    return {
        "days": days,
        "cutoff": cutoff,
        "count": int(row["c"]),
        "oldest": row["oldest"],
        "newest": row["newest"],
    }


def archive(
    conn: sqlite3.Connection, data_dir: Path, days: int = DEFAULT_DAYS, actor: str = "web"
) -> dict:
    info = plan(conn, days)
    if info["count"] == 0:
        return {**info, "archived": 0, "path": None}

    rows = conn.execute(
        "SELECT id, actor, action, entity, entity_id, payload, created_at"
        " FROM audit_log WHERE created_at < ? ORDER BY id",
        (info["cutoff"],),
    ).fetchall()

    folder = Path(data_dir) / "audit-archive"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = folder / f"audit-{stamp}.csv"

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "actor", "action", "entity", "entity_id", "payload", "created_at"])
    for r in rows:
        writer.writerow([r["id"], r["actor"], r["action"], r["entity"], r["entity_id"],
                         r["payload"] or "", r["created_at"]])
    path.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")

    ids = [int(r["id"]) for r in rows]
    with tx(conn):
        conn.executemany("DELETE FROM audit_log WHERE id = ?", [(i,) for i in ids])
        record(
            conn,
            actor=actor,
            action="audit.archive",
            entity="audit_log",
            payload={"days": days, "archived": len(ids), "path": str(path)},
        )

    return {**info, "archived": len(ids), "path": str(path), "bytes": path.stat().st_size}
