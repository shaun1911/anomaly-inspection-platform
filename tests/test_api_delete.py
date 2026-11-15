"""删除验收：无引用可删，有引用必须拒绝（保护证据链）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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


def test_delete_unused_code_and_model(client):
    client.post("/api/codes", json={"code": "AB-1"})
    assert client.delete("/api/codes/AB-1").status_code == 200
    assert client.get("/api/codes").json() == []

    model = client.post("/api/models", json={"code": "M1"}).json()
    assert client.delete(f"/api/models/{model['id']}").status_code == 200
    assert client.get("/api/models").json() == []


def test_delete_code_blocked_by_binding(client):
    client.post("/api/codes", json={"code": "AB-1"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    r = client.delete("/api/codes/AB-1")
    assert r.status_code == 409
    assert r.json()["error_code"] == "code_in_use"


def test_delete_model_blocked_by_version(client):
    model = client.post("/api/models", json={"code": "M1"}).json()
    client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1})
    r = client.delete(f"/api/models/{model['id']}")
    assert r.status_code == 409
    assert r.json()["error_code"] == "model_in_use"


def test_delete_code_blocked_by_case(client, tmp_path):
    client.post("/api/codes", json={"code": "AB-1"})
    img = tmp_path / "c.png"
    Image.new("RGB", (16, 16), (1, 2, 3)).save(img)
    client.post("/api/cases", json={"code": "AB-1", "crop_path": str(img), "verdict": "ok", "adjudicator": "z"})
    r = client.delete("/api/codes/AB-1")
    assert r.status_code == 409
    assert "判例" in r.json()["message"]


def test_delete_unknown(client):
    assert client.delete("/api/codes/NOPE").status_code == 404
    assert client.delete("/api/models/999").status_code == 404
