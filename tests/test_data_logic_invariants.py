"""数据逻辑不变量（docs/designs/data-logic.md）的可执行版本。

每个测试对应文档里的一条不变量；改了它们等于改设计，必须同步文档。
"""

from __future__ import annotations

import io
import sqlite3

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aip import store, whitelist
from aip.api.app import create_app


def _png(seed: int = 1) -> bytes:
    rng = np.random.default_rng(seed)
    arr = np.clip(np.full((64, 64, 3), 120, dtype=np.int16) + rng.integers(-40, 40, (64, 64, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "none.yaml"))
    monkeypatch.setenv("AIP_TRAIN_BACKEND", "fake")
    whitelist.reset_cache()
    db = tmp_path / "api.db"
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()
    return TestClient(create_app(db))


def _prepared_model(client) -> tuple[int, int]:
    client.post("/api/codes", json={"code": "AB-1", "family": "支架类"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 64, 64]})
    client.post("/api/thresholds", json={"model_version_id": version["id"], "roi_rev": 1, "rev": 1, "th_lo": 0.0, "th_hi": 1.0})
    return model["id"], version["id"]


def _infer(client, key: str, part: str = "P-CHAIN-1", batch: str = "B-CHAIN") -> int:
    job = client.post(
        "/infer",
        data={"code": "AB-1", "station": "S1", "part_no": part, "batch_no": batch},
        files={"image": (f"{key}.png", _png(hash(key) % 500), "image/png")},
        headers={"Idempotency-Key": key},
    ).json()
    return job["job_id"]


# ---------- L1 ----------

def test_l1_result_must_carry_model_version(client):
    """result 必须记录 model_version_id，否则"按哪版判的"永久丢失。"""
    conn = store.connect(client.app.state.db_path)
    mid = conn.execute("INSERT INTO model (code) VALUES ('MX') RETURNING id").fetchone()["id"]
    conn.execute("INSERT INTO product_code (code) VALUES ('AB-X')")
    job = conn.execute(
        "INSERT INTO inference_job (code, idempotency_key, status) VALUES ('AB-X', 'kx', 'done')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO inference_result (job_id, score, label, model_version_id)"
            " VALUES (?, 0.5, 'ok', NULL)",
            (job.lastrowid,),
        )
    conn.close()
    _ = mid


def test_l1_idempotency_returns_same_job(client):
    _prepared_model(client)
    key = "same-key"
    first = client.post(
        "/infer",
        data={"code": "AB-1", "station": "S1"},
        files={"image": ("a.png", _png(7), "image/png")},
        headers={"Idempotency-Key": key},
    ).json()
    second = client.post(
        "/infer",
        data={"code": "AB-1", "station": "S1"},
        files={"image": ("b.png", _png(7), "image/png")},
        headers={"Idempotency-Key": key},
    ).json()
    assert first["job_id"] == second["job_id"]


# ---------- L2 ----------

def test_l2_case_inherits_batch_and_version(client):
    _prepared_model(client)
    _infer(client, "k1")
    conn = store.connect(client.app.state.db_path)
    result = conn.execute("SELECT id, model_version_id FROM inference_result ORDER BY id DESC LIMIT 1").fetchone()
    crop = conn.execute("SELECT crop_path FROM inference_result WHERE id = ?", (result["id"],)).fetchone()["crop_path"]
    conn.close()

    case_id = client.post(
        "/api/cases",
        json={"code": "AB-1", "crop_path": crop, "verdict": "ng",
              "adjudicator": "z", "source": "result", "result_id": result["id"]},
    ).json()["id"]
    conn = store.connect(client.app.state.db_path)
    case = conn.execute("SELECT batch_no, model_version_id, batch_source FROM case_item WHERE id = ?", (case_id,)).fetchone()
    conn.close()
    assert case["batch_no"] == "B-CHAIN"
    assert case["model_version_id"] == result["model_version_id"]
    assert case["batch_source"] == "station"


# ---------- L3 ----------

