"""审计归档导入验收。"""

from __future__ import annotations

import csv

import pytest
from fastapi.testclient import TestClient

from aip import store, whitelist
from aip.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "none.yaml"))
    whitelist.reset_cache()
    db = tmp_path / "data" / "aip.db"
    db.parent.mkdir()
    conn = store.connect(db)
    store.migrate(conn)
    for i, ts in enumerate(["2020-01-01T00:00:00.000Z", "2020-06-01T00:00:00.000Z"]):
        conn.execute(
            "INSERT INTO audit_log (actor, action, entity, entity_id, created_at)"
            " VALUES ('alice','setting.update','setting',?,?)",
            (str(i), ts),
        )
    conn.commit()
    conn.close()
    return TestClient(create_app(db))


def _archive(client):
    return client.post(
        "/api/maintenance/audit/archive", json={"days": 180, "apply": True, "actor": "admin"}
    ).json()


def test_import_restores_archived_rows(client):
    out = _archive(client)
    assert out["archived"] == 2
    before = client.get("/api/audit").json()["total"]

    plan = client.post(
        "/api/maintenance/audit/import", json={"path": out["path"], "apply": False}
    ).json()
    assert plan["count"] == 2
    assert plan["fresh"] == 2
    assert client.get("/api/audit").json()["total"] == before  # 预检不写库

    applied = client.post(
        "/api/maintenance/audit/import", json={"path": out["path"], "apply": True, "actor": "admin"}
    ).json()
    assert applied["imported"] == 2
    assert client.get("/api/audit").json()["total"] == before + 2 + 1  # +1 导入动作


def test_import_twice_is_idempotent(client):
    out = _archive(client)
    first = client.post(
        "/api/maintenance/audit/import", json={"path": out["path"], "apply": True}
    ).json()
    assert first["imported"] == 2
    second = client.post(
        "/api/maintenance/audit/import", json={"path": out["path"], "apply": True}
    ).json()
    assert second["imported"] == 0
    assert second["duplicates"] == 2


def test_import_rejects_bad_csv(client, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
    resp = client.post("/api/maintenance/audit/import", json={"path": str(bad), "apply": False})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "audit_import_failed"


def test_import_missing_file(client):
    resp = client.post(
        "/api/maintenance/audit/import",
        json={"path": str(client.app.state.db_path.parent / "nope.csv"), "apply": False},
    )
    assert resp.status_code == 400
