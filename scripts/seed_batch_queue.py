"""给队列补几条带批次的判定，演示分组视图。"""

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


with httpx.Client(base_url=BASE, timeout=20) as c:
    n = 0
    for batch in ("B-2026-11-01", "B-2026-11-02"):
        for i in range(3):
            r = c.post(
                "/infer",
                data={"code": "AB-1234-01", "station": "S1", "part_no": f"P-{batch[-2:]}-{i}",
                      "batch_no": batch},
                files={"image": (f"{batch}-{i}.png", png(hash((batch, i)) % 1000), "image/png")},
                headers={"Idempotency-Key": f"seed-{batch}-{i}"},
            )
            n += 1 if r.status_code == 202 else 0
    q = c.get("/review/queue", params={"group_by": "batch"}).json()
    print("submitted", n)
    for it in q["items"]:
        print(" ", it["key"], it["count"], "件", it["parts"])