def test_l3_checksum_matches_frozen_members(client, tmp_path):
    import hashlib

    _prepared_model(client)
    _infer(client, "k2")
    conn = store.connect(client.app.state.db_path)
    crop = conn.execute("SELECT crop_path FROM inference_result ORDER BY id DESC LIMIT 1").fetchone()["crop_path"]
    conn.close()
    case_id = client.post(
        "/api/cases",
        json={"code": "AB-1", "crop_path": crop, "verdict": "ok", "adjudicator": "z"},
    ).json()["id"]

    model_id = client.get("/api/models").json()[0]["id"]
    ds = client.post("/api/datasets", json={"model_id": model_id, "name": "D"}).json()
    client.post(f"/api/datasets/{ds['id']}/items", json={"case_ids": [case_id]})
    checksum = client.post(f"/api/datasets/{ds['id']}/freeze").json()["checksum"]

    conn = store.connect(client.app.state.db_path)
    rows = conn.execute(
        "SELECT i.case_id, c.sha256 FROM dataset_item i JOIN case_item c ON c.id = i.case_id"
        " WHERE i.dataset_id = ? ORDER BY i.case_id",
        (ds["id"],),
    ).fetchall()
    digest = hashlib.sha256()
    for r in rows:
        digest.update(f"{r['case_id']}:{r['sha256'] or ''}\n".encode())
    conn.close()
    assert digest.hexdigest() == checksum


# ---------- L4 ----------

def test_l4_only_one_assist_per_model(client):
    _prepared_model(client)
    model_id = client.get("/api/models").json()[0]["id"]
    client.post(f"/api/models/{model_id}/versions", json={"version_no": 2})
    client.put(f"/api/models/{model_id}/versions/2/status", json={"status": "assist"})

    versions = {v["version_no"]: v["status"] for v in client.get("/api/models").json()[0]["versions"]}
    assert versions[2] == "assist"
    assert versions[1] == "disabled"


# ---------- 全链追溯 ----------

def test_traceability_chain_from_part_no(client):
    model_id, version_id = _prepared_model(client)
    job_id = _infer(client, "k3", part="P-TRACE-9", batch="B-TRACE")

    conn = store.connect(client.app.state.db_path)
    result = conn.execute("SELECT id, model_version_id FROM inference_result WHERE job_id = ?", (job_id,)).fetchone()
    crop = conn.execute("SELECT crop_path FROM inference_result WHERE id = ?", (result["id"],)).fetchone()["crop_path"]
    conn.close()

    case_id = client.post(
        "/api/cases",
        json={"code": "AB-1", "crop_path": crop, "verdict": "ng", "adjudicator": "z",
              "source": "result", "result_id": result["id"]},
    ).json()["id"]
    ds = client.post("/api/datasets", json={"model_id": model_id, "name": "TRACE"}).json()
    client.post(f"/api/datasets/{ds['id']}/items", json={"case_ids": [case_id]})
    client.post(f"/api/datasets/{ds['id']}/freeze")
    trained = client.post("/api/train", json={"model_id": model_id, "dataset_id": ds["id"]}).json()

    conn = store.connect(client.app.state.db_path)
    row = conn.execute(
        "SELECT j.part_no, j.batch_no, j.code, f.name AS family, mv.version_no AS judged_version,"
        " c.id AS case_id, d.id AS dataset_id, t.dataset_id AS trained_with, mv2.dataset_id AS version_dataset"
        " FROM inference_job j"
        " JOIN product_code p ON p.code = j.code"
        " LEFT JOIN family f ON f.id = p.family_id"
        " JOIN inference_result r ON r.job_id = j.id"
        " JOIN model_version mv ON mv.id = r.model_version_id"
        " JOIN case_item c ON c.result_id = r.id"
        " JOIN dataset_item i ON i.case_id = c.id"
        " JOIN dataset d ON d.id = i.dataset_id"
        " JOIN train_job t ON t.dataset_id = d.id"
        " JOIN model_version mv2 ON mv2.model_id = t.model_id AND mv2.version_no = ?"
        " WHERE j.part_no = ?",
        (trained["version_no"], "P-TRACE-9"),
    ).fetchone()
    conn.close()

    assert row is not None, "件号无法还原全链"
    assert row["batch_no"] == "B-TRACE"
    assert row["family"] == "支架类"
    assert row["case_id"] == case_id
    assert row["dataset_id"] == ds["id"]
    assert row["trained_with"] == ds["id"]
    assert row["version_dataset"] == ds["id"]
    _ = version_id
