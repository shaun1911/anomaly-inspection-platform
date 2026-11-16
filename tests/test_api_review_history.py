"""复判记录查询。"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aip import store, whitelist
from aip.api.app import create_app


def _png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    arr = np.clip(np.full((64, 64, 3), 120, dtype=np.int16) + rng.integers(-40, 40, (64, 64, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "none.yaml"))
    whitelist.reset_cache()
    db = tmp_path / "api.db"
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()
    return TestClient(create_app(db))


def _seed(client) -> int:
    client.post("/api/codes", json={"code": "AB-1"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 64, 64]})
    client.post("/api/thresholds", json={"model_version_id": version["id"], "roi_rev": 1, "rev": 1, "th_lo": 0.0, "th_hi": 1.0})
    job = client.post(
        "/infer",
        data={"code": "AB-1", "station": "S1", "part_no": "P-1"},
        files={"image": ("a.png", _png(1), "image/png")},
        headers={"Idempotency-Key": "k-1"},
    ).json()
    return client.get(f"/infer/{job['job_id']}").json()["result"]["id"]


def test_history_records_verdict_reason_actor(client):
    rid = _seed(client)
    r = client.post(f"/review/{rid}/confirm", json={"verdict": "ng", "note": "划痕", "confirmed_by": "alice"})
    assert r.status_code == 200, r.text

    out = client.get("/review/history", params={"actor": "alice", "verdict": "ng"}).json()
    assert out["total"] == 1
    item = out["items"][0]
    assert item["id"] == rid
    assert item["label"] == "ng"
    assert item["confirm_note"] == "划痕"
    assert item["confirmed_by"] == "alice"
    assert item["code"] == "AB-1"

    assert client.get("/review/history", params={"verdict": "ok"}).json()["total"] == 0
    assert client.get("/review/history", params={"since": "2999-01-01T00:00:00Z"}).json()["total"] == 0
