"""P2 验收：设置读写、校验、审计，以及守门阈值真的生效。"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aip import store, whitelist
from aip.api.app import create_app


def _png(size=(64, 64)) -> bytes:
    rng = np.random.default_rng(0)
    arr = np.clip(np.full((size[1], size[0], 3), 120, dtype=np.int16) + rng.integers(-40, 40, (size[1], size[0], 3)), 0, 255).astype(np.uint8)
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


def test_defaults_are_listed(client):
    rows = client.get("/api/settings").json()
    keys = {r["key"] for r in rows}
    assert "gate.min_side" in keys
    assert "reasons.list" in keys
    assert all(r["updated_by"] is None for r in rows)


def test_update_persists_and_audits(client):
    resp = client.put("/api/settings/gate.min_side", json={"value": 48, "actor": "zhoubin"})
    assert resp.status_code == 200
    assert resp.json()["value"] == 48

    rows = client.get("/api/settings").json()
    row = next(r for r in rows if r["key"] == "gate.min_side")
    assert row["value"] == 48
    assert row["updated_by"] == "zhoubin"

    audit = client.get("/api/audit/recent").json()
    assert any(a["action"] == "setting.update" for a in audit)


def test_invalid_value_is_rejected(client):
    resp = client.put("/api/settings/gate.min_side", json={"value": 1})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_setting"


def test_unknown_key_is_404(client):
    resp = client.put("/api/settings/nope.key", json={"value": 1})
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "unknown_setting"


def test_gate_threshold_comes_from_settings(client):
    client.post("/api/codes", json={"code": "AB-1"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 64, 64]})

    ok = client.post(
        "/infer",
        data={"code": "AB-1", "station": "S1"},
        files={"image": ("c.png", _png(), "image/png")},
        headers={"Idempotency-Key": "k1"},
    )
    assert ok.status_code == 202

    client.put("/api/settings/gate.min_side", json={"value": 200})
    rejected = client.post(
        "/infer",
        data={"code": "AB-1", "station": "S1"},
        files={"image": ("c2.png", _png(), "image/png")},
        headers={"Idempotency-Key": "k2"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "crop_too_small"


def test_reference_default_setting_is_bool(client):
    rows = {r["key"]: r for r in client.get("/api/settings").json()}
    assert rows["review.show_references_default"]["default"] is True
    assert rows["review.show_references_default"]["value"] is True

    resp = client.put(
        "/api/settings/review.show_references_default", json={"value": False}
    )
    assert resp.status_code == 200
    assert resp.json()["value"] is False

    rows = {r["key"]: r for r in client.get("/api/settings").json()}
    assert rows["review.show_references_default"]["value"] is False


def test_reference_default_setting_rejects_garbage(client):
    resp = client.put(
        "/api/settings/review.show_references_default", json={"value": "maybe"}
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_setting"

