"""审计日志时间范围筛选验收。"""

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
    for i, ts in enumerate(
        [
            "2026-11-14T08:00:00.000Z",
            "2026-11-14T20:00:00.000Z",
            "2026-11-15T09:30:00.000Z",
            "2026-11-15T18:00:00.000Z",
        ]
    ):
        conn.execute(
            "INSERT INTO audit_log (actor, action, entity, entity_id, created_at)"
            " VALUES ('alice', 'setting.update', 'setting', ?, ?)",
            (str(i), ts),
        )
    conn.commit()
    conn.close()
    return TestClient(create_app(db))


def test_since_and_until_filter(client):
    since = client.get("/api/audit", params={"since": "2026-11-15"}).json()
    assert since["total"] == 2

    until = client.get("/api/audit", params={"until": "2026-11-14"}).json()
    assert until["total"] == 2

    window = client.get(
        "/api/audit", params={"since": "2026-11-15T09:00", "until": "2026-11-15T12:00"}
    ).json()
    assert window["total"] == 1
    assert window["items"][0]["entity_id"] == "2"


def test_time_range_combines_with_action_and_paging(client):
    out = client.get(
        "/api/audit",
        params={"action": "setting.update", "since": "2026-11-14", "limit": 2, "offset": 0},
    ).json()
    assert out["total"] == 4
    assert len(out["items"]) == 2
    assert out["items"][0]["created_at"].startswith("2026-11-15T18")
