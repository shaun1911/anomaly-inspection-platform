"""误判上报：站位上报、后台处理、改判与生成判例。"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aip import store, whitelist
from aip.api.app import create_app


def _png(seed: int = 1) -> bytes:
    rng = np.random.default_rng(seed)
    arr = np.clip(np.full((64, 64, 3), 120, dtype=np.int16) + rng.integers(-40, 40, (64, 64, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "none.yaml"))
    monkeypatch.setenv("AIP_TRAIN_BACKEND", "fake")
    whitelist.reset_cache()
    db = tmp_path / "api.db"
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()
    return TestClient(create_app(db))


def _seed(client) -> int:
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 64, 64]})
    client.post("/api/thresholds", json={"model_version_id": version["id"], "roi_rev": 1, "rev": 1, "th_lo": 0.0, "th_hi": 1.0})
    job = client.post(
        "/infer", data={"code": "AB-1", "station": "S1", "part_no": "P-1", "batch_no": "B-1"},
        files={"image": ("a.png", _png(), "image/png")},
        headers={"Idempotency-Key": "k-1"},
    ).json()
    return client.get(f"/infer/{job['job_id']}").json()["result"]["id"]


def test_report_and_accept_creates_case(client):
    rid = _seed(client)
    client.put("/api/settings/station.token", json={"value": "tok-1"})

    bad = client.post("/station/misjudge", json={"result_id": rid, "expected_verdict": "ng"})
    assert bad.status_code == 401

    ok = client.post(
        "/station/misjudge",
        json={"result_id": rid, "expected_verdict": "ng", "reason_code": "漏检",
              "note": "现场看到划伤", "station": "S1", "reported_by": "张三"},
        headers={"X-Station-Token": "tok-1"},
    )
    assert ok.status_code == 201, ok.text
    fid = ok.json()["id"]

    dup = client.post(
        "/station/misjudge",
        json={"result_id": rid, "expected_verdict": "ok"},
        headers={"X-Station-Token": "tok-1"},
    )
    assert dup.status_code == 409
    assert dup.json()["error_code"] == "feedback_open"

    listing = client.get("/api/feedback", params={"status": "open"}).json()
    assert listing["total"] == 1
    assert listing["summary"]["open"] == 1
    assert listing["items"][0]["expected_verdict"] == "ng"

    handled = client.post(
        f"/api/feedback/{fid}/handle",
        json={"action": "accept", "handled_by": "admin", "create_case": True, "note": "确认漏检"},
    )
    assert handled.status_code == 200, handled.text
    assert handled.json()["verdict"] == "ng"
    assert handled.json()["case_id"]

    detail = client.get(f"/infer/{client.get(f'/api/feedback/{fid}').status_code and 1}")  # noqa: F841
    result = client.get(f"/results/{rid}").json()
    assert result["label"] == "ng"
    assert result["review_status"] == "done"
    cases = client.get("/api/cases", params={"code": "AB-1"}).json()
    assert cases and cases[0]["verdict"] == "ng"
    assert client.get("/api/audit", params={"action": "feedback.report"}).json()["total"] == 1


def test_reject_keeps_verdict(client):
    rid = _seed(client)
    fid = client.post(
        "/station/misjudge",
        json={"result_id": rid, "expected_verdict": "ng", "note": "现场认为漏检"},
    ).json()["id"]
    before = client.get(f"/results/{rid}").json()["label"]
    out = client.post(f"/api/feedback/{fid}/handle",
                      json={"action": "reject", "handled_by": "admin", "note": "复核维持原判"})
    assert out.status_code == 200
    assert out.json()["status"] == "rejected"
    assert client.get(f"/results/{rid}").json()["label"] == before
