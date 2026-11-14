"""补两条带件号的判例（含一条同件冲突），演示按件聚合。"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import store  # noqa: E402

conn = store.connect(ROOT / "data" / "aip.db")
rows = conn.execute(
    "SELECT r.id, r.crop_path, j.part_no FROM inference_result r"
    " JOIN inference_job j ON j.id = r.job_id ORDER BY r.id"
).fetchall()
conn.close()

with httpx.Client(base_url="http://127.0.0.1:8100", timeout=15) as client:
    made = 0
    for r in rows:
        if not r["part_no"]:
            continue
        resp = client.post(
            "/api/cases",
            json={
                "code": "AB-1234-01",
                "crop_path": r["crop_path"],
                "verdict": "ok" if made % 2 == 0 else "ng",
                "adjudicator": "admin",
                "reason": "纹理正常" if made % 2 == 0 else "边部划痕",
                "source": "result",
                "result_id": r["id"],
                "part_no": r["part_no"],
            },
        )
        if resp.status_code == 201:
            made += 1
        if made >= 2:
            break
    cases = client.get("/api/cases").json()
    print("cases:", len(cases))
    for c in cases[:6]:
        print(" ", c["id"], c["code"], c.get("part_no"), c["verdict"], "conflict" if c["conflict"] else "")
