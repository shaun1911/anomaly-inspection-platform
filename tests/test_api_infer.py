"""T1-3 / T1-4 验收：提交→判定→查询→复核的整条链路。"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aip import store, whitelist
from aip.api.app import create_app


def _png_bytes(color=(120, 120, 120), size=(64, 64), noise_max: int = 60) -> bytes:
    """带纹理的图：纯色图会被入口守门以"对比度低"拒绝。"""
    rng = np.random.default_rng(0)
    noise = rng.integers(0, max(1, noise_max), size=(size[1], size[0], 3), dtype=np.uint8)
    base = np.full((size[1], size[0], 3), color, dtype=np.uint8)
    array = np.clip(base + noise, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(array, "RGB").save(buf, format="PNG")
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


def _seed(client, th_lo=0.0, th_hi=0.0) -> None:
    client.post("/api/codes", json={"code": "AB-1"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post(
        "/api/configs",
        json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 64, 64]},
    )
    client.post(
        "/api/thresholds",
        json={
            "model_version_id": version["id"],
            "roi_rev": 1,
            "rev": 1,
            "th_lo": th_lo,
            "th_hi": th_hi,
        },
    )


def _submit(client, image: bytes | None = None, key: str = "k1", code: str = "AB-1"):
    return client.post(
        "/infer",
        data={"code": code, "station": "S1", "part_no": "P-1"},
        files={"image": ("crop.png", image or _png_bytes(), "image/png")},
        headers={"Idempotency-Key": key},
    )


def test_submit_returns_202_and_result_is_queryable(client):
    _seed(client)
    resp = _submit(client)
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    detail = client.get(f"/infer/{job_id}").json()
    assert detail["status"] == "done"
    assert detail["result"]["label"] == "ng"
    assert 0.0 <= detail["result"]["score"] <= 1.0


def test_duplicate_idempotency_key_returns_same_job(client):
    _seed(client)
    first = _submit(client).json()
    second = _submit(client, image=_png_bytes((130, 130, 130))).json()
    assert first["job_id"] == second["job_id"]
    assert second["duplicate"] is True


def test_gate_rejects_tiny_crop(client):
    _seed(client)
    resp = _submit(client, image=_png_bytes(size=(8, 8)))
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "crop_too_small"
    assert resp.json()["action"]


def test_gate_rejects_dark_crop(client):
    _seed(client)
    resp = _submit(client, image=_png_bytes(color=(0, 0, 0), noise_max=4))
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "crop_too_dark"


def test_unknown_code_is_422(client):
    _seed(client)
    resp = _submit(client, code="NOPE")
    assert resp.status_code == 422
    assert resp.json()["error_code"] in ("unknown_code", "not_in_shift")


def test_feedback_is_recorded_once_per_result(client):
    _seed(client)
    job = _submit(client).json()
    result_id = client.get(f"/infer/{job['job_id']}").json()["result"]["id"]

    ok = client.post("/infer/feedback", json={"result_id": result_id, "verdict": "ok"})
    assert ok.status_code == 201
    again = client.post("/infer/feedback", json={"result_id": result_id, "verdict": "ng"})
    assert again.status_code == 201

    conn = store.connect(client.app.state.db_path)
    rows = conn.execute("SELECT * FROM feedback WHERE result_id = ?", (result_id,)).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["verdict"] == "ng"


def test_review_pending_filters_by_station_and_confirm_clears_it(client):
    _seed(client)
    job = _submit(client).json()
    result_id = client.get(f"/infer/{job['job_id']}").json()["result"]["id"]

    pending = client.get("/review/pending", params={"station": "S1"}).json()
    assert pending["count"] == 1
    assert pending["items"][0]["result_id"] == result_id

    other = client.get("/review/pending", params={"station": "S2"}).json()
    assert other["count"] == 0

    confirmed = client.post(
        f"/review/{result_id}/confirm",
        json={"verdict": "ok", "note": "误报", "confirmed_by": "op-07"},
    )
    assert confirmed.status_code == 200

    after = client.get("/review/pending", params={"station": "S1"}).json()
    assert after["count"] == 0


def test_results_list_and_detail(client):
    _seed(client)
    job = _submit(client).json()
    result_id = client.get(f"/infer/{job['job_id']}").json()["result"]["id"]

    listed = client.get("/results", params={"code": "AB-1"}).json()
    assert len(listed) == 1
    assert listed[0]["id"] == result_id

    detail = client.get(f"/results/{result_id}").json()
    assert detail["code"] == "AB-1"
    assert detail["part_no"] == "P-1"
    assert detail["original_w"] == 64
    assert detail["confirmed_at"] is None


def test_result_image_is_served(client):
    _seed(client)
    job = _submit(client).json()
    result_id = client.get(f"/infer/{job['job_id']}").json()["result"]["id"]

    resp = client.get(f"/results/{result_id}/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")


def test_result_image_rejects_path_outside_data_root(client):
    _seed(client)
    job = _submit(client).json()
    result_id = client.get(f"/infer/{job['job_id']}").json()["result"]["id"]

    conn = store.connect(client.app.state.db_path)
    conn.execute(
        "UPDATE inference_result SET crop_path = ? WHERE id = ?",
        (r"C:\Windows\win.ini", result_id),
    )
    conn.close()

    resp = client.get(f"/results/{result_id}/image")
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "image_outside_root"


def test_result_image_missing_is_404(client):
    resp = client.get("/results/99999/image")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "result_not_found"

