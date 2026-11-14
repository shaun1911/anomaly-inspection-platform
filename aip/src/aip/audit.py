"""审计写入。

一条审计 = 谁（actor）在什么时候对什么（entity#id）做了什么（action），附可选 payload。
不抛异常：审计失败不能阻断业务，但必须留痕到日志。
"""

from __future__ import annotations

import json
import logging
import sqlite3

log = logging.getLogger("aip.audit")


def record(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    entity: str,
    entity_id: str | int | None = None,
    payload: dict | None = None,
) -> None:
    try:
        conn.execute(
            "INSERT INTO audit_log (actor, action, entity, entity_id, payload)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                actor or "unknown",
                action,
                entity,
                None if entity_id is None else str(entity_id),
                json.dumps(payload, ensure_ascii=False) if payload else None,
            ),
        )
    except sqlite3.Error:  # 审计失败不影响主流程
        log.exception("audit write failed: %s %s %s", action, entity, entity_id)
