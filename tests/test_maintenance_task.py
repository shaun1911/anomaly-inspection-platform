"""每日维护任务验收。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from aip import maintenance_task, store
from aip.settings import set_many


@pytest.fixture()
def env(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = store.connect(data / "aip.db")
    store.migrate(conn)
    (data / "crops").mkdir()
    yield conn, data
    conn.close()


def test_next_run_rolls_to_tomorrow():
    now = datetime(2026, 11, 15, 10, 30, tzinfo=timezone.utc)
    assert maintenance_task.next_run(now, 3) == datetime(2026, 11, 16, 3, tzinfo=timezone.utc)
    assert maintenance_task.next_run(now, 23) == datetime(2026, 11, 15, 23, tzinfo=timezone.utc)


def test_switches_off_do_nothing(env):
    conn, data = env
    assert maintenance_task.run_once(conn, data, actor="test") == {}
    rows = conn.execute("SELECT count(*) c FROM audit_log").fetchone()["c"]
    assert rows == 0


def test_auto_audit_archives_when_enabled(env):
    conn, data = env
    conn.execute(
        "INSERT INTO audit_log (actor, action, entity, created_at)"
        " VALUES ('a','setting.update','setting','2020-01-01T00:00:00.000Z')"
    )
    set_many(conn, {"maintenance.auto_audit": True})

    out = maintenance_task.run_once(conn, data, actor="test")
    assert out["audit_archived"] == 1
    assert Path(out["audit_path"]).exists()

    actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert "audit.archive" in actions
    assert "maintenance.auto" in actions


def test_auto_retention_removes_old_crop_when_enabled(env):
    conn, data = env
    img = data / "crops" / "old.png"
    img.write_bytes(b"x" * 10)
    old = datetime(2020, 1, 1, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    import os

    ts = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(img, (ts, ts))
    set_many(conn, {"maintenance.auto_retention": True, "retention.crop_days": 30})

    out = maintenance_task.run_once(conn, data, actor="test")
    assert out["retention_removed"] >= 1
    assert not img.exists()


def test_auto_runs_do_not_delete_audit_from_this_run(env):
    conn, data = env
    conn.execute(
        "INSERT INTO audit_log (actor, action, entity, created_at)"
        " VALUES ('a','setting.update','setting','2020-01-01T00:00:00.000Z')"
    )
    set_many(conn, {"maintenance.auto_audit": True})
    maintenance_task.run_once(conn, data, actor="test")
    latest = conn.execute("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert latest["action"] == "maintenance.auto"
