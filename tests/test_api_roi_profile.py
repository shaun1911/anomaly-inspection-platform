"""ROI 按编码 + 站位管理与回退。"""

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


def _seed(client) -> str:
    code = "AB-1"
    client.post("/api/codes", json={"code": code, "family": "支架类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": code, "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 280, 400]})
    client.post("/api/thresholds", json={"model_version_id": version["id"], "roi_rev": 1, "rev": 1, "th_lo": 0.4, "th_hi": 0.7})
    return code


def test_station_profile_wins_and_falls_back(client):
    code = _seed(client)
    s1 = client.put(
        f"/api/codes/{code}/roi-profiles",
        json={"station": "S1", "roi_rect": [10, 20, 300, 420], "note": "S1 重装"},
    )
    assert s1.status_code == 200, s1.text
    assert s1.json()["rev"] == 1

    cfg = client.get("/station/config", params={"code": code, "station": "S1"}).json()
    assert cfg["roi_rect"] == [10, 20, 300, 420]
    assert cfg["roi_source"] == "code+station"

    # 未配置的站位回退到版本 ROI
    cfg2 = client.get("/station/config", params={"code": code, "station": "S2"}).json()
    assert cfg2["roi_rect"] == [0, 0, 280, 400]
    assert cfg2["roi_source"] == "version"

    # 编码默认优先于版本，但低于具体站位
    default = client.put(
        f"/api/codes/{code}/roi-profiles",
        json={"station": "", "roi_rect": [0, 0, 260, 380]},
    )
    assert default.status_code == 200
    cfg2 = client.get("/station/config", params={"code": code, "station": "S2"}).json()
    assert cfg2["roi_rect"] == [0, 0, 260, 380]
    assert cfg2["roi_source"] == "code"
    cfg1 = client.get("/station/config", params={"code": code, "station": "S1"}).json()
    assert cfg1["roi_source"] == "code+station"

    profiles = client.get(f"/api/codes/{code}/roi-profiles").json()
    assert len(profiles) == 2
    assert {p["station"] for p in profiles} == {"S1", "(编码默认)"}
    assert client.get("/api/audit", params={"action": "roi_profile.save"}).json()["total"] == 2


def test_revision_and_validation(client):
    code = _seed(client)
    client.put(f"/api/codes/{code}/roi-profiles", json={"station": "S1", "roi_rect": [0, 0, 100, 100]})
    second = client.put(f"/api/codes/{code}/roi-profiles",
                         json={"station": "S1", "roi_rect": [0, 0, 120, 120]}).json()
    assert second["rev"] == 2
    profiles = client.get(f"/api/codes/{code}/roi-profiles").json()
    assert len(profiles) == 1  # 只有一条 active
    assert profiles[0]["roi_rect"] == [0, 0, 120, 120]

    bad = client.put(f"/api/codes/{code}/roi-profiles",
                      json={"station": "S1", "roi_rect": [10, 10, 5, 5]})
    assert bad.status_code == 400
    assert bad.json()["error_code"] == "bad_roi"
