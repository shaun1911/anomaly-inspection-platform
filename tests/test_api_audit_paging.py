"""审计日志分页与筛选验收。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aip import store, whitelist
from aip.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "none.yaml"))
    whitelist.reset_cache()
    db = tmp_path / "api.db"
    conn = store.connect(db)
    store.migrate(conn)
    for i in range(12):
        conn.execute(
            "INSERT INTO audit_log (actor, action, entity, entity_id) VALUES (?, ?, ?, ?)",
            ("alice" if i % 2 == 0 else "bob", "setting.update" if i < 8 else "model.load",
             "setting", str(i)),
        )
    conn.commit()
    conn.close()
    return TestClient(create_app(db))


def test_audit_page_returns_total_and_slice(client):
    first = client.get("/api/audit", params={"limit": 5, "offset": 0}).json()
    assert first["total"] == 12
    assert len(first["items"]) == 5
    assert first["items"][0]["id"] == 12  # 最新在前

    second = client.get("/api/audit", params={"limit": 5, "offset": 5}).json()
    assert len(second["items"]) == 5
    assert second["items"][0]["id"] == 7
    assert {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]} == set()


def test_audit_filters_apply_to_total(client):
    by_action = client.get("/api/audit", params={"action": "model.load"}).json()
    assert by_action["total"] == 4
    by_actor = client.get("/api/audit", params={"actor": "ali"}).json()
    assert by_actor["total"] == 6
    both = client.get("/api/audit", params={"action": "setting.update", "actor": "bob"}).json()
    assert both["total"] == 4
