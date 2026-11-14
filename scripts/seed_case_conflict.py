"""造一条判例 + 一条同图不同结论的冲突，用于演示判例库。"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import store  # noqa: E402

conn = store.connect(ROOT / "data" / "aip.db")
row = conn.execute(
    "SELECT r.id, r.crop_path, r.model_version_id FROM inference_result r ORDER BY r.id LIMIT 1"
).fetchone()
conn.close()
print("using crop", row["crop_path"])

with httpx.Client(base_url="http://127.0.0.1:8100", timeout=15) as client:
    ok = client.post(
        "/api/cases",
        json={
            "code": "AB-1234-01",
            "crop_path": row["crop_path"],
            "verdict": "ok",
            "adjudicator": "zhoubin",
            "reason": "纹理正常",
            "source": "result",
            "result_id": row["id"],
            "model_version_id": row["model_version_id"],
        },
    )
    print("create", ok.status_code, ok.text[:120])

    dup = client.post(
        "/api/cases",
        json={
            "code": "AB-1234-01",
            "crop_path": row["crop_path"],
            "verdict": "ng",
            "adjudicator": "li",
            "reason": "边部划痕",
        },
    )
    print("duplicate", dup.status_code, dup.text[:160])
    conflicts = client.get("/api/cases/conflicts").json()
    print("conflicts", len(conflicts))
