"""造一个已冻结的数据集，供界面演示。"""

from __future__ import annotations

import httpx

BASE = "http://127.0.0.1:8100"

with httpx.Client(base_url=BASE, timeout=15) as c:
    models = c.get("/api/models").json()
    model = models[0]
    ds = c.post("/api/datasets", json={"model_id": model["id"], "name": "M1-2026-W46"}).json()
    print("dataset", ds)
    cases = c.get("/api/cases?limit=50").json()
    ids = [x["id"] for x in cases if not x.get("archived_at")]
    r = c.post(f"/api/datasets/{ds['id']}/items", json={"case_ids": ids}).json()
    print("added", len(r["added"]), "skipped", len(r["skipped"]))
    f = c.post(f"/api/datasets/{ds['id']}/freeze").json()
    print("frozen", f["checksum"][:16])
