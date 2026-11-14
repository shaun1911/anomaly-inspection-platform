"""族建模验收：族实体、族→模型一致性、按族抽样。"""

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
    arr = np.clip(np.full((32, 32, 3), 120, dtype=np.int16) + rng.integers(-30, 30, (32, 32, 3)), 0, 255).astype(np.uint8)
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


def test_code_with_family_creates_family(client):
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    fams = client.get("/api/families").json()
    assert [f["name"] for f in fams] == ["支架类"]
    assert fams[0]["code_count"] == 1

    codes = client.get("/api/codes").json()
    assert codes[0]["family"] == "支架类"


def test_duplicate_family_rejected(client):
    client.post("/api/families", json={"name": "支架类"})
    dup = client.post("/api/families", json={"name": " 支架类 "})
    assert dup.status_code == 409
    assert dup.json()["error_code"] == "family_exists"


def test_family_models_conflict_detection(client):
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    client.post("/api/codes", json={"code": "AB-2", "family": "支架类"})
    m1 = client.post("/api/models", json={"code": "M1"}).json()
    m2 = client.post("/api/models", json={"code": "M2"}).json()
    client.post("/api/bindings", json={"code": "AB-1", "model_id": m1["id"]})
    client.post("/api/bindings", json={"code": "AB-2", "model_id": m1["id"]})

    fam = client.get("/api/families").json()[0]
    same = client.get(f"/api/families/{fam['id']}/models").json()
    assert same["conflict"] is False
    assert same["model_ids"] == [m1["id"]]

    client.post("/api/bindings", json={"code": "AB-2", "model_id": m2["id"]})
    split = client.get(f"/api/families/{fam['id']}/models").json()
    assert split["conflict"] is True
    assert len(split["model_ids"]) == 2


def test_cases_can_be_sampled_by_family(client):
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    client.post("/api/codes", json={"code": "CD-2", "family": "壳体类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 32, 32]})
    client.post("/api/thresholds", json={"model_version_id": version["id"], "roi_rev": 1, "rev": 1, "th_lo": 0.0, "th_hi": 1.0})

    job = client.post(
        "/infer",
        data={"code": "AB-1", "station": "S1", "part_no": "P-1"},
        files={"image": ("a.png", _png(1), "image/png")},
        headers={"Idempotency-Key": "k1"},
    ).json()
    conn = store.connect(client.app.state.db_path)
    crop = conn.execute("SELECT crop_path FROM inference_result ORDER BY id DESC LIMIT 1").fetchone()["crop_path"]
    conn.close()
    client.post("/api/cases", json={"code": "AB-1", "crop_path": crop, "verdict": "ok",
                                    "adjudicator": "z", "part_no": "P-1"})

    assert len(client.get("/api/cases", params={"family": "支架类"}).json()) == 1
    assert client.get("/api/cases", params={"family": "壳体类"}).json() == []


def test_export_dataset_by_family(client, tmp_path):
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    img = tmp_path / "a.png"
    Image.new("RGB", (16, 16), (9, 9, 9)).save(img)
    client.post("/api/cases", json={"code": "AB-1", "crop_path": str(img), "verdict": "ng",
                                    "adjudicator": "z", "part_no": "P-9", "reason": "划痕"})

    resp = client.get("/api/export/dataset", params={"family": "支架类"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    body = resp.text
    assert "part_no" in body
    assert "P-9" in body
    assert "划痕" in body

