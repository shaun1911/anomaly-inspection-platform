"""批量保存设置：原子性 + 单条审计。"""

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
    conn.close()
    return TestClient(create_app(db))


def test_bulk_saves_all_and_writes_one_audit(client):
    resp = client.post(
        "/api/settings/bulk",
        json={"values": {"gate.min_side": 40, "judge.gray_rate_max": 0.2}, "actor": "tech"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 2

    rows = {r["key"]: r for r in client.get("/api/settings").json()}
    assert rows["gate.min_side"]["value"] == 40
    assert rows["judge.gray_rate_max"]["value"] == 0.2

    audit = [a for a in client.get("/api/audit/recent").json() if a["action"] == "setting.bulk_update"]
    assert len(audit) == 1


def test_bulk_is_atomic_on_invalid_value(client):
    before = {r["key"]: r["value"] for r in client.get("/api/settings").json()}
    resp = client.post(
        "/api/settings/bulk",
        json={"values": {"gate.min_side": 40, "gate.min_brightness": 9999}},
    )
    assert resp.status_code == 400
    after = {r["key"]: r["value"] for r in client.get("/api/settings").json()}
    assert before == after


def test_bulk_rejects_unknown_key(client):
    resp = client.post("/api/settings/bulk", json={"values": {"nope.key": 1}})
    assert resp.status_code == 404
