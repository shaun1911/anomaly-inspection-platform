"""参考样例与判例图片验收。"""

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


def _seed(client) -> tuple[int, list[str]]:
    client.post("/api/codes", json={"code": "AB-1"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 64, 64]})
    client.post("/api/thresholds", json={"model_version_id": version["id"], "roi_rev": 1, "rev": 1, "th_lo": 0.0, "th_hi": 1.0})

    result_ids, crops = [], []
    for i in range(3):
        job = client.post(
            "/infer",
            data={"code": "AB-1", "station": "S1", "part_no": "P-1"},
            files={"image": (f"{i}.png", _png(i), "image/png")},
            headers={"Idempotency-Key": f"k{i}"},
        ).json()
        detail = client.get(f"/infer/{job['job_id']}").json()
        result_ids.append(detail["result"]["id"])

    conn = store.connect(client.app.state.db_path)
    crops = [r[0] for r in conn.execute("SELECT crop_path FROM inference_result ORDER BY id").fetchall()]
    conn.close()
    return result_ids[0], crops


def test_references_are_balanced_and_scoped_to_code(client):
    rid, crops = _seed(client)
    client.post("/api/cases", json={"code": "AB-1", "crop_path": crops[0], "verdict": "ok", "adjudicator": "z", "reason": "正常纹理"})
    client.post("/api/cases", json={"code": "AB-1", "crop_path": crops[1], "verdict": "ng", "adjudicator": "z", "reason": "边部划痕"})
    client.post("/api/codes", json={"code": "CD-2"})
    client.post("/api/cases", json={"code": "CD-2", "crop_path": crops[2], "verdict": "ng", "adjudicator": "z"})

    refs = client.get(f"/results/{rid}/references").json()
    assert refs["code"] == "AB-1"
    assert len(refs["ok"]) == 1
    assert len(refs["ng"]) == 1
    assert refs["enough"] is True
    assert refs["ok"][0]["reason"] == "正常纹理"
    assert all(c["case_id"] != 3 for c in refs["ng"])  # 不串编码


def test_references_empty_when_no_cases(client):
    rid, _ = _seed(client)
    refs = client.get(f"/results/{rid}/references").json()
    assert refs["ok"] == [] and refs["ng"] == []
    assert refs["enough"] is False
    assert refs["note"]


def test_references_unknown_result_404(client):
    assert client.get("/results/9999/references").status_code == 404


def test_case_image_served_and_guarded(client):
    _, crops = _seed(client)
    case_id = client.post(
        "/api/cases", json={"code": "AB-1", "crop_path": crops[0], "verdict": "ok", "adjudicator": "z"}
    ).json()["id"]
    resp = client.get(f"/api/cases/{case_id}/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")

    conn = store.connect(client.app.state.db_path)
    conn.execute("UPDATE case_item SET crop_path = ? WHERE id = ?", (r"C:\Windows\win.ini", case_id))
    conn.close()
    blocked = client.get(f"/api/cases/{case_id}/image")
    assert blocked.status_code == 403
