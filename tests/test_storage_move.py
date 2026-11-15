"""存储目录迁移验收：预检、复制、校验。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aip import storage, store


@pytest.fixture()
def env(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = store.connect(data / "aip.db")
    store.migrate(conn)
    (data / "crops").mkdir()
    (data / "crops" / "a.png").write_bytes(b"x" * 100)
    (data / "cases").mkdir()
    (data / "cases" / "b.png").write_bytes(b"y" * 50)
    conn.execute("INSERT INTO product_code (code) VALUES ('AB-1')")
    conn.commit()
    yield conn, data
    conn.close()


def test_info_reports_root_and_size(env):
    conn, data = env
    info = storage.info(conn)
    assert Path(info["root"]) == data.resolve()
    assert info["files"] >= 2
    assert info["bytes"] >= 150


def test_plan_rejects_same_or_nested_target(env):
    conn, data = env
    same = storage.plan_move(conn, str(data))
    assert same["ok"] is False
    assert any("相同" in p for p in same["problems"])

    with pytest.raises(storage.StorageError):
        storage.plan_move(conn, "relative/path")

    plan = storage.plan_move(conn, str(data / "inner"))
    assert plan["ok"] is False
    assert any("内部" in p for p in plan["problems"])


def test_plan_rejects_non_empty_target(env, tmp_path):
    conn, data = env
    target = tmp_path / "target"
    target.mkdir()
    (target / "old.txt").write_text("x", encoding="utf-8")
    plan = storage.plan_move(conn, str(target))
    assert plan["ok"] is False
    assert any("非空" in p for p in plan["problems"])


def test_apply_copies_db_and_files(env, tmp_path):
    conn, data = env
    target = tmp_path / "moved"
    out = storage.apply_move(conn, str(target))
    assert out["moved"] is True
    assert (target / "aip.db").exists()
    assert (target / "crops" / "a.png").exists()
    assert (target / "cases" / "b.png").exists()

    moved = sqlite3.connect(target / "aip.db")
    try:
        assert moved.execute("SELECT count(*) FROM product_code").fetchone()[0] == 1
        assert moved.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        moved.close()

    audit = conn.execute("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert audit["action"] == "storage.move"


def test_apply_refuses_when_target_non_empty(env, tmp_path):
    conn, data = env
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "x").write_text("x", encoding="utf-8")
    with pytest.raises(storage.StorageError):
        storage.apply_move(conn, str(target))
