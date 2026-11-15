"""离线 API 文档验收。"""

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


def test_docs_uses_local_assets(client):
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "/swagger/swagger-ui-bundle.js" in resp.text
    assert "cdn.jsdelivr" not in resp.text


def test_swagger_assets_served(client):
    css = client.get("/swagger/swagger-ui.css")
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    js = client.get("/swagger/swagger-ui-bundle.js")
    assert js.status_code == 200
    assert len(js.content) > 100_000


def test_swagger_asset_traversal_blocked(client):
    assert client.get("/swagger/nope.js").status_code == 404
    assert client.get("/swagger/..%2Fapp.py").status_code == 404


def test_openapi_contains_request_examples(client):
    spec = client.get("/openapi.json").json()
    code_example = spec["components"]["schemas"]["CodeIn"]["examples"][0]
    assert code_example["code"] == "AB-1234-01"
    move_example = spec["components"]["schemas"]["MoveIn"]["examples"][0]
    assert move_example["dry_run"] is True
