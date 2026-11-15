"""备份与还原验收。"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from aip import backup, store


@pytest.fixture()
def env(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = store.connect(data / "aip.db")
    store.migrate(conn)
    (data / "crops").mkdir()
    (data / "crops" / "a.png").write_bytes(b"x" * 120)
    (data / "cases").mkdir()
    (data / "cases" / "b.png").write_bytes(b"y" * 60)
    conn.execute("INSERT INTO product_code (code) VALUES ('AB-1')")
    conn.commit()
    yield conn, data
    conn.close()


def test_backup_creates_valid_zip(env, tmp_path):
    conn, data = env
    archive = tmp_path / "backup.zip"
    out = backup.create(conn, str(archive))
    assert archive.exists()
    assert out["files"] >= 3
    assert len(out["sha256"]) == 64

    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "aip.db" in names
    assert "crops/a.png" in names

    info = backup.inspect(str(archive))
    assert info["ok"] is True
    assert info["manifest"]["schema_version"] >= 1


def test_restore_to_empty_target(env, tmp_path):
    conn, data = env
    archive = tmp_path / "backup.zip"
    backup.create(conn, str(archive))
    target = tmp_path / "restored"

    out = backup.restore(str(archive), str(target), conn=conn)
    assert out["restored"] is True
    assert (target / "aip.db").exists()
    assert (target / "crops" / "a.png").exists()

    restored = sqlite3.connect(target / "aip.db")
    try:
        assert restored.execute("SELECT count(*) FROM product_code").fetchone()[0] == 1
    finally:
        restored.close()
    audit = conn.execute(
        "SELECT action FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert audit["action"] == "storage.restore"


def test_restore_refuses_non_empty_target(env, tmp_path):
    conn, data = env
    archive = tmp_path / "backup.zip"
    backup.create(conn, str(archive))
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "x").write_text("x", encoding="utf-8")
    with pytest.raises(backup.BackupError):
        backup.restore(str(archive), str(target), conn=conn)


def test_inspect_rejects_path_traversal(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format_version": 1, "files": 1}))
        zf.writestr("../../evil.txt", "x")
    info = backup.inspect(str(archive))
    assert info["ok"] is False
    assert any("非法路径" in p for p in info["problems"])


def test_inspect_rejects_missing_db(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format_version": 1}))
    info = backup.inspect(str(archive))
    assert info["ok"] is False
    assert any("aip.db" in p for p in info["problems"])
