"""离线评测：用生产同款 ONNX 预测器跑 OK/NG 目录。

示例：
    .venv\\Scripts\\python.exe scripts\\eval_onnx.py ^
      --onnx data\\models\\S1-v4.onnx --ok "sample\\Sample2\\Validation Data\\OK" ^
      --ng "sample\\Sample2\\Validation Data\\NG" --input-range zero_one ^
      --th-lo 0.4358 --th-hi 0.4858 --csv data\\runs\\eval-sample2.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip.inference.onnx import OnnxPredictor, load_session  # noqa: E402

EXTS = {".bmp", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS)


def auc(ok: list[float], ng: list[float]) -> float:
    if not ok or not ng:
        return float("nan")
    labels = np.array([0] * len(ok) + [1] * len(ng))
    scores = np.array(ok + ng)
    order = np.argsort(scores)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    # 处理并列分数
    _, inv, counts = np.unique(scores, return_inverse=True, return_counts=True)
    for i, c in enumerate(counts):
        if c > 1:
            ranks[inv == i] = ranks[inv == i].mean()
    pos = labels == 1
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--ok", required=True)
    ap.add_argument("--ng", required=True)
    ap.add_argument("--input-range", default="zero_one", choices=["pm1", "zero_one", "unit", "imagenet"])
    ap.add_argument("--aggregate", default="max", choices=["max", "mean"])
    ap.add_argument("--th-lo", type=float, default=None)
    ap.add_argument("--th-hi", type=float, default=None)
    ap.add_argument("--csv", default="")
    args = ap.parse_args()

    session = load_session(args.onnx, providers="cpu")
    predictor = OnnxPredictor(session, input_range=args.input_range, aggregate=args.aggregate)

    rows = []
    ok_scores, ng_scores = [], []
    for label, folder in (("ok", Path(args.ok)), ("ng", Path(args.ng))):
        for path in images(folder):
            score = predictor.predict(path).score
            rows.append((path.name, label, score))
            (ok_scores if label == "ok" else ng_scores).append(score)

    th_lo = args.th_lo if args.th_lo is not None else 0.0
    th_hi = args.th_hi if args.th_hi is not None else 1.0
    tp = sum(1 for s in ng_scores if s >= th_hi)
    fn = len(ng_scores) - tp
    fp = sum(1 for s in ok_scores if s >= th_hi)
    recall = tp / len(ng_scores) if ng_scores else float("nan")
    overkill = fp / len(ok_scores) if ok_scores else float("nan")
    gray_ok = sum(1 for s in ok_scores if th_lo <= s < th_hi)
    gray_ng = sum(1 for s in ng_scores if th_lo <= s < th_hi)

    print(f"OK={len(ok_scores)} NG={len(ng_scores)}  AUC={auc(ok_scores, ng_scores):.4f}")
    print(f"阈值 th_lo={th_lo:.4f} th_hi={th_hi:.4f}")
    print(f"召回={recall*100:.1f}%  过杀={overkill*100:.1f}%  灰区 OK={gray_ok} NG={gray_ng}")
    print(f"OK 分数: min={min(ok_scores):.3f} p50={np.median(ok_scores):.3f} max={max(ok_scores):.3f}")
    print(f"NG 分数: min={min(ng_scores):.3f} p50={np.median(ng_scores):.3f} max={max(ng_scores):.3f}")

    # 在该数据集上按过杀 5% 找参考阈值
    ref = None
    for t in sorted({*ok_scores, *ng_scores}):
        r = sum(1 for s in ng_scores if s >= t) / len(ng_scores)
        o = sum(1 for s in ok_scores if s >= t) / len(ok_scores)
        if o <= 0.05 + 1e-9 and (ref is None or r > ref[0]):
            ref = (r, o, t)
    if ref:
        print(f"参考阈值（本集过杀≤5%）: th={ref[2]:.4f} 召回={ref[0]*100:.1f}% 过杀={ref[1]*100:.1f}%")

    if args.csv:
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["file", "label", "score", "result"])
            for name, label, score in rows:
                result = "ng" if score >= th_hi else ("gray" if score >= th_lo else "ok")
                w.writerow([name, label, f"{score:.6f}", result])
        print("CSV:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
