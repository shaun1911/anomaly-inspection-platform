"""配置修订历史：值、顺序、当前标记数据。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aip import store, whitelist
from aip.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "none.yaml"))
    whitelist.reset_cache()
    db = tmp_path / "api.db"
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()
    return TestClient(create_app(db))


def test_config_and_threshold_history(client):
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    vid = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()["id"]
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})

    assert client.post("/api/configs", json={"model_version_id": vid, "rev": 1, "roi_rect": [0, 0, 512, 512]}).status_code == 201
    assert client.post("/api/configs", json={"model_version_id": vid, "rev": 2, "roi_rect": [0, 0, 280, 400]}).status_code == 201
    assert client.post("/api/thresholds", json={"model_version_id": vid, "roi_rev": 1, "th_lo": 0.45, "th_hi": 0.60}).status_code == 201
    assert client.post("/api/thresholds", json={"model_version_id": vid, "roi_rev": 2, "th_lo": 0.40, "th_hi": 0.70, "reason": "调松"}).status_code == 201

    d = client.get("/api/codes/AB-1/detail").json()
    assert d["config"]["rev"] == 2
    assert d["config"]["roi_rect"] == [0, 0, 280, 400]
    assert [c["rev"] for c in d["config_history"]] == [2, 1]
    assert d["config_history"][1]["roi_rect"] == [0, 0, 512, 512]
    assert d["threshold"]["rev"] == 1  # 阈值 rev 在 (version, roi_rev) 内自增
    assert d["threshold_history"][0]["th_lo"] == 0.40
    assert d["threshold_history"][0]["reason"] == "调松"
