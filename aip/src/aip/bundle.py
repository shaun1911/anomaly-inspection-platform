"""Build and read the deployable artifact bundle.

A bundle is the *only* thing you copy to a factory PC::

    artifacts/<project>/
      metadata.json     # everything the runtime needs to reproduce inference
      model.onnx        # pre-process + model + post-process, portable
      model.ckpt        # lightning checkpoint (retrain / parity checks)
      config.yaml       # the exact recipe that produced it

Two rules keep it self-contained:

1. never store absolute paths that the runtime depends on;
2. put every learned constant (threshold, min/max, image size, sensitivity)
   into ``metadata.json`` instead of relying on the ONNX graph being in sync.
   The graph *does* embed them today, but a runtime that re-derives labels from
   the raw score needs them explicitly, and a human reading the artifact needs
   to see what the model will do.
"""

from __future__ import annotations

import json
import logging
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AipConfig

logger = logging.getLogger(__name__)

BUNDLE_FORMAT_VERSION = 1


def _as_float(value: Any) -> float | None:
    """Convert a tensor/scalar to float, mapping nan/inf to ``None``."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result or result in (float("inf"), float("-inf")) else result


def extract_postprocess_state(model) -> dict[str, Any]:
    """Read the learned thresholds and normalisation range off the module.

    ``PostProcessor`` keeps them in buffers so they survive checkpointing; the
    effective values apply the "threshold matching" fallback.
    """
    processor = getattr(model, "post_processor", None)
    if processor is None:
        return {}
    state: dict[str, Any] = {
        "enabled": True,
        "image_sensitivity": float(getattr(processor, "image_sensitivity", 0.5)),
        "pixel_sensitivity": float(getattr(processor, "pixel_sensitivity", 0.5)),
        "enable_normalization": bool(getattr(processor, "enable_normalization", True)),
        "enable_thresholding": bool(getattr(processor, "enable_thresholding", True)),
    }
    for key, attr in (
        ("image_threshold", "image_threshold"),
        ("pixel_threshold", "pixel_threshold"),
        ("image_min", "image_min"),
        ("image_max", "image_max"),
        ("pixel_min", "pixel_min"),
        ("pixel_max", "pixel_max"),
    ):
        state[key] = _as_float(getattr(processor, attr, None))
    state["normalized_image_threshold"] = 1.0 - state["image_sensitivity"]
    state["normalized_pixel_threshold"] = 1.0 - state["pixel_sensitivity"]
    return state


def extract_preprocess_state(model, image_size: tuple[int, int]) -> dict[str, Any]:
    """Describe the input contract (the ONNX graph already embeds the transform)."""
    mean, std = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
    transform = getattr(getattr(model, "pre_processor", None), "transform", None)
    for module in getattr(transform, "transforms", []) or []:
        if hasattr(module, "mean") and hasattr(module, "std"):
            mean = [float(v) for v in module.mean]
            std = [float(v) for v in module.std]
    return {
        "size": [int(image_size[0]), int(image_size[1])],
        "layout": "NCHW",
        "color": "RGB",
        "dtype": "float32",
        "value_range": [0.0, 1.0],
        "mean": mean,
        "std": std,
        "resize": "bilinear",
        "note": "Feed raw RGB pixels / 255; the exported graph applies Resize+Normalize itself.",
    }


def build_bundle(
    config: AipConfig,
    engine,
    model,
    metrics: dict[str, Any] | None,
    dataset_info: dict[str, Any] | None = None,
    hardware: dict[str, Any] | None = None,
    train_seconds: float | None = None,
) -> Path:
    """Export the trained module and write the artifact bundle."""
    image_size = tuple(model.input_size or config.data.image_size)
    bundle = config.bundle_dir
    if bundle.exists():
        # keep the previous bundle diffable / recoverable
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = bundle.with_name(f"{bundle.name}.prev-{stamp}")
        shutil.move(str(bundle), str(backup))
        logger.info("Previous bundle moved to %s", backup)
    bundle.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, str] = {}

    # ------------------------------------------------------------- checkpoint
    if config.export.include_ckpt:
        ckpt = getattr(engine, "best_model_path", None)
        if ckpt and Path(ckpt).exists():
            shutil.copy2(ckpt, bundle / "model.ckpt")
            artifacts["ckpt"] = "model.ckpt"
        else:
            logger.warning("No checkpoint found; bundle will miss model.ckpt")

    # ------------------------------------------------------------------ onnx
    if "onnx" in config.export.formats:
        try:
            exported = engine.export(
                model=model,
                export_type="onnx",
                export_root=bundle / "_export",
                model_file_name="model",
                input_size=image_size,  # type: ignore[arg-type]
                # single-file graph: no stray model.onnx.data to forget when
                # copying the bundle to a factory PC
                onnx_kwargs={"opset_version": config.export.opset, "external_data": False},
            )
            if exported is not None:
                target = bundle / "model.onnx"
                shutil.move(str(exported), str(target))
                artifacts["onnx"] = "model.onnx"
                # tolerate exporters that still spill weights to a side file
                for side_car in Path(exported).parent.glob("model.onnx.data*"):
                    shutil.move(str(side_car), str(bundle / side_car.name))
                    artifacts.setdefault("onnx_external_data", []).append(side_car.name)
            shutil.rmtree(bundle / "_export", ignore_errors=True)
        except Exception as error:  # noqa: BLE001 - export must not kill the run
            logger.exception("ONNX export failed: %s", error)

    if "torch" in config.export.formats:
        try:
            exported = engine.export(model=model, export_type="torch", export_root=bundle / "_export")
            if exported is not None:
                shutil.move(str(exported), str(bundle / "model.pt"))
                artifacts["torch"] = "model.pt"
            shutil.rmtree(bundle / "_export", ignore_errors=True)
        except Exception as error:  # noqa: BLE001
            logger.exception("Torch export failed: %s", error)

    # -------------------------------------------------------------- metadata
    metadata = {
        "bundle_format": BUNDLE_FORMAT_VERSION,
        "created_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "project": config.project,
        "model": {"name": model.name, "args": config.model.args, "learning_type": model.learning_type.value},
        "dataset": {
            "kind": config.data.kind,
            "root": str(config.data.root),
            "category": config.data.category,
            "splits": dataset_info or {},
        },
        "input": extract_preprocess_state(model, image_size),  # type: ignore[arg-type]
        "postprocess": extract_postprocess_state(model),
        "metrics": metrics or {},
        "artifacts": artifacts,
        "training": {
            "seed": config.seed,
            "fit_seconds": round(train_seconds, 2) if train_seconds else None,
            "max_epochs": config.trainer.max_epochs,
            "precision": config.trainer.precision,
            "batch_size": config.data.train_batch_size,
        },
        "environment": {
            "anomalib": _version("anomalib"),
            "torch": _version("torch"),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "hardware": hardware or {},
        },
    }
    (bundle / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    config.dump(bundle / "config.yaml")

    logger.info("Bundle written to %s (artifacts: %s)", bundle, ", ".join(artifacts) or "none")
    return bundle


def read_metadata(bundle: str | Path) -> dict[str, Any]:
    """Load ``metadata.json`` from a bundle directory."""
    path = Path(bundle)
    if path.is_file():
        path = path.parent
    meta_path = path / "metadata.json"
    if not meta_path.exists():
        msg = f"{meta_path} not found: not an AIP bundle?"
        raise FileNotFoundError(msg)
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _version(module: str) -> str | None:
    try:
        return __import__(module).__version__
    except Exception:  # noqa: BLE001
        return None
