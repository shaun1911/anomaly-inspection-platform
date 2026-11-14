"""T2-1 验收：工位面板可访问，且包含关键操作元素。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from aip import store
from aip.api.app import create_app


def test_panel_is_served(tmp_path):
    db = tmp_path / "api.db"
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()

    client = TestClient(create_app(db))
    resp = client.get("/panel")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "工位面板" in body
    assert "换型" in body
    assert "待复核" in body
    assert "/review/pending" in body


def test_admin_is_served(tmp_path):
    db = tmp_path / "api.db"
    conn = store.connect(db)
    store.migrate(conn)
    conn.close()

    client = TestClient(create_app(db))
    resp = client.get("/admin")
    assert resp.status_code == 200
    body = resp.text
    assert "服务端" in body
    assert 'aria-label="主导航"' in body
    assert "/api/stats/today" in body
