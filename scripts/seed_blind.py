"""建一个盲判批次并判几件，用于界面演示。"""

from __future__ import annotations

import httpx

with httpx.Client(base_url="http://127.0.0.1:8100", timeout=15) as c:
    existing = c.get("/api/blind/batches").json()
    if existing:
        print("batches:", [(b["week"], b["judged"], b["total"], b["status"]) for b in existing])
        bid = existing[0]["id"]
    else:
        created = c.post("/api/blind/batches", json={"week": "2026-W46", "sample_size": 6, "sampled_by": "admin"})
        print("created", created.status_code, created.text[:120])
        bid = created.json()["id"]

    detail = c.get(f"/api/blind/batches/{bid}").json()
    pending = [i for i in detail["items"] if not i["human_label"]]
    for it in pending[:2]:
        r = c.post(f"/api/blind/items/{it['id']}/judge", json={"human_label": "ng", "judge": "admin"})
        print("judge", it["id"], r.status_code)
    final = c.get(f"/api/blind/batches/{bid}").json()
    print("progress", final["judged"], "/", final["total"], final["status"])
