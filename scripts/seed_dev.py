"""生成本地演示数据（幂等）。

用法：``python scripts/seed_dev.py``
写入 ``data/aip.db``，不碰生产数据；重复执行会跳过已存在的编码/模型。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip import store  # noqa: E402
from aip.api.app import create_app  # noqa: E402

DB = ROOT / "data" / "aip.db"


def png(seed: int, size=(96, 96)) -> bytes:
    rng = np.random.default_rng(seed)
    base = np.full((size[1], size[0], 3), 128, dtype=np.uint8)
    noise = rng.integers(-40, 40, size=(size[1], size[0], 3))
    array = np.clip(base.astype(int) + noise, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(array, "RGB").save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = store.connect(DB)
    store.migrate(conn)
    conn.close()

    client = TestClient(create_app(DB))

    codes = [c["code"] for c in client.get("/api/codes").json()]
    if "AB-1234-01" not in codes:
        client.post("/api/codes", json={"code": "AB-1234-01", "family": "支架"})

    models = client.get("/api/codes").json()  # 仅用于沉默检查
    _ = models

    # 建模型（若已存在接口会 409，忽略）
    model = client.post("/api/models", json={"code": "M1", "name": "支架-全型"}).json()
    if "id" not in model:
        # 已存在时从绑定接口反查
        bindings = client.get("/api/bindings", params={"code": "AB-1234-01"}).json()
        model_id = bindings[0]["model_id"] if bindings else None
        if model_id is None:
            print("模型已存在但未绑定，请手动处理")
            return 1
    else:
        model_id = model["id"]
        version = client.post(
            f"/api/models/{model_id}/versions", json={"version_no": 1}
        ).json()
        client.put(
            f"/api/models/{model_id}/versions/1/status", json={"status": "assist"}
        )
        client.post("/api/bindings", json={"code": "AB-1234-01", "model_id": model_id})
        client.post(
            "/api/configs",
            json={"model_version_id": version["id"], "rev": 1, "roi_rect": [0, 0, 96, 96]},
        )
        client.post(
            "/api/thresholds",
            json={
                "model_version_id": version["id"],
                "roi_rev": 1,
                "rev": 1,
                "th_lo": 0.45,
                "th_hi": 0.6,
            },
        )

    for seed in range(1, 6):
        resp = client.post(
            "/infer",
            data={"code": "AB-1234-01", "station": "S1", "part_no": f"P-{seed:02d}"},
            files={"image": (f"crop{seed}.png", png(seed), "image/png")},
            headers={"Idempotency-Key": f"seed-{seed}"},
        )
        print("submit", seed, resp.status_code, resp.json())

    pending = client.get("/review/pending", params={"station": "S1"}).json()
    print("pending", pending["count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
