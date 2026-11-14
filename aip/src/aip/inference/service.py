"""推理服务内核（T1-3）。

真实预测器由 anomalib 提供；这里先放一个确定性假预测器，把链路跑通。
接口契约保持不变：``predict(image_path) -> Prediction``。
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from ..store import tx

# 入口守门默认阈值（Q5 会用真实裁片统计后覆盖）
GATE = {
    "min_side": 32,
    "min_brightness": 10.0,
    "max_brightness": 245.0,
    "min_contrast": 5.0,
}


@dataclass(frozen=True)
class Prediction:
    score: float
    label: str
    boxes: list[list[int]]
    width: int
    height: int


class FakePredictor:
    """以图片字节的 sha256 生成稳定分数，便于测试与演示。"""

    def predict(self, image_path: Path) -> Prediction:
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        score = (int(digest[:8], 16) % 1000) / 1000.0
        with Image.open(image_path) as image:
            width, height = image.size
        return Prediction(score=score, label="ok", boxes=[], width=width, height=height)


def label_for(score: float, th_lo: float, th_hi: float) -> str:
    if score < th_lo:
        return "ok"
    if score < th_hi:
        return "gray"
    return "ng"


def check_gate(image_path: Path, gate: dict | None = None) -> str | None:
    """返回错误码；None 表示通过。"""
    cfg = {**GATE, **(gate or {})}
    try:
        with Image.open(image_path) as image:
            gray = image.convert("L")
            width, height = gray.size
            if min(width, height) < cfg["min_side"]:
                return "crop_too_small"
            array = np.asarray(gray, dtype=np.float32)
    except Exception:  # noqa: BLE001
        return "crop_unreadable"

    mean = float(array.mean())
    if mean < cfg["min_brightness"]:
        return "crop_too_dark"
    if mean > cfg["max_brightness"]:
        return "crop_too_bright"
    if float(array.std()) < cfg["min_contrast"]:
        return "crop_low_contrast"
    return None


GATE_MESSAGES = {
    "crop_too_small": ("裁片过小", "检查镜头倍率或 ROI 设置"),
    "crop_unreadable": ("裁片无法解码", "重新拍照或检查传输"),
    "crop_too_dark": ("裁片过暗", "检查光源亮度"),
    "crop_too_bright": ("裁片过曝", "检查光源或曝光时间"),
    "crop_low_contrast": ("裁片对比度过低", "检查对焦与光源角度"),
}


def process_job(
    conn: sqlite3.Connection,
    *,
    job_id: int,
    model_version_id: int,
    crop_path: Path,
    predictor,
    th_lo: float,
    th_hi: float,
) -> None:
    """一次判定：预测 → 落 result → 更新 job。失败也落 failed。"""
    try:
        prediction = predictor.predict(crop_path)
        label = label_for(prediction.score, th_lo, th_hi)
        with tx(conn):
            conn.execute(
                "INSERT INTO inference_result"
                " (job_id, model_version_id, score, label, boxes_json, crop_path,"
                "  original_w, original_h)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    model_version_id,
                    prediction.score,
                    label,
                    "[]",
                    str(crop_path),
                    prediction.width,
                    prediction.height,
                ),
            )
            conn.execute(
                "UPDATE inference_job SET status = 'done', done_at ="
                " strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ?",
                (job_id,),
            )
    except Exception:  # noqa: BLE001 - 失败必须落状态，不能吞
        with tx(conn):
            conn.execute(
                "UPDATE inference_job SET status = 'failed', error_code = 'inference_failed'"
                " WHERE id = ?",
                (job_id,),
            )
        raise
