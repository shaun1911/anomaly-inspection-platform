"""P3a 验收：训练任务、候选版本、发布与回滚。

训练必须引用已冻结的数据集（L3）。
"""

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


def _prepared(client, tmp_path) -> tuple[int, int]:
    """建好：族/编码/模型/绑定/判例/冻结数据集，返回 (model_id, dataset_id)。"""
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})

    img = tmp_path / "c.png"
    Image.new("RGB", (32, 32), (7, 7, 7)).save(img)
    case = client.post(
        "/api/cases",
        json={"code": "AB-1", "crop_path": str(img), "verdict": "ok", "adjudicator": "z"},
    ).json()

    ds = client.post("/api/datasets", json={"model_id": model["id"], "name": "D1"}).json()
    client.post(f"/api/datasets/{ds['id']}/items", json={"case_ids": [case["id"]]})
    client.post(f"/api/datasets/{ds['id']}/freeze")
    return model["id"], ds["id"]


def test_training_creates_candidate_with_metrics(client, tmp_path):
    mid, did = _prepared(client, tmp_path)
    resp = client.post("/api/train", json={"model_id": mid, "dataset_id": did})
    assert resp.status_code == 201
    body = resp.json()
    assert body["version_no"] == 1
    assert "recall" in body["metrics"]

    versions = client.get("/api/models").json()[0]["versions"]
    assert versions[0]["status"] == "candidate"

    jobs = client.get("/api/train").json()
    assert jobs[0]["status"] == "succeeded"
    assert jobs[0]["dataset_id"] == did
    assert jobs[0]["metrics"]["val_samples"] == 15


def test_training_requires_frozen_dataset(client, tmp_path):
    mid, did = _prepared(client, tmp_path)
    draft = client.post("/api/datasets", json={"model_id": mid, "name": "D2"}).json()
    resp = client.post("/api/train", json={"model_id": mid, "dataset_id": draft["id"]})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "dataset_not_frozen"


def test_training_rejects_wrong_model_dataset(client, tmp_path):
    mid, did = _prepared(client, tmp_path)
    other = client.post("/api/models", json={"code": "M2"}).json()
    resp = client.post("/api/train", json={"model_id": other["id"], "dataset_id": did})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "dataset_model_mismatch"


def test_training_unknown_model(client):
    resp = client.post("/api/train", json={"model_id": 999, "dataset_id": 1})
    assert resp.status_code == 404


def test_cancel_only_queued(client, tmp_path):
    mid, did = _prepared(client, tmp_path)
    job = client.post("/api/train", json={"model_id": mid, "dataset_id": did}).json()
    resp = client.post(f"/api/train/{job['job_id']}/cancel")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "not_cancellable"


def test_publish_demotes_previous_assist(client, tmp_path):
    mid, did = _prepared(client, tmp_path)
    client.post("/api/train", json={"model_id": mid, "dataset_id": did})
    client.post("/api/train", json={"model_id": mid, "dataset_id": did})

    client.put(f"/api/models/{mid}/versions/1/status", json={"status": "assist"})
    client.put(f"/api/models/{mid}/versions/2/status", json={"status": "assist"})

    versions = {v["version_no"]: v["status"] for v in client.get("/api/models").json()[0]["versions"]}
    assert versions[2] == "assist"
    assert versions[1] == "disabled"


def test_rollback_swaps_assist_and_updates_bindings(client, tmp_path):
    mid, did = _prepared(client, tmp_path)
    client.post("/api/train", json={"model_id": mid, "dataset_id": did})
    client.post("/api/train", json={"model_id": mid, "dataset_id": did})
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


def test_rollback_without_previous_is_409(client, tmp_path):
    mid, did = _prepared(client, tmp_path)
    client.post("/api/train", json={"model_id": mid, "dataset_id": did})
    client.put(f"/api/models/{mid}/versions/1/status", json={"status": "assist"})
    resp = client.post(f"/api/models/{mid}/rollback")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "no_previous"


def test_smoke_on_candidate_version(client):
    client.post("/api/codes", json={"code": "AB-1"})
    mid = client.post("/api/models", json={"code": "M1"}).json()["id"]
    client.post(f"/api/models/{mid}/versions", json={"version_no": 1})

    import numpy as np
    from PIL import Image as PILImage
    import io as _io

    rng = np.random.default_rng(1)
    arr = np.clip(np.full((64, 64, 3), 120, dtype=np.int16) + rng.integers(-40, 40, (64, 64, 3)), 0, 255).astype("uint8")
    buf = _io.BytesIO()
    PILImage.fromarray(arr, "RGB").save(buf, format="PNG")

    resp = client.post(
        f"/api/models/{mid}/versions/1/smoke",
        files={"file": ("s.png", buf.getvalue(), "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is True
    assert body["label"] in ("ok", "gray", "ng")
    assert 0 <= body["score"] <= 1


def test_smoke_rejects_tiny_image_and_unknown_version(client):
    client.post("/api/codes", json={"code": "AB-1"})
    mid = client.post("/api/models", json={"code": "M1"}).json()["id"]
    client.post(f"/api/models/{mid}/versions", json={"version_no": 1})

    import io as _io
    from PIL import Image as PILImage

    buf = _io.BytesIO()
    PILImage.new("RGB", (8, 8), (0, 0, 0)).save(buf, format="PNG")
    small = client.post(
        f"/api/models/{mid}/versions/1/smoke",
        files={"file": ("s.png", buf.getvalue(), "image/png")},
    )
    assert small.status_code == 200
    assert small.json()["passed"] is False
    assert small.json()["gate"] == "crop_too_small"

    missing = client.post(
        f"/api/models/{mid}/versions/9/smoke",
        files={"file": ("s.png", buf.getvalue(), "image/png")},
    )
    assert missing.status_code == 404

