"""给同一个件号补几张，验证复核队列的按件聚合。"""

from __future__ import annotations

import io

import httpx
import numpy as np
from PIL import Image

BASE = "http://127.0.0.1:8100"


def png(seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    arr = np.clip(np.full((96, 96, 3), 120, dtype=np.int16) + rng.integers(-40, 40, (96, 96, 3)), 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


with httpx.Client(base_url=BASE, timeout=20) as client:
    for i in range(3):
        r = client.post(
            "/infer",
            data={"code": "AB-1234-01", "station": "S1", "part_no": "P-02"},
            files={"image": (f"p02-{i}.png", png(200 + i), "image/png")},
            headers={"Idempotency-Key": f"agg-{i}"},
        )
        print("submit", i, r.status_code)

    q = client.get("/review/queue", params={"group_by": "part"}).json()
    print("total", q["summary"]["total"], "groups", len(q["items"]))
    for it in q["items"]:
        print(" ", it["code"], it["part_no"], "x", it["count"])
