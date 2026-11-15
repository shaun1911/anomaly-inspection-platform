"""ONNX 推理后端验收（不依赖真实模型文件）。"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from aip.inference import onnx as onnx_mod
from aip.inference.service import FakePredictor


class _Meta:
    name = "images"
    shape = [1, 3, 32, 32]


class _Session:
    def __init__(self, output=None):
        self.last = None
        self._out = output if output is not None else np.array([[[2.5]]], dtype=np.float32)

    def get_inputs(self):
        return [_Meta()]

    def run(self, _outputs, feeds):
        self.last = feeds
        return [self._out]


def _png(tmp_path, size=(64, 48)):
    p = tmp_path / "a.png"
    rng = np.random.default_rng(1)
    arr = np.clip(np.full((size[1], size[0], 3), 120, dtype=np.int16) + rng.integers(-40, 40, (size[1], size[0], 3)), 0, 255).astype(np.uint8)
    Image.fromarray(arr, "RGB").save(p)
    return p


def test_prepare_input_nchw_pm1(tmp_path):
    tensor, w, h = onnx_mod.prepare_input(_png(tmp_path), [1, 3, 32, 40], "pm1")
    assert tensor.shape == (1, 3, 32, 40)
    assert w == 40 and h == 32
    assert tensor.dtype == np.float32
    assert tensor.min() >= -1.0 and tensor.max() <= 1.0


def test_prepare_input_nhwc_unit(tmp_path):
    tensor, w, h = onnx_mod.prepare_input(_png(tmp_path), [1, 24, 16, 3], "unit")
    assert tensor.shape == (1, 24, 16, 3)
    assert w == 16 and h == 24
    assert tensor.min() >= 0.0 and tensor.max() <= 1.0


def test_dynamic_dims_fall_back(tmp_path):
    tensor, w, h = onnx_mod.prepare_input(_png(tmp_path), ["batch", 3, "h", "w"], "pm1")
    assert tensor.shape == (1, 3, 256, 256)


def test_build_predictor_falls_back_to_fake():
    assert isinstance(onnx_mod.build_predictor(None), FakePredictor)


def test_onnx_predictor_aggregates_and_squashes(tmp_path):
    session = _Session()
    predictor = onnx_mod.OnnxPredictor(session, input_range="pm1", aggregate="max")
    pred = predictor.predict(_png(tmp_path))
    assert 0.0 <= pred.score <= 1.0
    assert pred.score == pytest.approx(2.5 / 3.5, rel=1e-6)
    assert session.last is not None


def test_onnx_predictor_mean_aggregate(tmp_path):
    session = _Session(np.array([[0.2, 0.8]], dtype=np.float32))
    pred = onnx_mod.OnnxPredictor(session, aggregate="mean").predict(_png(tmp_path))
    assert pred.score == pytest.approx(0.5, rel=1e-6)


def test_bad_aggregate_rejected():
    with pytest.raises(ValueError):
        onnx_mod.OnnxPredictor(_Session(), aggregate="p95")


def test_missing_runtime_gives_actionable_error(monkeypatch):
    def boom():
        raise onnx_mod.PredictorUnavailable("未安装 onnxruntime")

    monkeypatch.setattr(onnx_mod, "_import_ort", boom)
    with pytest.raises(onnx_mod.PredictorUnavailable) as exc:
        onnx_mod.load_session("x.onnx")
    assert "onnxruntime" in str(exc.value)
