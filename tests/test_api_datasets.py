"""L3 数据集验收：族推导、加入判例、冻结与校验和、导入清单与上传。"""

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


def _case(client, tmp_path, code: str, name: str) -> int:
    img = tmp_path / name
    Image.new("RGB", (16, 16), (3, 3, 3)).save(img)
    return client.post(
        "/api/cases",
        json={"code": code, "crop_path": str(img), "verdict": "ok", "adjudicator": "z"},
    ).json()["id"]


def _setup(client, tmp_path):
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    client.post("/api/codes", json={"code": "CD-2", "family": "壳体类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    c1 = _case(client, tmp_path, "AB-1", "a.png")
    c2 = _case(client, tmp_path, "CD-2", "b.png")
    return model["id"], c1, c2


def test_dataset_family_inferred_from_model(client, tmp_path):
    mid, _, _ = _setup(client, tmp_path)
    ds = client.post("/api/datasets", json={"model_id": mid, "name": "D1"}).json()
    detail = client.get(f"/api/datasets/{ds['id']}").json()
    assert detail["family"] == "支架类"
    assert detail["count"] == 0


def test_add_items_filters_other_family(client, tmp_path):
    mid, c1, c2 = _setup(client, tmp_path)
    ds = client.post("/api/datasets", json={"model_id": mid, "name": "D1"}).json()
    r = client.post(f"/api/datasets/{ds['id']}/items", json={"case_ids": [c1, c2]}).json()
    assert r["added"] == [c1]
    assert r["skipped"] == [c2]


def test_freeze_computes_checksum_and_locks(client, tmp_path):
    mid, c1, _ = _setup(client, tmp_path)
    ds = client.post("/api/datasets", json={"model_id": mid, "name": "D1"}).json()
    client.post(f"/api/datasets/{ds['id']}/items", json={"case_ids": [c1]})

    frozen = client.post(f"/api/datasets/{ds['id']}/freeze").json()
    assert len(frozen["checksum"]) == 64

    again = client.post(f"/api/datasets/{ds['id']}/items", json={"case_ids": [c1]})
    assert again.status_code == 409
    assert again.json()["error_code"] == "dataset_frozen"


def test_empty_dataset_cannot_freeze(client, tmp_path):
    mid, _, _ = _setup(client, tmp_path)
    ds = client.post("/api/datasets", json={"model_id": mid, "name": "D1"}).json()
    resp = client.post(f"/api/datasets/{ds['id']}/freeze")
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "empty_dataset"


def test_export_csv_and_upload(client, tmp_path):
    mid, c1, _ = _setup(client, tmp_path)
    ds = client.post("/api/datasets", json={"model_id": mid, "name": "D1"}).json()
    client.post(f"/api/datasets/{ds['id']}/items", json={"case_ids": [c1]})
    client.post(f"/api/datasets/{ds['id']}/freeze")

    csv_resp = client.get(f"/api/datasets/{ds['id']}/export.csv")
    assert csv_resp.status_code == 200
    assert "case_id" in csv_resp.text

    img_bytes = (tmp_path / "a.png").read_bytes()
    up = client.post("/api/cases/upload", files={"file": ("x.png", img_bytes, "image/png")})
    assert up.status_code == 200
    assert up.json()["crop_path"].endswith(".png")
