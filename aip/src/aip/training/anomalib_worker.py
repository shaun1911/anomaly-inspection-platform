"""anomalib 训练 worker（独立进程）。

由服务端 `aip.training.runner` 启动，读取 config.json，训练 PatchCore，
导出 ONNX、在验证集上标定阈值，最后写 result.json。

只依赖 anomalib/torch/PIL/onnxruntime，不碰数据库。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "aip" / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "aip" / "src"))


def log(msg: str) -> None:
    print(f"[worker] {msg}", flush=True)


def materialize(run_dir: Path, items: list[dict]) -> dict:
    """把判例图转成 PNG 目录树；返回计数与首图尺寸。"""
    data = run_dir / "dataset"
    counts = {"train_ok": 0, "val_ok": 0, "val_ng": 0, "skipped_ng_train": 0}
    size = None
    for it in items:
        split = it["split"]
        verdict = it["verdict"]
        if verdict == "ng" and split != "frozen_val":
            counts["skipped_ng_train"] += 1
            continue
        kind = "ok" if verdict == "ok" else "ng"
        if split == "frozen_val":
            sub = data / "val" / kind
        else:
            if verdict != "ok":
                continue
            sub = data / "train" / "ok"
        sub.mkdir(parents=True, exist_ok=True)
        src = Path(it["path"])
        dst = sub / f"{it['case_id']}.png"
        with Image.open(src) as im:
            rgb = im.convert("RGB")
            if size is None:
                size = rgb.size
            rgb.save(dst)
        key = "train_ok" if split != "frozen_val" else f"val_{kind}"
        counts[key] += 1
    return {"counts": counts, "image_size": size}


def score_images(onnx_path: Path, paths: list[Path]) -> list[float]:
    from aip.inference.onnx import OnnxPredictor, load_session

    session = load_session(onnx_path, providers="cpu")
    predictor = OnnxPredictor(session, input_range="zero_one", aggregate="max")
    return [predictor.predict(p).score for p in paths]


def pick_thresholds(ok: list[float], ng: list[float], max_overkill: float = 0.05) -> dict:
    """在验证集上按"过杀不超预算、召回最大"选 th_hi；th_lo 取更保守的低分位。"""
    if not ok or not ng:
        raise ValueError("验证集必须同时包含 OK 与 NG")
    candidates = sorted({*ok, *ng})

    def stats(t: float) -> tuple[float, float]:
        recall = sum(1 for s in ng if s >= t) / len(ng)
        overkill = sum(1 for s in ok if s >= t) / len(ok)
        return recall, overkill

    best = None
    for t in candidates:
        recall, overkill = stats(t)
        if overkill <= max_overkill + 1e-9:
            key = (recall, -overkill, -t)
            if best is None or key > best[0]:
                best = (key, t, recall, overkill)
    rule = "max_recall_under_overkill"
    if best is None:
        rule = "best_f1_fallback"
        f1_best = None
        for t in candidates:
            recall, overkill = stats(t)
            precision = recall * len(ng) / max(1, (recall * len(ng) + overkill * len(ok)))
            f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
            if f1_best is None or f1 > f1_best[0]:
                f1_best = (f1, t, recall, overkill)
        assert f1_best is not None
        _, t, recall, overkill = f1_best
        best = ((0, 0, 0), t, recall, overkill)

    _, th_hi, recall, overkill = best

    # th_lo：过杀更低的阈值；找不到就取 th_hi 下方一点，形成灰区
    lo_best = None
    for t in candidates:
        if t >= th_hi:
            continue
        r, o = stats(t)
        if o <= 0.02 + 1e-9 and r >= recall - 0.05:
            if lo_best is None or r > lo_best[0]:
                lo_best = (r, t, o)
    th_lo = lo_best[1] if lo_best else max(0.0, th_hi - 0.05)
    if th_lo >= th_hi:
        th_lo = max(0.0, th_hi - 0.01)

    return {
        "th_lo": round(float(th_lo), 4),
        "th_hi": round(float(th_hi), 4),
        "recall": round(float(recall), 4),
        "overkill": round(float(overkill), 4),
        "rule": rule,
        "ok_scores": len(ok),
        "ng_scores": len(ng),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    run_dir = Path(cfg["run_dir"])
    result_path = Path(cfg["result_path"])
    result: dict = {"status": "failed"}

    try:
        started = time.time()
        log(f"materialize -> {run_dir / 'dataset'}")
        packed = materialize(run_dir, cfg["items"])
        counts = packed["counts"]
        log(f"counts: {counts}")
        if counts["train_ok"] < 2:
            raise RuntimeError("训练集 OK 样本不足（至少 2 张）")
        if counts["val_ok"] < 1:
            raise RuntimeError("验证集没有 OK 样本，无法标定过杀")
        if counts["val_ng"] < 1:
            raise RuntimeError("验证集没有 NG 样本，无法计算召回")

        import torch
        from anomalib.data import Folder
        from anomalib.deploy import ExportType
        from anomalib.engine import Engine
        from anomalib.models import Patchcore

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA 不可用，训练环境异常")

        dm = Folder(
            name=cfg.get("model_code", "model"),
            root=str(run_dir / "dataset"),
            normal_dir="train/ok",
            abnormal_dir="val/ng",
            normal_test_dir="val/ok",
            train_batch_size=int(cfg.get("batch_size", 16)),
            eval_batch_size=int(cfg.get("batch_size", 16)),
            num_workers=0,
            val_split_mode="same_as_test",
            test_split_mode="from_dir",
            seed=int(cfg.get("seed", 42)),
        )
        model = Patchcore(
            backbone=cfg.get("backbone", "wide_resnet50_2"),
            layers=("layer2", "layer3"),
            pre_trained=True,
            coreset_sampling_ratio=float(cfg.get("coreset_sampling_ratio", 0.1)),
        )
        engine = Engine(
            default_root_dir=str(run_dir / "anomalib"),
            max_epochs=1,
            accelerator="gpu",
            devices=1,
            logger=False,
            enable_progress_bar=False,
            enable_model_summary=False,
        )
        log("fit start")
        engine.fit(model=model, datamodule=dm)
        log("fit done")

        export_root = run_dir / "export"
        onnx_path = engine.export(
            model=model,
            export_type=ExportType.ONNX,
            export_root=str(export_root),
            input_size=(int(cfg.get("image_size", 256)), int(cfg.get("image_size", 256))),
            model_file_name=f"{cfg.get('model_code', 'model')}-v{cfg.get('version_no', 1)}",
        )
        if onnx_path is None:
            raise RuntimeError("ONNX 导出返回空路径")
        log(f"onnx: {onnx_path}")

        val_ok = sorted((run_dir / "dataset" / "val" / "ok").glob("*.png"))
        val_ng = sorted((run_dir / "dataset" / "val" / "ng").glob("*.png"))
        log("calibrate on onnx")
        ok_scores = score_images(Path(onnx_path), val_ok)
        ng_scores = score_images(Path(onnx_path), val_ng)
        picked = pick_thresholds(ok_scores, ng_scores)

        result = {
            "status": "ok",
            "onnx_path": str(onnx_path),
            "input_range": "zero_one",
            "aggregate": "max",
            "roi_rect": [0, 0, packed["image_size"][0], packed["image_size"][1]] if packed["image_size"] else None,
            "metrics": {
                **picked,
                "val_samples": len(ok_scores) + len(ng_scores),
                "train_samples": counts["train_ok"],
                "backbone": cfg.get("backbone", "wide_resnet50_2"),
                "image_size": int(cfg.get("image_size", 256)),
                "device": torch.cuda.get_device_name(0),
                "backend": "anomalib-patchcore",
                "duration_sec": round(time.time() - started, 1),
                "note": "real",
            },
        }
        log(f"done: {result['metrics']}")
        return 0
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-6000:],
        }
        log(f"FAILED: {result['error']}")
        return 1
    finally:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
