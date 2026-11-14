"""复核队列归类验收：按族/编码/批次分组与筛选。"""

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


def _seed(client, batch: str, parts: int = 2):
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    resp = client.post("/api/models", json={"code": "M1"})
    model_id = resp.json()["id"] if resp.status_code == 201 else client.get("/api/models").json()[0]["id"]
    versions = client.get("/api/models").json()[0]["versions"]
    if any(v["version_no"] == 1 for v in versions):
        version = {"id": 1}
    else:
        version = client.post(f"/api/models/{model_id}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model_id}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model_id})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 64, 64]})
    client.post("/api/thresholds", json={"model_version_id": version["id"], "roi_rev": 1, "rev": 1, "th_lo": 0.0, "th_hi": 1.0})

    for p in range(parts):
        client.post(
            "/infer",
            data={"code": "AB-1", "station": "S1", "part_no": f"P-{p}", "batch_no": batch},
            files={"image": (f"{p}.png", _png(p), "image/png")},
            headers={"Idempotency-Key": f"k-{batch}-{p}"},
        )


def test_group_by_family_and_code(client):
    _seed(client, "B-1")
    fam = client.get("/review/queue", params={"group_by": "family"}).json()
    assert fam["items"][0]["key"] == "支架类"
    assert fam["items"][0]["count"] == 2

    code = client.get("/review/queue", params={"group_by": "code"}).json()
    assert code["items"][0]["key"] == "AB-1"
    assert code["items"][0]["parts"] == 2


def test_group_by_batch_and_filter(client):
    _seed(client, "B-1")
    _seed(client, "B-2")
    batches = client.get("/review/queue", params={"group_by": "batch"}).json()
    keys = {it["key"]: it["count"] for it in batches["items"]}
    assert keys == {"B-1": 2, "B-2": 2}

    only_b2 = client.get("/review/queue", params={"batch": "B-2"}).json()
    assert only_b2["summary"]["total"] == 2

    only_fam = client.get("/review/queue", params={"family": "支架类"}).json()
    assert only_fam["summary"]["total"] == 4
