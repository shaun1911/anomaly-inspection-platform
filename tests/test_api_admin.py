"""P0 验收：工作台指标、编码详情与时间线。"""

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
    base = np.full((64, 64, 3), 120, dtype=np.int16)
    arr = np.clip(base + rng.integers(-40, 40, (64, 64, 3)), 0, 255).astype(np.uint8)
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


def _seed(client) -> str:
    client.post("/api/codes", json={"code": "AB-1", "family": "支架"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 64, 64]})
    client.post("/api/thresholds", json={"model_version_id": version["id"], "roi_rev": 1, "rev": 1, "th_lo": 0.0, "th_hi": 1.0})
    for i in range(3):
        client.post(
            "/infer",
            data={"code": "AB-1", "station": "S1", "part_no": f"P-{i}"},
            files={"image": ("c.png", _png(i), "image/png")},
            headers={"Idempotency-Key": f"k{i}"},
        )
    return "AB-1"


def test_stats_today_counts_labels(client):
    _seed(client)
    stats = client.get("/api/stats/today").json()
    assert stats["total"] == 3
    assert stats["ok"] + stats["gray"] + stats["ng"] == 3
    assert 0.0 <= stats["ng_rate"] <= 1.0


def test_code_detail_aggregates_everything(client):
    code = _seed(client)
    detail = client.get(f"/api/codes/{code}/detail").json()
    assert detail["code"] == code
    assert detail["binding"]["model_code"] == "M1"
    assert detail["version"]["status"] == "assist"
    assert detail["config"]["roi_rect"] == [0, 0, 64, 64]
    assert detail["threshold"]["th_hi"] == 1.0
    assert len(detail["recent_results"]) == 3
    assert detail["case_count"] == 0


def test_code_detail_unknown_is_404(client):
    resp = client.get("/api/codes/NOPE/detail")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "unknown_code"


def test_timeline_is_desc_and_has_binding(client):
    code = _seed(client)
    events = client.get(f"/api/codes/{code}/timeline").json()
    assert len(events) >= 3
    kinds = {e["kind"] for e in events}
    assert "binding" in kinds and "config" in kinds and "threshold" in kinds
    times = [e["at"] for e in events]
    assert times == sorted(times, reverse=True)


def test_audit_recent_empty_shape(client):
    rows = client.get("/api/audit/recent").json()
    assert rows == []


def test_publish_syncs_binding_stage_and_writes_audit(client):
    client.post("/api/codes", json={"code": "AB-1"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})

    resp = client.put(
        f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"}
    )
    assert resp.status_code == 200
    assert resp.json()["bindings_updated"] == 1

    bindings = client.get("/api/bindings", params={"code": "AB-1"}).json()
    assert bindings[0]["stage"] == "assist"

    audit = client.get("/api/audit/recent").json()
    actions = {a["action"] for a in audit}
    assert "version.status" in actions
    assert "binding.create" in actions

