"""盲判抽检验收：抽样不泄底、判完才能关、三方签字、指标冻结。"""

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


def _seed(client, labels: list[str]) -> None:
    conn = store.connect(client.app.state.db_path)
    conn.execute("INSERT INTO product_code (code) VALUES ('AB-1')")
    conn.execute("INSERT INTO model (code) VALUES ('M1')")
    mid = conn.execute("SELECT id FROM model").fetchone()["id"]
    conn.execute(
        "INSERT INTO model_version (model_id, version_no, status) VALUES (?, 1, 'assist')", (mid,)
    )
    vid = conn.execute("SELECT id FROM model_version").fetchone()["id"]
    for i, label in enumerate(labels):
        cur = conn.execute(
            "INSERT INTO inference_job (code, part_no, idempotency_key, status)"
            " VALUES ('AB-1', ?, ?, 'done')",
            (f"P-{i}", f"k{i}"),
        )
        conn.execute(
            "INSERT INTO inference_result (job_id, score, label, model_version_id)"
            " VALUES (?, 0.9, ?, ?)",
            (cur.lastrowid, label, vid),
        )
    conn.commit()
    conn.close()


def _create(client, size: int = 6) -> int:
    return client.post("/api/blind/batches", json={"week": "2026-W46", "sample_size": size}).json()["id"]


def test_create_batch_and_week_unique(client):
    _seed(client, ["ok", "ng", "gray", "ok", "ng", "ok"])
    bid = _create(client)
    detail = client.get(f"/api/blind/batches/{bid}").json()
    assert detail["total"] == 6
    assert detail["status"] == "open"

    dup = client.post("/api/blind/batches", json={"week": "2026-W46", "sample_size": 6})
    assert dup.status_code == 409
    assert dup.json()["error_code"] == "week_exists"


def test_open_batch_does_not_leak_system_labels(client):
    _seed(client, ["ok", "ng", "ok"])
    bid = _create(client, 3)
    items = client.get(f"/api/blind/batches/{bid}").json()["items"]
    assert all("system_label" not in it for it in items)
    assert all(it["image_url"].startswith("/api/blind/items/") for it in items)


def test_close_requires_all_judged_and_signoffs(client):
    _seed(client, ["ok", "ng", "ok"])
    bid = _create(client, 3)
    items = client.get(f"/api/blind/batches/{bid}").json()["items"]

    signoffs = {"signed_quality": "qa", "signed_line": "line", "signed_tech": "tech"}
    early = client.post(f"/api/blind/batches/{bid}/close", json=signoffs)
    assert early.status_code == 409
    assert early.json()["error_code"] == "not_all_judged"

    for it in items:
        assert client.post(f"/api/blind/items/{it['id']}/judge", json={"human_label": "ok", "judge": "op"}).status_code == 200

    missing = client.post(f"/api/blind/batches/{bid}/close", json={"signed_quality": "", "signed_line": "l", "signed_tech": "t"})
    assert missing.status_code == 400


def test_low_ng_requires_force_and_metrics_are_frozen(client):
    _seed(client, ["ng", "ng", "ok", "ok", "gray"])
    client.put("/api/settings/sampling.min_ng", json={"value": 1})
    bid = _create(client, 5)
    conn = store.connect(client.app.state.db_path)
    rows = conn.execute(
        "SELECT id, system_label FROM blind_item WHERE batch_id = ? ORDER BY id", (bid,)
    ).fetchall()
    conn.close()

    human: dict[int, str] = {}
    missed_id = next(r["id"] for r in rows if r["system_label"] != "ng")
    overkill_id = next(r["id"] for r in rows if r["system_label"] == "ng")
    for r in rows:
        if r["id"] == missed_id:
            human[r["id"]] = "ng"
        elif r["id"] == overkill_id:
            human[r["id"]] = "ok"
        else:
            human[r["id"]] = r["system_label"]

    for item_id, label in human.items():
        client.post(f"/api/blind/items/{item_id}/judge", json={"human_label": label, "judge": "op"})

    exp_ng = sum(1 for v in human.values() if v == "ng")
    exp_ok = sum(1 for v in human.values() if v == "ok")
    exp_missed = 1
    exp_overkill = 1

    signoffs = {"signed_quality": "qa", "signed_line": "line", "signed_tech": "tech"}
    resp = client.post(f"/api/blind/batches/{bid}/close", json=signoffs)
    assert resp.status_code == 200
    m = resp.json()["metrics"]
    assert m["human_ng"] == exp_ng
    assert m["human_ok"] == exp_ok
    assert m["missed"] == exp_missed
    assert m["overkill"] == exp_overkill
    assert m["recall"] == round((exp_ng - exp_missed) / exp_ng, 4)
    assert m["overkill_rate"] == round(exp_overkill / exp_ok, 4)

    detail = client.get(f"/api/blind/batches/{bid}").json()
    assert detail["status"] == "closed"
    assert all("system_label" in it for it in detail["items"])
    assert detail["signed_quality"] == "qa"

    assert client.post(f"/api/blind/batches/{bid}/close", json=signoffs).status_code == 409


def test_low_ng_blocks_without_force(client):
    _seed(client, ["ng", "ok", "ok"])
    bid = _create(client, 3)
    items = client.get(f"/api/blind/batches/{bid}").json()["items"]
    for it in items:
        client.post(f"/api/blind/items/{it['id']}/judge", json={"human_label": "ok", "judge": "op"})
    resp = client.post(
        "/api/blind/batches/%d/close" % bid,
        json={"signed_quality": "qa", "signed_line": "l", "signed_tech": "t"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "low_ng"
