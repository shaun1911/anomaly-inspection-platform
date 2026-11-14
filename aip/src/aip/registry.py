"""Factories that turn a recipe into anomalib objects, plus hardware probing.

Keeping every ``anomalib`` import inside a function keeps CLI start-up fast and
makes the package importable on a box without a GPU (for artifact inspection).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from .config import AipConfig

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- data
def build_datamodule(config: AipConfig):
    """Instantiate the anomalib DataModule described by ``config.data``."""
    from anomalib.data import BTech, Folder, MVTecAD, Visa

    data = config.data
    common: dict[str, Any] = {
        "train_batch_size": data.train_batch_size,
        "eval_batch_size": data.eval_batch_size,
        "num_workers": data.num_workers,
        "seed": config.seed,
    }
    if data.val_split_mode is not None:
        common["val_split_mode"] = data.val_split_mode
    if data.val_split_ratio is not None:
        common["val_split_ratio"] = data.val_split_ratio
    if data.test_split_mode is not None:
        common["test_split_mode"] = data.test_split_mode
    if data.test_split_ratio is not None:
        common["test_split_ratio"] = data.test_split_ratio

    if data.kind == "folder":
        return Folder(
            name=data.name or config.project,
            root=data.root,
            normal_dir=data.normal_dir,
            abnormal_dir=data.abnormal_dir,
            normal_test_dir=data.normal_test_dir,
            mask_dir=data.mask_dir,
            extensions=tuple(data.extensions) if data.extensions else None,
            normal_split_ratio=data.normal_split_ratio,
            **common,
        )

    if data.kind == "mvtec":
        return MVTecAD(root=data.root, category=data.category or "", **common)
    if data.kind == "visa":
        return Visa(root=data.root, category=data.category or "", **common)
    if data.kind == "btech":
        return BTech(root=data.root, category=data.category, **common)

    msg = f"Unsupported data kind: {data.kind}"
    raise ValueError(msg)


# -------------------------------------------------------------------- model
def build_model(config: AipConfig):
    """Instantiate the anomalib model named in the recipe."""
    from anomalib.models import get_model

    model = get_model(config.model.name, **config.model.args)
    logger.info("Model: %s | learning_type=%s", model.name, model.learning_type.value)
    return model


# --------------------------------------------------------------------- gpu
def configure_hardware(config: AipConfig) -> dict[str, Any]:
    """Enable the fast paths that are safe on consumer Blackwell GPUs.

    - TF32 for fp32 matmul/conv (Ampere+): big speed-up, no accuracy change that
      matters for feature-extraction models.
    - cuDNN benchmark: picks the best conv algorithm for the fixed input size.
    - deterministic-less seeding: reproducible runs without killing throughput.

    Returns a small report so it can be logged into the run metadata.
    """
    import torch

    report: dict[str, Any] = {
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda": torch.version.cuda,
    }
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        report.update(
            {
                "device": props.name,
                "capability": f"{props.major}.{props.minor}",
                "vram_gb": round(props.total_memory / 1024**3, 1),
                "sm_count": props.multi_processor_count,
            }
        )
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True
        torch.set_float32_matmul_precision("high")

    if config.seed is not None:
        import lightning as L

        L.seed_everything(config.seed, workers=True)

    # Win32 + DataLoader workers > 0 needs the spawn guard; keep the recipe
    # honest instead of silently hanging the first epoch.
    if sys.platform == "win32" and config.data.num_workers > 0:
        logger.warning(
            "num_workers=%s on Windows spawns processes; if the run hangs, set data.num_workers=0.",
            config.data.num_workers,
        )
    return report


# ------------------------------------------------------------------ engine
def build_engine(config: AipConfig):
    """Create the anomalib ``Engine`` with recipe-level trainer settings."""
    from anomalib.engine import Engine

    trainer_args: dict[str, Any] = {
        "accelerator": config.trainer.accelerator,
        "devices": config.trainer.devices,
        "precision": config.trainer.precision,
        "default_root_dir": config.run_root,
    }
    if config.trainer.max_epochs is not None:
        trainer_args["max_epochs"] = config.trainer.max_epochs
    if config.trainer.compile:
        trainer_args["compile"] = True
    trainer_args.update(config.trainer.overrides)
    return Engine(**trainer_args)


# --------------------------------------------------------------- diagnostics
def doctor() -> dict[str, Any]:
    """Collect an environment report (used by ``aip doctor`` and the bundle)."""
    import torch

    info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "torch": torch.__version__,
        "torchvision": _safe_version("torchvision"),
        "anomalib": _safe_version("anomalib"),
        "cuda_available": torch.cuda.is_available(),
        "cuda_build": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "tf32_matmul": torch.backends.cuda.matmul.allow_tf32,
    }
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        info["gpu"] = {
            "name": props.name,
            "capability": f"sm_{props.major}{props.minor}",
            "vram_gb": round(props.total_memory / 1024**3, 1),
            "sm_count": props.multi_processor_count,
        }
    try:
        import onnxruntime as ort

        info["onnxruntime"] = {
            "version": ort.__version__,
            "providers": ort.get_available_providers(),
        }
    except ImportError:  # pragma: no cover - optional dependency
        info["onnxruntime"] = None
    return info


def _safe_version(module: str) -> str | None:
    try:
        return __import__(module).__version__
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return None


def prepare_env() -> None:
    """Project-local defaults that must be set before torch initialises."""
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    # keeps HF downloads (timm backbones) out of the user profile when possible
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    # Windows consoles default to GBK; Rich's progress bar renders bullets and
    # would raise UnicodeEncodeError mid-training. UTF-8 everywhere is required.
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def dataset_summary(datamodule) -> dict[str, Any]:
    """Count samples per split; useful in run metadata and for sanity checks."""
    datamodule.setup()
    summary: dict[str, Any] = {}
    for split in ("train_data", "val_data", "test_data"):
        data = getattr(datamodule, split, None)
        if data is None:
            continue
        try:
            frame = data.samples
            summary[split] = {
                "total": int(len(frame)),
                "normal": int((frame["label_index"] == 0).sum()),
                "abnormal": int((frame["label_index"] == 1).sum()),
            }
        except Exception:  # noqa: BLE001 - metadata only
            summary[split] = {"total": len(data)}
    return summary


def resolve_device(requested: str = "auto"):
    """Pick a torch device string."""
    import torch

    if requested == "cpu":
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    logger.warning("CUDA not available, falling back to CPU.")
    return "cpu"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
