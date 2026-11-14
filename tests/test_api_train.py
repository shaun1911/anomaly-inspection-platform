"""P3a 验收：训练任务、候选版本、发布与回滚。"""

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


def test_training_creates_candidate_with_metrics(client):
    mid = _model(client)
    resp = client.post("/api/train", json={"model_id": mid})
    assert resp.status_code == 201
    body = resp.json()
    assert body["version_no"] == 1
    assert "recall" in body["metrics"]

    versions = client.get("/api/models").json()[0]["versions"]
    assert versions[0]["status"] == "candidate"

    jobs = client.get("/api/train").json()
    assert jobs[0]["status"] == "succeeded"
    assert jobs[0]["metrics"]["val_samples"] == 15


def test_training_unknown_or_archived_model(client):
    assert client.post("/api/train", json={"model_id": 999}).status_code == 404
    mid = _model(client)
    client.post(f"/api/models/{mid}/archive")
    resp = client.post("/api/train", json={"model_id": mid})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "model_archived"


def test_cancel_only_queued(client):
    mid = _model(client)
    job = client.post("/api/train", json={"model_id": mid}).json()
    resp = client.post(f"/api/train/{job['job_id']}/cancel")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "not_cancellable"


def test_publish_demotes_previous_assist(client):
    mid = _model(client)
    client.post("/api/train", json={"model_id": mid})
    client.post("/api/train", json={"model_id": mid})

    client.put(f"/api/models/{mid}/versions/1/status", json={"status": "assist"})
    client.put(f"/api/models/{mid}/versions/2/status", json={"status": "assist"})

    versions = {v["version_no"]: v["status"] for v in client.get("/api/models").json()[0]["versions"]}
    assert versions[2] == "assist"
    assert versions[1] == "disabled"


def test_rollback_swaps_assist_and_updates_bindings(client):
    mid = _model(client)
    client.post("/api/codes", json={"code": "AB-1"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": mid})
    client.post("/api/train", json={"model_id": mid})
    client.post("/api/train", json={"model_id": mid})
    client.put(f"/api/models/{mid}/versions/1/status", json={"status": "assist"})
    client.put(f"/api/models/{mid}/versions/2/status", json={"status": "assist"})

    resp = client.post(f"/api/models/{mid}/rollback")
    assert resp.status_code == 200
    assert resp.json()["to"] == 1

    versions = {v["version_no"]: v["status"] for v in client.get("/api/models").json()[0]["versions"]}
    assert versions[1] == "assist"
    assert versions[2] == "disabled"

    binding = client.get("/api/bindings", params={"code": "AB-1"}).json()[0]
    assert binding["stage"] == "assist"


def test_rollback_without_previous_is_409(client):
    mid = _model(client)
    client.post("/api/train", json={"model_id": mid})
    client.put(f"/api/models/{mid}/versions/1/status", json={"status": "assist"})
    resp = client.post(f"/api/models/{mid}/rollback")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "no_previous"
