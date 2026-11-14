"""Bundle contract: what the runtime is allowed to rely on."""

from __future__ import annotations

from pathlib import Path

import pytest

from aip.bundle import read_metadata

BUNDLE = Path(__file__).resolve().parents[1] / "artifacts" / "demo-metal"

pytestmark = pytest.mark.skipif(not (BUNDLE / "metadata.json").exists(), reason="run `aip train` first")


def test_metadata_contract() -> None:
    meta = read_metadata(BUNDLE)
    assert meta["bundle_format"] == 1
    assert meta["model"]["name"]
    assert meta["input"]["layout"] == "NCHW"
    assert len(meta["input"]["size"]) == 2
    assert "image_threshold" in meta["postprocess"]
    assert meta["artifacts"]["onnx"] == "model.onnx"


def test_bundle_is_self_contained() -> None:
    """Every artifact referenced by metadata must exist next to it."""
    meta = read_metadata(BUNDLE)
    for key, filename in meta["artifacts"].items():
        if key == "onnx_external_data":
            for extra in filename:
                assert (BUNDLE / extra).exists()
            continue
        assert (BUNDLE / filename).exists(), filename


def test_no_absolute_paths_in_artifacts() -> None:
    """The dataset path may be recorded for audit, but artifacts must be relative."""
    meta = read_metadata(BUNDLE)
    for filename in meta["artifacts"].values():
        values = filename if isinstance(filename, list) else [filename]
        for value in values:
            assert not Path(value).is_absolute(), value


def test_single_file_onnx() -> None:
    """We export with external_data=False so copying the bundle cannot lose weights."""
    meta = read_metadata(BUNDLE)
    assert "onnx_external_data" not in meta["artifacts"]
    assert (BUNDLE / "model.onnx").stat().st_size > 1_000_000
