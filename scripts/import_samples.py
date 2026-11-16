"""批量导入本地样本为判例（按 OK/NG 子目录）。

示例（Sample1）：
    .venv\\Scripts\\python.exe scripts\\import_samples.py ^
        --dir sample\\Sample1 --code VPTXDF-18B955-CP --family 排线口B ^
        --model S1 --model-name "Sample1 排线口B" ^
        --dataset Sample1-v1 --freeze

    --limit 20   只导前 20 张（试跑）
    --dry-run    只统计，不写库

幂等：同一张图 + 同一件号重复导入会被服务端判重并跳过。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
EXTS = {".bmp", ".png", ".jpg", ".jpeg", ".webp"}


def api(base: str) -> httpx.Client:
    client = httpx.Client(base_url=base, timeout=120)
    return client


def ensure_code(c: httpx.Client, code: str, family: str) -> None:
    codes = c.get("/api/codes", params={"include_archived": "true"}).json()
    if not any(x["code"] == code for x in codes):
        r = c.post("/api/codes", json={"code": code, "family": family})
        r.raise_for_status()
        print(f"  新建编码 {code}（族 {family}）")
    else:
        print(f"  编码 {code} 已存在")


def ensure_model(c: httpx.Client, model: str, name: str) -> int:
    models = c.get("/api/models").json()
    for m in models:
        if m["code"] == model:
            print(f"  模型 {model} 已存在（id {m['id']}）")
            return int(m["id"])
    r = c.post("/api/models", json={"code": model, "name": name})
    r.raise_for_status()
    mid = int(r.json()["id"])
    print(f"  新建模型 {model}（id {mid}）")
    return mid


def ensure_binding(c: httpx.Client, code: str, model_id: int) -> None:
    rows = c.get("/api/bindings").json()
    if any(b["code"] == code and b.get("model_id") == model_id for b in rows):
        print("  绑定已存在")
        return
    r = c.post("/api/bindings", json={"code": code, "model_id": model_id})
    r.raise_for_status()
    print("  已绑定编码 → 模型")


def ensure_dataset(c: httpx.Client, model_id: int, name: str) -> int:
    for d in c.get("/api/datasets").json():
        if d["name"] == name and d.get("model_id") == model_id:
            print(f"  数据集 {name} 已存在（id {d['id']}，{d['status']}）")
            return int(d["id"])
    r = c.post("/api/datasets", json={"model_id": model_id, "name": name, "note": "Sample1 导入"})
    r.raise_for_status()
    did = int(r.json()["id"])
    print(f"  新建数据集 {name}（id {did}）")
    return did


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=str(ROOT / "sample" / "Sample1"))
    parser.add_argument("--code", required=True)
    parser.add_argument("--family", default="排线口B")
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-name", default="")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--base", default="http://127.0.0.1:8100")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.is_absolute():
        root = ROOT / root
    files: list[tuple[Path, str]] = []
    for verdict, folder in (("ok", "OK"), ("ng", "NG")):
        d = root / folder
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in EXTS:
                files.append((f, verdict))
    print(f"发现 {len(files)} 张图片（ok {sum(1 for _, v in files if v == 'ok')} / ng {sum(1 for _, v in files if v == 'ng')}）")
    if args.limit:
        ok = [x for x in files if x[1] == "ok"][: args.limit]
        ng = [x for x in files if x[1] == "ng"][: args.limit]
        files = ok + ng
        print(f"限制为 {len(files)} 张（每种各 {args.limit}）")
    if args.dry_run:
        return 0

    with api(args.base) as c:
        print("[1/3] 编码与模型")
        ensure_code(c, args.code, args.family)
        mid = ensure_model(c, args.model, args.model_name or args.model)
        ensure_binding(c, args.code, mid)

        print("[2/3] 导入判例")
        imported = skipped = failed = 0
        case_ids: list[int] = []
        for i, (path, verdict) in enumerate(files, 1):
            try:
                up = c.post(
                    "/api/cases/upload",
                    files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
                )
                up.raise_for_status()
                crop = up.json()["crop_path"]
                r = c.post(
                    "/api/cases",
                    json={
                        "code": args.code,
                        "crop_path": crop,
                        "verdict": verdict,
                        "adjudicator": "sample-import",
                        "part_no": path.stem[:60],
                        "reason": "Sample1 导入",
                        "source": "import",
                    },
                )
                if r.status_code == 409:
                    skipped += 1
                    continue
                r.raise_for_status()
                case_ids.append(int(r.json()["id"]))
                imported += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  ! {path.name}: {exc}")
            if i % 50 == 0:
                print(f"  ... {i}/{len(files)}（新增 {imported}，重复 {skipped}，失败 {failed}）")

        print(f"  新增 {imported}，重复 {skipped}，失败 {failed}")

        if args.dataset:
            print(f"[3/3] 数据集 {args.dataset}")
            did = ensure_dataset(c, mid, args.dataset)
            ds = c.get(f"/api/datasets/{did}").json()
            if ds["status"] == "frozen":
                print("  数据集已冻结，跳过加入")
            else:
                if case_ids:
                    for j in range(0, len(case_ids), 200):
                        r = c.post(f"/api/datasets/{did}/items", json={"case_ids": case_ids[j : j + 200]})
                        r.raise_for_status()
                    print(f"  已加入 {len(case_ids)} 条判例")
                if args.freeze:
                    r = c.post(f"/api/datasets/{did}/freeze")
                    r.raise_for_status()
                    print("  已冻结，校验和：" + str(r.json().get("checksum", ""))[:16] + "…")
                else:
                    print("  未冻结（加 --freeze 冻结）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
