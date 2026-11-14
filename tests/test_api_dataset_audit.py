"""数据集成员审计验收：冻结后改判/归档可被发现。"""

from __future__ import annotations

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


def _case(client, tmp_path, name: str) -> int:
    img = tmp_path / name
    shade = (abs(hash(name)) % 200) + 20
    Image.new("RGB", (16, 16), (shade, shade, shade)).save(img)
    r = client.post(
        "/api/cases",
        json={"code": "AB-1", "crop_path": str(img), "verdict": "ok", "adjudicator": "z"},
    )
    return r.json()["id"]


def _frozen_dataset(client, tmp_path, n: int = 2) -> tuple[int, list[int]]:
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    ids = [_case(client, tmp_path, f"c{i}.png") for i in range(n)]
    ds = client.post("/api/datasets", json={"model_id": model["id"], "name": "D1"}).json()
    client.post(f"/api/datasets/{ds['id']}/items", json={"case_ids": ids})
    client.post(f"/api/datasets/{ds['id']}/freeze")
    return ds["id"], ids


def test_audit_clean_after_freeze(client, tmp_path):
    ds_id, _ = _frozen_dataset(client, tmp_path)
    out = client.get(f"/api/datasets/{ds_id}/audit").json()
    assert out["clean"] is True
    assert out["total"] == 2


def test_audit_detects_verdict_change(client, tmp_path):
    ds_id, ids = _frozen_dataset(client, tmp_path)
    client.put(f"/api/cases/{ids[0]}", json={"verdict": "ng", "reason": "改判"})
    out = client.get(f"/api/datasets/{ds_id}/audit").json()
    assert out["clean"] is False
    assert len(out["verdict_changed"]) == 1
    assert out["verdict_changed"][0]["before"] == "ok"
    assert out["verdict_changed"][0]["after"] == "ng"


def test_audit_detects_archived_member(client, tmp_path):
    ds_id, ids = _frozen_dataset(client, tmp_path)
    client.post(f"/api/cases/{ids[0]}/archive")
    out = client.get(f"/api/datasets/{ds_id}/audit").json()
    assert len(out["archived"]) == 1
    assert out["archived"][0]["case_id"] == ids[0]
