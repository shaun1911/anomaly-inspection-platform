"""存储布局与迁移锁验收。"""

from __future__ import annotations

import io
import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from aip import storage, store, whitelist
from aip.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "none.yaml"))
    whitelist.reset_cache()
    db = tmp_path / "data" / "aip.db"
    db.parent.mkdir()
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()
    return TestClient(create_app(db))


def _png() -> bytes:
    rng = np.random.default_rng(1)
    arr = np.clip(np.full((64, 64, 3), 120, dtype=np.int16) + rng.integers(-40, 40, (64, 64, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


def test_infer_blocked_while_maintenance(client):
    with storage.maintenance():
        resp = client.post(
            "/infer",
            data={"code": "AB-1", "station": "S1"},
            files={"image": ("a.png", _png(), "image/png")},
            headers={"Idempotency-Key": "k1"},
        )
    assert resp.status_code == 503
    assert resp.json()["error_code"] == "maintenance"
    assert storage.is_locked() is False


def test_case_upload_blocked_while_maintenance(client):
    with storage.maintenance():
        resp = client.post(
            "/api/cases/upload",
            files={"file": ("a.png", _png(), "image/png")},
        )
    assert resp.status_code == 503


def test_lock_is_released_even_on_exception():
    with pytest.raises(RuntimeError):
        with storage.maintenance():
            raise RuntimeError("boom")
    assert storage.is_locked() is False


def test_lock_is_thread_safe_for_reads():
    seen = []

    def worker():
        seen.append(storage.is_locked())

    with storage.maintenance():
        th = threading.Thread(target=worker)
        th.start()
        th.join()
    assert seen == [True]
