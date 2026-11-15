"""ONNX 绑定接口验收。"""

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


def _model(client) -> int:
    return client.post("/api/models", json={"code": "M1"}).json()["id"]


def test_bind_onnx_path(client, tmp_path):
    mid = _model(client)
    client.post(f"/api/models/{mid}/versions", json={"version_no": 1})
    f = tmp_path / "model.onnx"
    f.write_bytes(b"not-a-real-onnx")

    resp = client.put(f"/api/models/{mid}/versions/1/onnx", json={"onnx_path": str(f)})
    assert resp.status_code == 200
    versions = client.get("/api/models").json()[0]["versions"]
    assert versions[0]["onnx_path"] == str(f)


def test_bind_onnx_rejects_bad_paths(client, tmp_path):
    mid = _model(client)
    client.post(f"/api/models/{mid}/versions", json={"version_no": 1})

    bad_rel = client.put(f"/api/models/{mid}/versions/1/onnx", json={"onnx_path": "model.onnx"})
    assert bad_rel.status_code == 400
    assert bad_rel.json()["error_code"] == "bad_onnx_path"

    missing = client.put(
        f"/api/models/{mid}/versions/1/onnx", json={"onnx_path": str(tmp_path / "nope.onnx")}
    )
    assert missing.status_code == 400
    assert missing.json()["error_code"] == "onnx_missing"

    wrong_ext = tmp_path / "model.bin"
    wrong_ext.write_bytes(b"x")
    bad_ext = client.put(
        f"/api/models/{mid}/versions/1/onnx", json={"onnx_path": str(wrong_ext)}
    )
    assert bad_ext.status_code == 400


def test_bind_onnx_unknown_version(client, tmp_path):
    mid = _model(client)
    f = tmp_path / "m.onnx"
    f.write_bytes(b"x")
    resp = client.put(f"/api/models/{mid}/versions/9/onnx", json={"onnx_path": str(f)})
    assert resp.status_code == 404
