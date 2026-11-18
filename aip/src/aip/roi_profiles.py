"""ROI 配置：按“编码 + 站位”管理。

优先级：编码+具体站位 > 编码默认（station_id=0）> 模型版本 config_rev。
"""

from __future__ import annotations

import json
import sqlite3

from .audit import record
from .store import tx


class RoiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _code_id(conn: sqlite3.Connection, code: str) -> int:
    row = conn.execute("SELECT id FROM product_code WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise RoiError("unknown_code", f"未知编码 {code}", 404)
    return int(row["id"])


def _station_id(conn: sqlite3.Connection, name: str | None, create: bool = False) -> int:
    name = (name or "").strip()
    if not name:
        return 0
    row = conn.execute("SELECT id FROM station WHERE name = ?", (name,)).fetchone()
    if row is not None:
        return int(row["id"])
    if not create:
        return 0
    cur = conn.execute(
        "INSERT INTO station (name, health, last_seen_at) VALUES (?, 'ok',"
        " strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
        (name,),
    )
    return int(cur.lastrowid)


def validate_roi(roi: list[int]) -> list[int]:
    if not isinstance(roi, list) or len(roi) != 4:
        raise RoiError("bad_roi", "ROI 必须是 4 个整数：x1,y1,x2,y2", 400)
    try:
        x1, y1, x2, y2 = [int(v) for v in roi]
    except (TypeError, ValueError):
        raise RoiError("bad_roi", "ROI 必须是整数", 400) from None
    if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
        raise RoiError("bad_roi", "ROI 需满足 0<=x1<x2、0<=y1<y2", 400)
    return [x1, y1, x2, y2]


def list_profiles(conn: sqlite3.Connection, code: str) -> list[dict]:
    cid = _code_id(conn, code)
    rows = conn.execute(
        "SELECT p.id, p.station_id, s.name station, p.roi_rect, p.rev, p.note,"
        " p.updated_by, p.updated_at"
        " FROM roi_profile p LEFT JOIN station s ON s.id = p.station_id"
        " WHERE p.product_code_id = ? AND p.active = 1"
        " ORDER BY p.station_id",
        (cid,),
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["station"] = r["station"] or "(编码默认)"
        item["roi_rect"] = json.loads(r["roi_rect"])
        out.append(item)
    return out


def save_profile(
    conn: sqlite3.Connection, code: str, roi: list[int],
    station: str | None = None, note: str | None = None, actor: str = "web",
) -> dict:
    roi = validate_roi(roi)
    cid = _code_id(conn, code)
    with tx(conn):
        sid = _station_id(conn, station, create=True)
        row = conn.execute(
            "SELECT COALESCE(MAX(rev), 0) AS rev FROM roi_profile"
            " WHERE product_code_id = ? AND station_id = ?",
            (cid, sid),
        ).fetchone()
        rev = int(row["rev"]) + 1
        conn.execute(
            "UPDATE roi_profile SET active = 0 WHERE product_code_id = ? AND station_id = ? AND active = 1",
            (cid, sid),
        )
        cur = conn.execute(
            "INSERT INTO roi_profile (product_code_id, station_id, roi_rect, rev, active,"
            " note, updated_by) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (cid, sid, json.dumps(roi), rev, note, actor),
        )
        record(conn, actor=actor, action="roi_profile.save", entity="roi_profile",
               entity_id=cur.lastrowid,
               payload={"code": code, "station": station or None, "roi": roi, "rev": rev})
    return {"id": int(cur.lastrowid), "code": code, "station": station or "(编码默认)",
            "roi_rect": roi, "rev": rev}


def resolve_for_station(
    conn: sqlite3.Connection, code: str, station: str | None
) -> dict | None:
    """返回当前编码+站位的 ROI；没有返回 None（调用方回退版本配置）。"""
    cid = _code_id(conn, code)
    sid = _station_id(conn, station, create=False) if station else 0
    row = None
    if sid:
        row = conn.execute(
            "SELECT id, station_id, roi_rect, rev, updated_at FROM roi_profile"
            " WHERE product_code_id = ? AND station_id = ? AND active = 1",
            (cid, sid),
        ).fetchone()
    source = "code+station"
    if row is None:
        row = conn.execute(
            "SELECT id, station_id, roi_rect, rev, updated_at FROM roi_profile"
            " WHERE product_code_id = ? AND station_id = 0 AND active = 1",
            (cid,),
        ).fetchone()
        source = "code"
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "roi_rect": json.loads(row["roi_rect"]),
        "rev": int(row["rev"]),
        "source": source,
        "updated_at": row["updated_at"],
    }
