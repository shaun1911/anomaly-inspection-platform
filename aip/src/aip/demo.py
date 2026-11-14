"""Synthetic industrial-surface dataset generator.

Why synthetic: MVTec AD downloads are currently disabled upstream, and a
platform must be smoke-testable on any machine in under a minute. The generated
images mimic a brushed-metal part with three defect families, so a
feature-matching model (PatchCore/PaDiM) learns something meaningful and the
pixel-level metrics are above chance.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

DEFECT_TYPES = ("scratch", "stain", "dent")


def _texture(rng: np.random.Generator, height: int, width: int) -> np.ndarray:
    """Brushed-metal-ish background: fine noise + directional streaks + vignette."""
    import cv2

    base = rng.normal(150, 6, (height, width)).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), 1.2)
    streaks = rng.normal(0, 4, (height, 1)).astype(np.float32)
    streaks = cv2.resize(streaks, (width, height), interpolation=cv2.INTER_LINEAR)
    fine = rng.normal(0, 3.0, (height, width)).astype(np.float32)
    canvas = base + streaks * 0.6 + fine

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = width / 2, height / 2
    radius = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max(cx, cy)
    canvas *= 1.0 - 0.18 * radius**2
    canvas = np.clip(canvas, 0, 255)

    tint = np.array([1.0, 0.985, 0.95], dtype=np.float32)  # slight warm metal tint
    image = np.stack([canvas * t for t in tint], axis=-1)
    return np.clip(image, 0, 255).astype(np.uint8)


def _add_defect(image: np.ndarray, rng: np.random.Generator, kind: str) -> tuple[np.ndarray, np.ndarray]:
    """Draw a defect and return (image, binary mask).

    All geometry scales with the short side so the generator works for any
    image size (tests use tiny frames, production uses 4K).
    """
    import cv2

    out = image.copy()
    height, width = image.shape[:2]
    short = min(height, width)
    margin = max(6, int(short * 0.14))
    mask = np.zeros((height, width), dtype=np.uint8)

    if kind == "scratch":
        x0 = int(rng.integers(margin, max(margin + 1, width - margin)))
        y0 = int(rng.integers(margin, max(margin + 1, height - margin)))
        angle = rng.uniform(0, np.pi)
        length = int(rng.integers(max(12, int(short * 0.25)), max(13, int(short * 0.6))))
        x1 = int(np.clip(x0 + length * np.cos(angle), 0, width - 1))
        y1 = int(np.clip(y0 + length * np.sin(angle), 0, height - 1))
        thickness = max(1, int(rng.integers(2, 5)))
        cv2.line(mask, (x0, y0), (x1, y1), 255, thickness)
        value = int(rng.integers(40, 90))  # dark scratch
        cv2.line(out, (x0, y0), (x1, y1), (value, value, value), thickness)

    elif kind == "stain":
        cx = int(rng.integers(margin, max(margin + 1, width - margin)))
        cy = int(rng.integers(margin, max(margin + 1, height - margin)))
        axes = (
            max(3, int(rng.integers(int(short * 0.05), max(int(short * 0.05) + 1, int(short * 0.13))))),
            max(3, int(rng.integers(int(short * 0.04), max(int(short * 0.04) + 1, int(short * 0.10))))),
        )
        angle = rng.uniform(0, 180)
        cv2.ellipse(mask, (cx, cy), axes, angle, 0, 360, 255, -1)
        mask = cv2.GaussianBlur(mask, (9, 9), 0)
        mask = (mask > 60).astype(np.uint8) * 255
        overlay = out.copy()
        cv2.ellipse(overlay, (cx, cy), axes, angle, 0, 360, (70, 65, 60), -1)
        alpha = (mask.astype(np.float32) / 255)[..., None] * 0.75
        out = (out * (1 - alpha) + overlay * alpha).astype(np.uint8)

    else:  # dent
        cx = int(rng.integers(margin, max(margin + 1, width - margin)))
        cy = int(rng.integers(margin, max(margin + 1, height - margin)))
        radius = max(5, int(rng.integers(int(short * 0.05), max(int(short * 0.05) + 1, int(short * 0.13)))))
        cv2.circle(mask, (cx, cy), radius, 255, -1)
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / radius
        shading = np.clip(1.0 - 0.30 * np.exp(-((dist - 0.55) ** 2) / 0.06), 0.6, 1.25)
        shaded = np.clip(out.astype(np.float32) * shading[..., None], 0, 255)
        ring = (np.abs(dist - 0.95) < 0.08) & (mask > 0)
        shaded[ring] *= 0.75
        out = np.where((mask > 0)[..., None], shaded, out.astype(np.float32)).astype(np.uint8)

    return out, mask


def make_demo_dataset(
    root: str | Path,
    *,
    train_good: int = 40,
    test_good: int = 20,
    per_defect: int = 15,
    size: tuple[int, int] = (480, 640),
    seed: int = 7,
) -> Path:
    """Write an MVTec-style layout (folder datamodule friendly) and return the root."""
    import cv2

    root = Path(root)
    height, width = size
    layout = {
        "train_good": root / "train" / "good",
        "test_good": root / "test" / "good",
    }
    for kind in DEFECT_TYPES:
        layout[f"test_{kind}"] = root / "test" / kind
        layout[f"mask_{kind}"] = root / "ground_truth" / kind
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)

    for index in range(train_good):
        image = _texture(rng, height, width)
        cv2.imwrite(str(layout["train_good"] / f"{index:04d}.png"), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

    for index in range(test_good):
        image = _texture(rng, height, width)
        cv2.imwrite(str(layout["test_good"] / f"{index:04d}.png"), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

    for kind in DEFECT_TYPES:
        for index in range(per_defect):
            image = _texture(rng, height, width)
            defective, mask = _add_defect(image, rng, kind)
            name = f"{kind}_{index:04d}.png"
            cv2.imwrite(str(layout[f"test_{kind}"] / name), cv2.cvtColor(defective, cv2.COLOR_RGB2BGR))
            cv2.imwrite(str(layout[f"mask_{kind}"] / name), mask)

    total = train_good + test_good + per_defect * len(DEFECT_TYPES)
    logger.info("Demo dataset written to %s (%d images)", root, total)
    return root
