"""数据集分类统计与训练/验证划分验收。"""

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


def _case(client, tmp_path, name: str, verdict: str, shade: int) -> int:
    img = tmp_path / name
    Image.new("RGB", (16, 16), (shade % 250 + 3, shade % 250 + 3, shade % 250 + 3)).save(img)
    return client.post(
        "/api/cases",
        json={"code": "AB-1", "crop_path": str(img), "verdict": verdict,
              "adjudicator": "z", "part_no": name},
    ).json()["id"]


def _dataset_with(client, tmp_path, ok: int, ng: int) -> tuple[int, int]:
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    ids = [_case(client, tmp_path, f"ok{i}.png", "ok", 10 + i * 7) for i in range(ok)]
    ids += [_case(client, tmp_path, f"ng{i}.png", "ng", 60 + i * 7) for i in range(ng)]
    ds = client.post("/api/datasets", json={"model_id": model["id"], "name": "D1"}).json()
    client.post(f"/api/datasets/{ds['id']}/items", json={"case_ids": ids})
    return model["id"], ds["id"]


def test_summary_counts_ok_ng_and_val(client, tmp_path):
    _, ds_id = _dataset_with(client, tmp_path, ok=10, ng=6)
    client.post(f"/api/datasets/{ds_id}/freeze")

    detail = client.get(f"/api/datasets/{ds_id}").json()
    s = detail["summary"]
    assert s["total"] == 16
    assert s["ok"] == 10
    assert s["ng"] == 6
    assert s["train_ok"] + s["val_ok"] == 10
    assert s["train_ng"] + s["val_ng"] == 6
    # 比例：正常 20% 进验证，缺陷 50%
    assert s["val_ok"] == 2
    assert s["val_ng"] == 3
    # 每类至少留一条训练
    assert s["train_ok"] >= 1 and s["train_ng"] >= 1

    # 明细里的 split 与统计一致
    val = [i for i in detail["items"] if i["split"] == "frozen_val"]
    assert len(val) == s["val_ok"] + s["val_ng"]


def test_tiny_class_stays_in_train(client, tmp_path):
    _, ds_id = _dataset_with(client, tmp_path, ok=1, ng=1)
    client.post(f"/api/datasets/{ds_id}/freeze")
    s = client.get(f"/api/datasets/{ds_id}").json()["summary"]
    assert s["val_ok"] == 0 and s["val_ng"] == 0
    assert s["train_ok"] == 1 and s["train_ng"] == 1


def test_list_exposes_class_counts(client, tmp_path):
    _, ds_id = _dataset_with(client, tmp_path, ok=5, ng=5)
    client.post(f"/api/datasets/{ds_id}/freeze")
    row = client.get("/api/datasets").json()[0]
    assert row["ok_count"] == 5
    assert row["ng_count"] == 5
    assert row["val_ok"] + row["val_ng"] == 3  # 5*0.2=1, 5*0.5=3(round 2.5→2? 见下)
