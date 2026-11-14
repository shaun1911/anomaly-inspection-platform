"""CRUD 验收：编码改/停用、模型改名/归档、解绑、判例改删。"""

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


def _seed(client):
    client.post("/api/codes", json={"code": "AB-1", "family": "支架"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 64, 64]})
    return model["id"]


def test_patch_code_description_but_not_code_string(client):
    _seed(client)
    resp = client.put("/api/codes/AB-1", json={"family": "支架", "part": "全型"})
    assert resp.status_code == 200
    row = next(c for c in client.get("/api/codes").json() if c["code"] == "AB-1")
    assert row["part"] == "全型"


def test_deactivate_blocks_station_config_with_410(client):
    _seed(client)
    assert client.post("/api/codes/AB-1/active", json={"active": False}).status_code == 200
    resp = client.get("/station/config", params={"code": "AB-1"})
    assert resp.status_code == 410
    assert resp.json()["error_code"] == "code_inactive"

    client.post("/api/codes/AB-1/active", json={"active": True})
    assert client.get("/station/config", params={"code": "AB-1"}).status_code == 200


def test_archive_model_blocked_when_bound_then_allowed_after_unbind(client):
    model_id = _seed(client)
    blocked = client.post(f"/api/models/{model_id}/archive")
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "model_in_use"

    binding = client.get("/api/bindings", params={"code": "AB-1"}).json()[0]
    assert client.delete(f"/api/bindings/{binding['id']}").status_code == 200
    assert client.post(f"/api/models/{model_id}/archive").status_code == 200


def test_unbind_makes_station_config_fail_with_409(client):
    _seed(client)
    binding = client.get("/api/bindings", params={"code": "AB-1"}).json()[0]
    client.delete(f"/api/bindings/{binding['id']}")
    resp = client.get("/station/config", params={"code": "AB-1"})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "no_binding"


def test_case_update_and_delete(client):
    _seed(client)
    case_id = client.post(
        "/api/cases",
        json={"code": "AB-1", "crop_path": "x.png", "verdict": "ok", "adjudicator": "z"},
    ).json()["id"]

    assert client.put(f"/api/cases/{case_id}", json={"verdict": "ng", "reason": "划痕"}).status_code == 200
    rows = client.get("/api/cases").json()
    assert rows[0]["verdict"] == "ng"
    assert rows[0]["reason"] == "划痕"

    assert client.delete(f"/api/cases/{case_id}").status_code == 200
    assert client.get("/api/cases").json() == []
    assert client.delete(f"/api/cases/{case_id}").status_code == 404


def test_patch_model_name_and_unknown_codes(client):
    model_id = _seed(client)
    assert client.put(f"/api/models/{model_id}", json={"name": "支架-全型"}).status_code == 200
    assert client.put("/api/codes/NOPE", json={"family": "x"}).status_code == 404


def test_threshold_rev_auto_increments(client):
    client.post("/api/models", json={"code": "M1"})
    version = client.post("/api/models/1/versions", json={"version_no": 1}).json()

    first = client.post(
        "/api/thresholds",
        json={"model_version_id": version["id"], "roi_rev": 1, "th_lo": 0.4, "th_hi": 0.7},
    )
    second = client.post(
        "/api/thresholds",
        json={"model_version_id": version["id"], "roi_rev": 1, "th_lo": 0.5, "th_hi": 0.8},
    )
    assert first.status_code == 201
    assert second.status_code == 201

    conn = store.connect(client.app.state.db_path)
    rows = conn.execute(
        "SELECT rev, th_lo FROM threshold_rev WHERE model_version_id = ? ORDER BY rev",
        (version["id"],),
    ).fetchall()
    conn.close()
    assert [r["rev"] for r in rows] == [1, 2]
    assert rows[-1]["th_lo"] == 0.5


def test_archive_blocked_when_bound_then_hidden_from_default_list(client):
    model_id = _seed(client)
    blocked = client.post("/api/codes/AB-1/archive")
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "code_in_use"

    binding = client.get("/api/bindings", params={"code": "AB-1"}).json()[0]
    client.delete(f"/api/bindings/{binding['id']}")
    assert client.post("/api/codes/AB-1/archive").status_code == 200

    default_codes = [c["code"] for c in client.get("/api/codes").json()]
    assert "AB-1" not in default_codes
    all_codes = client.get("/api/codes", params={"include_archived": True}).json()
    assert any(c["code"] == "AB-1" for c in all_codes)
    _ = model_id


def test_archived_code_is_410_at_station_and_restore_recovers(client):
    server = TestClient(client.app)
    server.post("/api/codes", json={"code": "AB-9"})
    resp = server.get("/station/config", params={"code": "AB-9"})
    assert resp.status_code in (409, 422)  # 未绑定

    server.post("/api/codes/AB-9/archive")
    resp = server.get("/station/config", params={"code": "AB-9"})
    assert resp.status_code == 410
    assert resp.json()["error_code"] == "code_archived"

    assert server.post("/api/codes/AB-9/restore").status_code == 200
    resp = server.get("/station/config", params={"code": "AB-9"})
    assert resp.status_code != 410

