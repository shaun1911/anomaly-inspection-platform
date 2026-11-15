"""推一张图触发按需加载，便于工作台展示常驻模型。"""

from __future__ import annotations

import io

import httpx
import numpy as np
from PIL import Image

rng = np.random.default_rng(99)
arr = np.clip(np.full((96, 96, 3), 120, dtype=np.int16) + rng.integers(-40, 40, (96, 96, 3)), 0, 255).astype("uint8")
buf = io.BytesIO()
Image.fromarray(arr, "RGB").save(buf, format="PNG")

with httpx.Client(base_url="http://127.0.0.1:8100", timeout=20) as c:
    r = c.post(
        "/infer",
        data={"code": "AB-1234-01", "station": "S1", "part_no": "P-CACHE-1", "batch_no": "B-2026-11-03"},
        files={"image": ("cache.png", buf.getvalue(), "image/png")},
        headers={"Idempotency-Key": "cache-demo-1"},
    )
    print("infer", r.status_code, r.text[:120])
    cache = c.get("/api/model-cache").json()
    print("cache", cache)
