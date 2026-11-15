"""全局搜索验收。"""

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


def test_empty_query_returns_empty(client):
    out = client.get("/api/search", params={"q": ""}).json()
    assert out == {"codes": [], "parts": [], "models": []}


def test_search_finds_code_part_and_model(client):
    client.post("/api/codes", json={"code": "AB-1234-01", "family": "支架类"})
    model = client.post("/api/models", json={"code": "M1", "name": "支架模型"}).json()
    client.post("/api/bindings", json={"code": "AB-1234-01", "model_id": model["id"]})
    conn = store.connect(client.app.state.db_path)
    conn.execute(
        "INSERT INTO inference_job (code, part_no, idempotency_key, status)"
        " VALUES ('AB-1234-01', 'P-20261115-0007', 'k1', 'done')"
    )
    conn.commit()
    conn.close()

    by_code = client.get("/api/search", params={"q": "AB-1234"}).json()
    assert [c["code"] for c in by_code["codes"]] == ["AB-1234-01"]
    assert by_code["codes"][0]["family"] == "支架类"

    by_part = client.get("/api/search", params={"q": "0007"}).json()
    assert [p["part_no"] for p in by_part["parts"]] == ["P-20261115-0007"]

    by_model = client.get("/api/search", params={"q": "支架"}).json()
    assert [m["code"] for m in by_model["models"]] == ["M1"]


def test_search_ignores_archived_codes(client):
    client.post("/api/codes", json={"code": "CD-9"})
    client.post("/api/codes/CD-9/archive")
    out = client.get("/api/search", params={"q": "CD-9"}).json()
    assert out["codes"] == []
