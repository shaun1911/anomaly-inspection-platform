"""编码服务端分页。"""

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
    conn.execute("INSERT INTO family (name) VALUES (?)", ("支架类",))
    for i in range(25):
        conn.execute(
            "INSERT INTO product_code (code, family_id) VALUES (?, 1)",
            (f"AB-{i:04d}",),
        )
    conn.commit()
    conn.close()
    return TestClient(create_app(db))


def test_page_and_total(client):
    first = client.get("/api/codes/page", params={"limit": 10, "offset": 0}).json()
    assert first["total"] == 25
    assert len(first["items"]) == 10
    second = client.get("/api/codes/page", params={"limit": 10, "offset": 10}).json()
    assert len(second["items"]) == 10
    assert {x["code"] for x in first["items"]} & {x["code"] for x in second["items"]} == set()


def test_search_filters_total(client):
    out = client.get("/api/codes/page", params={"q": "AB-001"}).json()
    assert out["total"] == 10  # AB-0010 ~ AB-0019
    assert all("AB-001" in x["code"] for x in out["items"])
