"""ONNX 导出与真实推理链路验收。"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

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
    conn.close()
    return TestClient(create_app(db))


def _png(size: int = 96, value: int = 120) -> bytes:
    rng = np.random.default_rng(3)
    arr = np.clip(np.full((size, size, 3), value, dtype=np.int16) + rng.integers(-30, 30, (size, size, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


def _model_version(client):
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    return model["id"], version["id"]


def test_export_stub_binds_onnx(client):
    mid, vid = _model_version(client)
    resp = client.post(f"/api/models/{mid}/versions/1/export", json={"backend": "stub"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["onnx_path"].endswith(".onnx")
    assert body["skipped"] is False

    versions = client.get("/api/models").json()[0]["versions"]
    assert versions[0]["onnx_path"] == body["onnx_path"]

    again = client.post(f"/api/models/{mid}/versions/1/export", json={"backend": "stub"})
    assert again.json()["skipped"] is True


def test_export_rejects_unknown_backend(client):
    mid, _ = _model_version(client)
    resp = client.post(f"/api/models/{mid}/versions/1/export", json={"backend": "anomalib"})
    assert resp.status_code == 400


def test_onnx_inference_end_to_end(client):
    mid, vid = _model_version(client)
    export = client.post(f"/api/models/{mid}/versions/1/export", json={"backend": "stub"}).json()
    assert export["onnx_path"]

    client.put(f"/api/models/{mid}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": mid})
    client.post("/api/configs", json={"model_version_id": vid, "rev": 1, "roi_rect": [0, 0, 96, 96]})
    client.post("/api/thresholds", json={"model_version_id": vid, "roi_rev": 1, "rev": 1,
                                        "th_lo": 0.2, "th_hi": 0.8})

    job = client.post(
        "/infer",
        data={"code": "AB-1", "station": "S1", "part_no": "P-1", "batch_no": "B-1"},
        files={"image": ("a.png", _png(96, 120), "image/png")},
        headers={"Idempotency-Key": "k-ort-1"},
    )
    assert job.status_code == 202
    detail = client.get(f"/infer/{job.json()['job_id']}").json()
    result = detail["result"]
    assert result is not None
    assert 0.0 <= result["score"] <= 1.0
    assert result["label"] in ("ok", "gray", "ng")
    assert client.get("/api/metrics").status_code == 200  # 缓存非空时工作台指标不能崩
    cache = client.get("/api/model-cache").json()
    assert cache["count"] >= 1
    assert cache["items"][0]["fake"] is False
