"""批次贯通验收：判定带批次 → 判例继承 → 按批查询。"""

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
    return version["id"]


def _submit(client, batch: str | None, key: str):
    data = {"code": "AB-1", "station": "S1", "part_no": "P-1"}
    if batch is not None:
        data["batch_no"] = batch
    return client.post(
        "/infer",
        data=data,
        files={"image": ("a.png", _png(hash(key) % 1000), "image/png")},
        headers={"Idempotency-Key": key},
    )


def test_batch_stored_and_returned(client):
    _seed(client)
    job = _submit(client, "B-2026-11-A", "k1").json()
    detail = client.get(f"/infer/{job['job_id']}").json()
    assert detail["batch_no"] == "B-2026-11-A"
    assert detail["part_no"] == "P-1"


def test_invalid_batch_rejected(client):
    _seed(client)
    resp = _submit(client, "批次 中文 空格", "k2")
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "batch_invalid"


def test_case_inherits_batch_from_result(client):
    _seed(client)
    job = _submit(client, "B-2026-11-B", "k3").json()
    conn = store.connect(client.app.state.db_path)
    row = conn.execute("SELECT id, crop_path FROM inference_result ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    client.post(
        "/api/cases",
        json={"code": "AB-1", "crop_path": row["crop_path"], "verdict": "ng",
              "adjudicator": "z", "source": "result", "result_id": row["id"]},
    )
    cases = client.get("/api/cases").json()
    assert cases[0]["batch_no"] == "B-2026-11-B"

    filtered = client.get("/api/cases", params={"batch_no": "B-2026-11-B"}).json()
    assert len(filtered) == 1
    assert client.get("/api/cases", params={"batch_no": "B-OTHER"}).json() == []
