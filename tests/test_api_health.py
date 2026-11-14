"""T1-1 验收：应用可装配、健康检查可观测、错误体统一。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aip import store
from aip.api.app import create_app
from aip.api.errors import ApiError


@pytest.fixture()
def client(tmp_path):
    db = tmp_path / "api.db"
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()
    return TestClient(create_app(db))


def test_health_reports_db_and_queue(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["queue_depth"] == 0


def test_health_degrades_when_db_missing(tmp_path):
    client = TestClient(create_app(tmp_path / "no-such-dir" / "x.db"))
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"


def test_api_error_envelope(client):
    app = client.app

    @app.get("/boom")
    def boom():
        raise ApiError(
            code="not_in_shift",
            message="本编码不在本班范围",
            action="联系技师或换件",
            status=403,
        )

    resp = client.get("/boom")
    assert resp.status_code == 403
    assert resp.json() == {
        "error_code": "not_in_shift",
        "message": "本编码不在本班范围",
        "action": "联系技师或换件",
    }


def test_lookup_error_maps_to_404(client):
    app = client.app

    @app.get("/missing")
    def missing():
        raise LookupError("未知产品编码")

    resp = client.get("/missing")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "not_found"
