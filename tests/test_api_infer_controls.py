"""接入控制验收：强制件号/批次、裁片尺寸校验、站位令牌。"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aip import store, whitelist
from aip.api.app import create_app


def _png(size: int = 64, seed: int = 1) -> bytes:
    rng = np.random.default_rng(seed)
    arr = np.clip(np.full((size, size, 3), 120, dtype=np.int16) + rng.integers(-40, 40, (size, size, 3)), 0, 255).astype(np.uint8)
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


def _prepare(client, roi=(0, 0, 64, 64)) -> None:
    client.post("/api/codes", json={"code": "AB-1"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": list(roi)})
    client.post("/api/thresholds", json={"model_version_id": version["id"], "roi_rev": 1, "rev": 1, "th_lo": 0.0, "th_hi": 1.0})


def _infer(client, **kwargs):
    data = {"code": "AB-1", "station": "S1"}
    headers = {"Idempotency-Key": kwargs.pop("key", "k1")}
    headers.update(kwargs.pop("headers", {}))
    data.update(kwargs.pop("data", {}))
    return client.post(
        "/infer", data=data, files={"image": ("a.png", _png(kwargs.pop("size", 64), kwargs.pop("seed", 1)), "image/png")},
        headers=headers,
    )


def test_require_part_no_and_batch(client):
    _prepare(client)
    assert _infer(client, key="k0").status_code == 202

    client.put("/api/settings/infer.require_part_no", json={"value": True})
    missing = _infer(client, key="k1")
    assert missing.status_code == 400
    assert missing.json()["error_code"] == "missing_part_no"
    assert _infer(client, key="k2", data={"part_no": "P-1"}).status_code == 202

    client.put("/api/settings/infer.require_batch_no", json={"value": True})
    no_batch = _infer(client, key="k3", data={"part_no": "P-2"})
    assert no_batch.status_code == 400
    assert no_batch.json()["error_code"] == "missing_batch_no"
    ok = _infer(client, key="k4", data={"part_no": "P-3", "batch_no": "B-1"})
    assert ok.status_code == 202


def test_crop_size_must_match_roi(client):
    _prepare(client, roi=(0, 0, 64, 64))
    bad = _infer(client, key="k1", size=96, seed=9)
    assert bad.status_code == 422
    assert bad.json()["error_code"] == "crop_roi_mismatch"

    client.put("/api/settings/infer.crop_size_tolerance", json={"value": 0})
    assert _infer(client, key="k2", size=96, seed=9).status_code == 202


def test_station_token_enforced(client):
    _prepare(client)
    client.put("/api/settings/station.token", json={"value": "tok-123"})

    denied = _infer(client, key="k1")
    assert denied.status_code == 401
    assert denied.json()["error_code"] == "bad_station_token"

    allowed = _infer(client, key="k2", headers={"X-Station-Token": "tok-123"})
    assert allowed.status_code == 202

    assert client.get("/station/config", params={"code": "AB-1"}).status_code == 401
    ok_cfg = client.get(
        "/station/config", params={"code": "AB-1"}, headers={"X-Station-Token": "tok-123"}
    )
    assert ok_cfg.status_code == 200
