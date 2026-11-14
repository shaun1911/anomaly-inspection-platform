"""判例库数据质量验收：去重、冲突、软删、来源与筛选。"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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


def _img(tmp_path, name: str, color: tuple[int, int, int]) -> str:
    path = tmp_path / name
    Image.new("RGB", (32, 32), color).save(path)
    return str(path)


def _seed(client):
    client.post("/api/codes", json={"code": "AB-1"})


def test_duplicate_same_image_is_rejected(client, tmp_path):
    _seed(client)
    path = _img(tmp_path, "a.png", (10, 20, 30))
    first = client.post("/api/cases", json={"code": "AB-1", "crop_path": path, "verdict": "ok", "adjudicator": "z"})
    assert first.status_code == 201

    dup = client.post("/api/cases", json={"code": "AB-1", "crop_path": path, "verdict": "ok", "adjudicator": "z"})
    assert dup.status_code == 409
    assert dup.json()["error_code"] == "case_duplicate"


def test_conflicting_verdict_marks_conflict_and_patch_clears(client, tmp_path):
    _seed(client)
    path = _img(tmp_path, "a.png", (10, 20, 30))
    case_id = client.post(
        "/api/cases", json={"code": "AB-1", "crop_path": path, "verdict": "ok", "adjudicator": "z"}
    ).json()["id"]

    dup = client.post("/api/cases", json={"code": "AB-1", "crop_path": path, "verdict": "ng", "adjudicator": "z"})
    assert dup.status_code == 409

    conflicts = client.get("/api/cases/conflicts").json()
    assert len(conflicts) == 1
    assert conflicts[0]["id"] == case_id

    assert client.put(f"/api/cases/{case_id}", json={"verdict": "ng"}).status_code == 200
    assert client.get("/api/cases/conflicts").json() == []


def test_archive_hides_and_restore_returns(client, tmp_path):
    _seed(client)
    path = _img(tmp_path, "a.png", (1, 2, 3))
    case_id = client.post(
        "/api/cases", json={"code": "AB-1", "crop_path": path, "verdict": "ok", "adjudicator": "z"}
    ).json()["id"]

    assert client.post(f"/api/cases/{case_id}/archive").status_code == 200
    assert client.get("/api/cases").json() == []
    assert len(client.get("/api/cases", params={"include_archived": True}).json()) == 1

    assert client.post(f"/api/cases/{case_id}/restore").status_code == 200
    assert len(client.get("/api/cases").json()) == 1


def test_filters_by_verdict_source_and_audit_written(client, tmp_path):
    _seed(client)
    p1 = _img(tmp_path, "a.png", (5, 5, 5))
    p2 = _img(tmp_path, "b.png", (6, 6, 6))
    client.post("/api/cases", json={"code": "AB-1", "crop_path": p1, "verdict": "ok", "adjudicator": "z", "source": "manual"})
    client.post("/api/cases", json={"code": "AB-1", "crop_path": p2, "verdict": "ng", "adjudicator": "li", "source": "result"})

    assert len(client.get("/api/cases", params={"verdict": "ok"}).json()) == 1
    assert len(client.get("/api/cases", params={"source": "result"}).json()) == 1
    assert len(client.get("/api/cases", params={"adjudicator": "li"}).json()) == 1

    audit = client.get("/api/audit/recent").json()
    assert any(a["action"] == "case.create" for a in audit)
