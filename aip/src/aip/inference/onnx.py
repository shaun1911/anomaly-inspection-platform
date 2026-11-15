"""ONNX 推理后端（可选）。

有 `onnx_path` 的版本走 ONNX Runtime；没有就退回 FakePredictor。
CPU 版 onnxruntime 随服务端安装；GPU 版与 CUDA/cuDNN 由用户自行安装。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

from .service import Prediction


class PredictorUnavailable(RuntimeError):
    pass


def _import_ort():
    try:
        import onnxruntime as ort  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 环境相关
        raise PredictorUnavailable(
            "未安装 onnxruntime；CPU: pip install onnxruntime；"
            "GPU: pip install onnxruntime-gpu（CUDA/cuDNN 需自行安装）"
        ) from exc
    return ort


def load_session(path: str | Path, providers: str = "auto"):
    ort = _import_ort()
    available = ort.get_available_providers()
    if providers == "cpu":
        chosen = ["CPUExecutionProvider"]
    else:
        chosen = ["CUDAExecutionProvider"] if "CUDAExecutionProvider" in available else ["CPUExecutionProvider"]
    return ort.InferenceSession(str(path), providers=chosen)


def prepare_input(
    image_path: Path, shape: list, input_range: str = "pm1"
) -> tuple[np.ndarray, int, int]:
    """按模型输入形状准备张量；返回 (tensor, W, H)。"""
    if len(shape) != 4:
        raise ValueError(f"只支持 4 维输入（N,C,H,W 或 N,H,W,C），实际 {shape}")

    def _dim(value, fallback: int) -> int:
        return int(value) if isinstance(value, int) or str(value).isdigit() else fallback

    channels_first = _dim(shape[1], 3) == 3
    h = _dim(shape[2] if channels_first else shape[1], 256)
    w = _dim(shape[3] if channels_first else shape[2], 256)

    with Image.open(image_path) as image:
        rgb = image.convert("RGB").resize((w, h))
    arr = np.asarray(rgb, dtype=np.float32) / 255.0
    if input_range == "pm1":
        arr = arr * 2.0 - 1.0
    if channels_first:
        arr = np.transpose(arr, (2, 0, 1))
    return arr[None, ...], w, h


class OnnxPredictor:
    def __init__(self, session, input_range: str = "pm1", aggregate: str = "max",
                 fallback_size: int = 256) -> None:
        if aggregate not in ("max", "mean"):
            raise ValueError("onnx_aggregate 只能是 max 或 mean")
        self.session = session
        self.input_range = input_range
        self.aggregate = aggregate
        self.fallback_size = fallback_size

    def predict(self, image_path: Path) -> Prediction:
        input_meta = self.session.get_inputs()[0]
        tensor, w, h = prepare_input(image_path, list(input_meta.shape), self.input_range)
        outputs = self.session.run(None, {input_meta.name: tensor})
        arrays = [o for o in outputs if isinstance(o, np.ndarray) and o.dtype.kind == "f"]
        if not arrays:
            raise PredictorUnavailable("模型没有浮点输出")
        arr = max(arrays, key=lambda a: a.size)
        if self.aggregate == "mean":
            score = float(np.mean(arr))
        else:
            score = float(np.max(arr)) if arr.ndim >= 2 else float(np.mean(arr))

        # 不同导出的分数尺度不同：>1 时做单调压缩，<0 归零，保证落在 [0,1]
        if score > 1.0:
            score = score / (1.0 + score)
        score = max(0.0, min(1.0, score))
        return Prediction(score=score, label="ok", boxes=[], width=w, height=h)


def build_predictor(session, *, input_range: str = "pm1", aggregate: str = "max"):
    """有 session 用 ONNX，没有就用假预测器。"""
    if session is None:
        from .service import FakePredictor  # noqa: PLC0415

        return FakePredictor()
    return OnnxPredictor(session, input_range=input_range, aggregate=aggregate)


def fingerprint(path: str | Path | None) -> str | None:
    if not path or not Path(path).is_file():
        return None
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
