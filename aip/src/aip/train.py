"""Train / evaluate / export orchestration.

One call does the whole factory loop: fit -> test -> export bundle -> record
provenance. Everything is logged under ``runs/<project>`` and the deployable
output lands in ``artifacts/<project>``.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .bundle import build_bundle
from .config import AipConfig
from .registry import (
    build_datamodule,
    build_engine,
    build_model,
    configure_hardware,
    dataset_summary,
    prepare_env,
)

logger = logging.getLogger(__name__)


def run_training(config: AipConfig) -> dict[str, Any]:
    """Fit the model, evaluate it, and produce the artifact bundle."""
    prepare_env()
    hardware = configure_hardware(config)

    datamodule = build_datamodule(config)
    datamodule.setup()
    splits = dataset_summary(datamodule)
    logger.info("Dataset splits: %s", splits)

    model = build_model(config)
    engine = build_engine(config)

    logger.info(
        "Training %s on %s | device=%s | precision=%s | batch=%d",
        model.name,
        config.data.label,
        hardware.get("device", "cpu"),
        config.trainer.precision,
        config.data.train_batch_size,
    )
    started = time.perf_counter()
    engine.fit(model=model, datamodule=datamodule)
    fit_seconds = time.perf_counter() - started

    results = engine.test(model=model, datamodule=datamodule)
    metrics = _first_result(results)
    logger.info("Test metrics: %s", json.dumps(metrics, indent=2))

    bundle = build_bundle(
        config=config,
        engine=engine,
        model=model,
        metrics=metrics,
        dataset_info=splits,
        hardware=hardware,
        train_seconds=fit_seconds,
    )

    report = {
        "project": config.project,
        "model": model.name,
        "bundle": str(bundle),
        "fit_seconds": round(fit_seconds, 2),
        "metrics": metrics,
        "dataset": splits,
        "hardware": hardware,
    }
    _write_json(config.run_root / "last_run.json", report)
    return report


def run_test(config: AipConfig, bundle: str | Path | None = None) -> dict[str, Any]:
    """Re-evaluate a bundle on the recipe's dataset (regression gate)."""
    import torch
    import anomalib.models as models

    from anomalib.engine import Engine

    prepare_env()
    hardware = configure_hardware(config)
    datamodule = build_datamodule(config)
    datamodule.setup()

    model_cls = getattr(models, config.model.name)
    ckpt = Path(bundle or config.bundle_dir) / "model.ckpt"
    if not ckpt.exists():
        msg = f"Checkpoint not found: {ckpt}"
        raise FileNotFoundError(msg)

    model = model_cls.load_from_checkpoint(str(ckpt), map_location="cuda" if torch.cuda.is_available() else "cpu")
    engine = Engine(
        accelerator=config.trainer.accelerator,
        devices=1,
        precision=config.trainer.precision,
        default_root_dir=config.run_root,
    )
    results = engine.test(model=model, datamodule=datamodule)
    metrics = _first_result(results)
    report = {"project": config.project, "model": config.model.name, "metrics": metrics, "hardware": hardware}
    _write_json(config.run_root / "last_test.json", report)
    return report


def _first_result(results: Any) -> dict[str, Any]:
    """``Engine.test`` returns a list of dicts (one per dataloader)."""
    if not results:
        return {}
    first = results[0]
    return {key: _jsonable(value) for key, value in dict(first).items()}


def _jsonable(value: Any) -> Any:  # noqa: ANN401
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
