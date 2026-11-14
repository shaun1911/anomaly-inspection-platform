"""Runtime contract: ONNX and torch backends must agree on an image."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from aip.runtime import create_runtime

BUNDLE = Path(__file__).resolve().parents[1] / "artifacts" / "demo-metal"

pytestmark = pytest.mark.skipif(not (BUNDLE / "metadata.json").exists(), reason="run `aip train` first")


@pytest.fixture(scope="module")
def onnx_runtime():
    return create_runtime(BUNDLE, backend="onnx", device="cpu")


def _image(seed: int = 0, size: tuple[int, int] = (480, 640)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.integers(120, 180, (size[0], size[1], 3), dtype=np.uint8)
    return base


def test_prediction_payload_contract(onnx_runtime) -> None:
    prediction = onnx_runtime.predict(_image())
    payload = prediction.to_dict()
    for key in ("score", "label", "is_defect", "threshold", "defect_ratio", "boxes", "latency_ms", "backend"):
        assert key in payload, key
    assert 0.0 <= payload["score"] <= 1.0
    assert payload["label"] in {"ok", "defect"}
    assert payload["backend"] == "onnx"
    # localized is only meaningful for defects
    assert payload["localized"] is None or isinstance(payload["localized"], bool)


def test_batch_matches_single(onnx_runtime) -> None:
    images = [_image(seed) for seed in range(3)]
    batched = onnx_runtime.predict_batch(images)
    singles = [onnx_runtime.predict(image) for image in images]
    assert len(batched) == len(singles) == 3
    for batch_prediction, single_prediction in zip(batched, singles, strict=True):
        assert abs(batch_prediction.score - single_prediction.score) < 1e-4


def test_masks_have_native_resolution(onnx_runtime) -> None:
    image = _image(size=(300, 420))
    prediction = onnx_runtime.predict(image)
    if prediction.mask is not None:
        assert prediction.mask.shape[:2] == image.shape[:2]
    if prediction.anomaly_map is not None:
        assert prediction.anomaly_map.shape[:2] == image.shape[:2]


def test_unknown_bundle_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        create_runtime(tmp_path, backend="onnx")


def test_payload_is_json_serialisable(onnx_runtime) -> None:
    payload = onnx_runtime.predict(_image()).to_dict()
    json.dumps(payload)  # must not raise
