"""给 AB-1234-01 造 2 条 ok + 2 条 ng 判例（用真实裁片路径），用于演示参考样例。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import store  # noqa: E402

DB = ROOT / "data" / "aip.db"
conn = store.connect(DB)
rows = conn.execute(
    "SELECT r.id, r.crop_path, r.label FROM inference_result r"
    " JOIN inference_job j ON j.id = r.job_id"
    " WHERE j.code = 'AB-1234-01' ORDER BY r.id"
).fetchall()

ok_rows = [r for r in rows if r["label"] == "ok"][:2]
ng_rows = [r for r in rows if r["label"] in ("ng", "gray")][:2]
print("ok", len(ok_rows), "ng", len(ng_rows))

import httpx  # noqa: E402

with httpx.Client(base_url="http://127.0.0.1:8100", timeout=15) as client:
    for r in ok_rows:
        client.post(
            "/api/cases",
            json={
                "code": "AB-1234-01",
                "crop_path": r["crop_path"],
                "verdict": "ok",
                "adjudicator": "admin",
                "reason": "纹理正常",
            },
        )
    for r in ng_rows:
        client.post(
            "/api/cases",
            json={
                "code": "AB-1234-01",
                "crop_path": r["crop_path"],
                "verdict": "ng",
                "adjudicator": "admin",
                "reason": "边部划痕",
            },
        )
    cases = client.get("/api/cases").json()
    print("cases now:", len(cases))
conn.close()
