"""T1-2 / T1-5 验收：编码→模型→配置→阈值链路，以及白名单与错误码。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aip import store, whitelist
from aip.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "no-whitelist.yaml"))
    whitelist.reset_cache()
    db = tmp_path / "api.db"
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()
    return TestClient(create_app(db))


def _seed(client) -> None:
    assert client.post("/api/codes", json={"code": "AB-1"}).status_code == 201
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(
        f"/api/models/{model['id']}/versions", json={"version_no": 1}
    ).json()
    client.put(
        f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"}
    )
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post(
        "/api/configs",
        json={"model_version_id": version["id"], "rev": 1, "roi_rect": [10, 20, 300, 400]},
    )
    client.post(
        "/api/thresholds",
        json={
            "model_version_id": version["id"],
            "roi_rev": 1,
            "rev": 1,
            "th_lo": 0.4,
            "th_hi": 0.7,
        },
    )


def test_station_config_returns_version_roi_and_threshold(client):
    _seed(client)
    resp = client.get("/station/config", params={"code": "AB-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["version_no"] == 1
    assert body["roi_rect"] == [10, 20, 300, 400]
    assert body["threshold"]["th_lo"] == 0.4
    assert body["threshold"]["th_hi"] == 0.7


def test_station_config_unknown_code_returns_422(client):
    resp = client.get("/station/config", params={"code": "NOPE"})
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "unknown_code"


def test_station_config_without_binding_returns_409(client):
    client.post("/api/codes", json={"code": "ZZ-9"})
    resp = client.get("/station/config", params={"code": "ZZ-9"})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "no_binding"


def test_whitelist_blocks_other_codes(client, tmp_path, monkeypatch):
    path = tmp_path / "shift.yaml"
    path.write_text("codes:\n  - AB-1\n", encoding="utf-8")
    monkeypatch.setenv("AIP_WHITELIST", str(path))
    whitelist.reset_cache()

    _seed(client)
    ok = client.get("/station/config", params={"code": "AB-1"})
    assert ok.status_code == 200

    client.post("/api/codes", json={"code": "CD-2"})
    blocked = client.get("/station/config", params={"code": "CD-2"})
    assert blocked.status_code == 403
    assert blocked.json()["error_code"] == "not_in_shift"
    assert blocked.json()["action"]


def test_heartbeat_upserts_station(client):
    first = client.post("/station/heartbeat", json={"station": "S1", "config_rev": "1:1"})
    assert first.status_code == 200
    second = client.post("/station/heartbeat", json={"station": "S1", "config_rev": "1:2"})
    assert second.json()["ok"] is True

    conn = store.connect(client.app.state.db_path)
    rows = conn.execute("SELECT * FROM station WHERE name = 'S1'").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["last_config_rev"] == "1:2"


def test_threshold_direction_is_enforced(client):
    client.post("/api/models", json={"code": "M2"})
    version = client.post("/api/models/1/versions", json={"version_no": 1}).json()
    bad = client.post(
        "/api/thresholds",
        json={
            "model_version_id": version["id"],
            "roi_rev": 1,
            "rev": 1,
            "th_lo": 0.8,
            "th_hi": 0.2,
        },
    )
    assert bad.status_code == 409
    good = client.post(
        "/api/thresholds",
        json={
            "model_version_id": version["id"],
            "roi_rev": 1,
            "rev": 1,
            "th_lo": 0.8,
            "th_hi": 0.2,
            "mode": "high_overkill",
        },
    )
    assert good.status_code == 201
