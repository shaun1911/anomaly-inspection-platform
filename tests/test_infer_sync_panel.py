"""同步推理与工位面板开关验收。"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aip import store, whitelist
from aip.api.app import create_app
from aip.settings import set_many


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "none.yaml"))
    whitelist.reset_cache()
    db = tmp_path / "data" / "aip.db"
    db.parent.mkdir()
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()
    c = TestClient(create_app(db))
    c.app.state.db_path = db
    return c


def _png(value: int = 120) -> bytes:
    rng = np.random.default_rng(7)
    arr = np.clip(np.full((96, 96, 3), value, dtype=np.int16) + rng.integers(-40, 40, (96, 96, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


def _ready(client) -> int:
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    vid = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()["id"]
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": vid, "rev": 1, "roi_rect": [0, 0, 96, 96]})
    client.post("/api/thresholds", json={"model_version_id": vid, "roi_rev": 1, "rev": 1,
                                        "th_lo": 0.2, "th_hi": 0.8})
    return vid


def test_sync_infer_returns_result_in_one_round_trip(client):
    _ready(client)
    resp = client.post(
        "/infer?sync=1",
        data={"code": "AB-1", "station": "S1", "part_no": "P-1", "batch_no": "B-1"},
        files={"image": ("a.png", _png(), "image/png")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "done"
    assert body["result"]["label"] in ("ok", "gray", "ng")
    assert 0.0 <= body["result"]["score"] <= 1.0


def test_async_infer_keeps_202(client):
    _ready(client)
    resp = client.post(
        "/infer",
        data={"code": "AB-1", "station": "S1"},
        files={"image": ("b.png", _png(), "image/png")},
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "done"


def test_duplicate_sync_returns_existing_result(client):
    _ready(client)
    files = {"image": ("c.png", _png(), "image/png")}
    data = {"code": "AB-1", "station": "S1"}
    first = client.post("/infer?sync=1", data=data, files=files, headers={"Idempotency-Key": "dup-1"})
    second = client.post("/infer?sync=1", data=data, files=files, headers={"Idempotency-Key": "dup-1"})
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["job_id"] == first.json()["job_id"]


def test_panel_enabled_by_default(client):
    assert client.get("/panel").status_code == 200


def test_panel_can_be_disabled(client):
    conn = store.connect(client.app.state.db_path)
    set_many(conn, {"ui.panel_enabled": False})
    conn.close()
    resp = client.get("/panel")
    assert resp.status_code == 404
    # 后台页面不受影响
    assert client.get("/admin").status_code == 200


def test_decision_mapping_is_pure():
    from aip.api.routes_infer import _decision

    conn = store.connect(":memory:")
    store.migrate(conn)
    try:
        assert _decision(conn, "ok") == {"action": "pass", "human_required": False}
        assert _decision(conn, "ng") == {"action": "block", "human_required": False}
        gray = _decision(conn, "gray")
        assert gray["action"] == "review" and gray["human_required"] is True

        set_many(conn, {"review.gray_route": "stop"})
        stopped = _decision(conn, "gray")
        assert stopped["action"] == "block"
        assert stopped["reason"] == "gray_stop"
        assert stopped["human_required"] is True
    finally:
        conn.close()


def test_sync_payload_includes_decision(client):
    _ready(client)
    body = client.post(
        "/infer?sync=1",
        data={"code": "AB-1", "station": "S1"},
        files={"image": ("d.png", _png(), "image/png")},
        headers={"Idempotency-Key": "decision-1"},
    ).json()
    assert body["decision"]["action"] in ("pass", "block", "review")
    assert "human_required" in body["decision"]
