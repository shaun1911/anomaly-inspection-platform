"""审计归档验收。"""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from aip import store, whitelist
from aip.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIP_WHITELIST", str(tmp_path / "none.yaml"))
    whitelist.reset_cache()
    db = tmp_path / "data" / "aip.db"
    db.parent.mkdir()
    conn = store.connect(db)
    store.migrate(conn)
    for i, ts in enumerate(
        ["2020-01-01T00:00:00.000Z", "2020-06-01T00:00:00.000Z", "2026-11-15T09:00:00.000Z"]
    ):
        conn.execute(
            "INSERT INTO audit_log (actor, action, entity, entity_id, created_at)"
            " VALUES ('alice','setting.update','setting',?,?)",
            (str(i), ts),
        )
    conn.commit()
    conn.close()
    return TestClient(create_app(db))


def test_plan_counts_old_rows(client):
    plan = client.get("/api/maintenance/audit", params={"days": 180}).json()
    assert plan["count"] == 2
    assert plan["oldest"].startswith("2020-01-01")


def test_archive_exports_and_deletes_old(client):
    out = client.post(
        "/api/maintenance/audit/archive", json={"days": 180, "apply": True, "actor": "admin"}
    ).json()
    assert out["archived"] == 2
    assert out["path"].endswith(".csv")

    rows = client.get("/api/audit").json()
    assert rows["total"] == 2  # 1 条新记录 + 1 条归档动作审计

    # CSV 内容
    path = out["path"]
    with open(path, encoding="utf-8-sig", newline="") as fh:
        data = list(csv.DictReader(fh))
    assert {r["entity_id"] for r in data} == {"0", "1"}


def test_recent_rows_are_kept(client):
    out = client.post(
        "/api/maintenance/audit/archive", json={"days": 30, "apply": True}
    ).json()
    assert out["archived"] == 2
    remaining = client.get("/api/audit").json()["items"]
    assert any(i["created_at"].startswith("2026-11-15") for i in remaining)


def test_too_small_retention_rejected(client):
    resp = client.get("/api/maintenance/audit", params={"days": 1})
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "archive_invalid"
