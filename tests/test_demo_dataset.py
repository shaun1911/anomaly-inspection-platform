"""Synthetic dataset generator: layout must match what anomalib's Folder loader expects."""

from __future__ import annotations

from pathlib import Path

from aip.demo import DEFECT_TYPES, make_demo_dataset


def _names(directory: Path) -> set[str]:
    return {p.name for p in directory.glob("*.png")}


def test_creates_expected_layout(tmp_path: Path) -> None:
    root = make_demo_dataset(tmp_path / "demo", train_good=4, test_good=3, per_defect=2, size=(120, 160))
    assert root.exists()

    assert len(_names(root / "train" / "good")) == 4
    assert len(_names(root / "test" / "good")) == 3

    for kind in DEFECT_TYPES:
        images = _names(root / "test" / kind)
        masks = _names(root / "ground_truth" / kind)
        assert len(images) == 2, kind
        # anomalib matches masks to anomalous images by file stem
        assert images == masks, kind


def test_generated_images_are_readable(tmp_path: Path) -> None:
    import cv2

    root = make_demo_dataset(tmp_path / "demo", train_good=1, test_good=1, per_defect=1, size=(96, 128))
    image = cv2.imread(str(next((root / "train" / "good").glob("*.png"))))
    assert image is not None
    assert image.shape[:2] == (96, 128)

    mask = cv2.imread(str(next((root / "ground_truth" / DEFECT_TYPES[0]).glob("*.png"))), cv2.IMREAD_GRAYSCALE)
    assert mask is not None
    assert mask.max() == 255  # defect pixels are white
