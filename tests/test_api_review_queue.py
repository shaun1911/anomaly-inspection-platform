"""复核队列（状态机）验收。"""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aip import store, whitelist
from aip.api.app import create_app


def _png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    arr = np.clip(np.full((64, 64, 3), 120, dtype=np.int16) + rng.integers(-40, 40, (64, 64, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "none.yaml"))
    whitelist.reset_cache()
    db = tmp_path / "api.db"
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()
    return TestClient(create_app(db))


def _seed(client, parts: int = 2, shots: int = 2) -> list[int]:
    client.post("/api/codes", json={"code": "AB-1"})
    model = client.post("/api/models", json={"code": "M1"}).json()
    version = client.post(f"/api/models/{model['id']}/versions", json={"version_no": 1}).json()
    client.put(f"/api/models/{model['id']}/versions/1/status", json={"status": "assist"})
    client.post("/api/bindings", json={"code": "AB-1", "model_id": model["id"]})
    client.post("/api/configs", json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 64, 64]})
    client.post("/api/thresholds", json={"model_version_id": version["id"], "roi_rev": 1, "rev": 1, "th_lo": 0.0, "th_hi": 1.0})

    ids: list[int] = []
    for p in range(parts):
        for s in range(shots):
            job = client.post(
                "/infer",
                data={"code": "AB-1", "station": "S1", "part_no": f"P-{p}"},
                files={"image": (f"{p}-{s}.png", _png(p * 10 + s), "image/png")},
                headers={"Idempotency-Key": f"k-{p}-{s}"},
            ).json()
            detail = client.get(f"/infer/{job['job_id']}").json()
            ids.append(detail["result"]["id"])
    return ids


def test_queue_groups_by_part(client):
    _seed(client, parts=2, shots=3)
    q = client.get("/review/queue", params={"group_by": "part"}).json()
    assert q["summary"]["total"] == 6
    assert len(q["items"]) == 2
    assert all(item["count"] == 3 for item in q["items"])


def test_queue_oldest_first(client):
    _seed(client, parts=1, shots=2)
    q = client.get("/review/queue", params={"group_by": "result", "sort": "oldest"}).json()
    times = [i["created_at"] for i in q["items"]]
    assert times == sorted(times)


def test_filters_by_code_and_label(client):
    _seed(client, parts=1, shots=2)
    assert client.get("/review/queue", params={"code": "NOPE"}).json()["summary"]["total"] == 0
    q = client.get("/review/queue", params={"label": "gray"}).json()
    assert all(i["label"] == "gray" for i in q["items"] if i.get("label"))


def test_claim_excludes_other_actor(client):
    ids = _seed(client, parts=1, shots=1)
    rid = ids[0]
    assert client.post(f"/review/{rid}/claim", json={"actor": "A"}).status_code == 200
    blocked = client.post(f"/review/{rid}/claim", json={"actor": "B"})
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "claimed_by_other"

    assert client.post(f"/review/{rid}/release", json={"actor": "A"}).status_code == 200
    assert client.post(f"/review/{rid}/claim", json={"actor": "B"}).status_code == 200


def test_skip_removes_from_queue(client):
    ids = _seed(client, parts=1, shots=1)
    rid = ids[0]
    assert client.post(f"/review/{rid}/skip", json={"actor": "A", "reason": "看不清"}).status_code == 200
    assert client.get("/review/queue").json()["summary"]["total"] == 0


def test_skip_requires_reason(client):
    ids = _seed(client, parts=1, shots=1)
    resp = client.post(f"/review/{ids[0]}/skip", json={"actor": "A", "reason": "  "})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "reason_required"


def test_confirm_marks_done_and_leaves_queue(client):
    ids = _seed(client, parts=1, shots=1)
    rid = ids[0]
    assert client.post(f"/review/{rid}/confirm", json={"verdict": "ok", "confirmed_by": "A"}).status_code == 200
    assert client.get("/review/queue").json()["summary"]["total"] == 0


def test_batch_claim_skips_taken(client):
    ids = _seed(client, parts=1, shots=2)
    client.post(f"/review/{ids[0]}/claim", json={"actor": "A"})
    out = client.post("/review/claim-batch", json={"actor": "B", "result_ids": ids}).json()
    assert out["claimed"] == [ids[1]]
    assert out["skipped"] == [ids[0]]


def test_confirm_without_verdict_keeps_system_label(client):
    ids = _seed(client, parts=1, shots=1)
    before = client.get(f"/results/{ids[0]}").json()["label"]
    resp = client.post(f"/review/{ids[0]}/confirm", json={"confirmed_by": "A"})
    assert resp.status_code == 200
    assert resp.json()["verdict"] == before


def test_confirm_flip_inverts_label(client):
    ids = _seed(client, parts=1, shots=1)
    before = client.get(f"/results/{ids[0]}").json()["label"]
    resp = client.post(f"/review/{ids[0]}/confirm", json={"flip": True, "confirmed_by": "A"})
    after = client.get(f"/results/{ids[0]}").json()["label"]
    assert resp.json()["verdict"] == after
    assert after != before


def test_accept_group_clears_all_shots_of_part(client):
    ids = _seed(client, parts=1, shots=3)
    assert len(ids) == 3
    for rid in ids:
        assert client.post(f"/review/{rid}/confirm", json={"confirmed_by": "A"}).status_code == 200
    assert client.get("/review/queue").json()["summary"]["total"] == 0


def test_skipped_bin_lists_reason_and_restores(client):
    ids = _seed(client, parts=1, shots=1)
    rid = ids[0]
    client.post(f"/review/{rid}/skip", json={"actor": "A", "reason": "光太暗看不清"})

    q = client.get("/review/queue").json()
    assert q["summary"]["skipped_count"] == 1
    assert q["summary"]["total"] == 0

    bin_rows = client.get("/review/skipped").json()
    assert bin_rows["count"] == 1
    assert bin_rows["items"][0]["reason"] == "光太暗看不清"
    assert bin_rows["items"][0]["claimed_by"] == "A"

    assert client.post(f"/review/{rid}/restore", json={"actor": "B"}).status_code == 200
    assert client.get("/review/skipped").json()["count"] == 0
    assert client.get("/review/queue").json()["summary"]["total"] == 1


def test_restore_rejects_non_skipped(client):
    ids = _seed(client, parts=1, shots=1)
    resp = client.post(f"/review/{ids[0]}/restore", json={"actor": "B"})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "not_skipped"

