"""Typed configuration for a training/serving recipe.

A recipe is a single YAML file. Everything that changes between factories
(model, dataset layout, thresholds policy, export formats, serving backend)
lives there, so migrating to a new line is "copy the YAML, change 3 fields".
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

DataKind = Literal["folder", "mvtec", "visa", "btech"]
Backend = Literal["auto", "onnx", "torch"]


class _Model(BaseModel):
    """Base model that validates on assignment (needed by ``--set`` overrides)."""

    model_config = ConfigDict(validate_assignment=True)


class DataConfig(_Model):
    """Where the images come from and how they are batched.

    ``kind="folder"`` is the migration-friendly default: any directory layout
    with normal/abnormal/mask folders works, no dataset Wrangler required.
    """

    kind: DataKind = "folder"
    name: str | None = None
    root: Path
    # folder layout (relative to root)
    normal_dir: str | list[str] = "train/good"
    abnormal_dir: str | list[str] | None = None
    normal_test_dir: str | list[str] | None = None
    mask_dir: str | list[str] | None = None
    category: str | None = None
    extensions: list[str] | None = None
    normal_split_ratio: float = 0.2
    # batching / preprocessing
    image_size: tuple[int, int] = (256, 256)
    train_batch_size: int = 16
    eval_batch_size: int = 16
    num_workers: int = 0
    val_split_mode: str | None = None
    val_split_ratio: float | None = None
    test_split_mode: str | None = None
    test_split_ratio: float | None = None

    @field_validator("image_size")
    @classmethod
    def _size_is_pair(cls, value: tuple[int, int]) -> tuple[int, int]:
        if len(value) != 2 or min(value) <= 0:
            msg = f"image_size must be (height, width) of positive ints, got {value}"
            raise ValueError(msg)
        return (int(value[0]), int(value[1]))

    @property
    def label(self) -> str:
        """Stable short name used in run directories."""
        return self.name or self.category or self.kind


class ModelConfig(_Model):
    """Anomalib model class name plus its constructor arguments."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class TrainerConfig(_Model):
    """PyTorch Lightning trainer knobs that matter on consumer GPUs."""

    accelerator: str = "gpu"
    devices: int | str = 1
    precision: str = "32"  # "32" | "bf16-mixed" | "16-mixed"
    max_epochs: int | None = None  # None -> model decides (PatchCore: 1)
    overrides: dict[str, Any] = Field(default_factory=dict)
    compile: bool = False  # torch.compile the module (slow first call, then faster)
    channels_last: bool = False


class ExportConfig(_Model):
    """What to ship inside the artifact bundle."""

    formats: list[Literal["onnx", "torch"]] = Field(default_factory=lambda: ["onnx"])
    opset: int = 18
    # ONNX export of anomalib modules includes pre/post processing, so serving
    # only has to resize + scale to [0, 1].
    include_ckpt: bool = True


class ServeConfig(_Model):
    """HTTP inference defaults baked into the bundle."""

    backend: Backend = "auto"
    host: str = "0.0.0.0"
    port: int = 8000
    image_sensitivity: float = 0.5
    pixel_sensitivity: float = 0.5
    max_upload_mb: int = 16


class AipConfig(_Model):
    """Root recipe."""

    project: str
    seed: int | None = 42
    output_dir: Path = Path("artifacts")
    runs_dir: Path = Path("runs")
    data: DataConfig
    model: ModelConfig
    trainer: TrainerConfig = Field(default_factory=TrainerConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    serve: ServeConfig = Field(default_factory=ServeConfig)

    # --------------------------------------------------------------- loading
    @classmethod
    def from_yaml(cls, path: str | Path) -> AipConfig:
        """Load a recipe from YAML, resolving paths relative to the YAML file."""
        path = Path(path).resolve()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        config = cls.model_validate(raw)
        base = path.parent
        if not config.data.root.is_absolute():
            config.data.root = (base / config.data.root).resolve()
        if not config.output_dir.is_absolute():
            config.output_dir = (base.parent / config.output_dir).resolve()
        if not config.runs_dir.is_absolute():
            config.runs_dir = (base.parent / config.runs_dir).resolve()
        return config

    def dump(self, path: str | Path) -> Path:
        """Write the effective config next to the run artifacts (reproducibility)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.model_dump(mode="json")
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return path

    def with_overrides(self, overrides: list[str] | None) -> AipConfig:
        """Apply ``--set a.b=c`` style overrides (values parsed as YAML)."""
        if not overrides:
            return self
        clone = AipConfig.model_validate(copy.deepcopy(self.model_dump()))
        for item in overrides:
            key, separator, raw_value = item.partition("=")
            if not separator:
                msg = f"Override must look like key=value, got {item!r}"
                raise ValueError(msg)
            _set_path(clone, key.split("."), yaml.safe_load(raw_value))
        return AipConfig.model_validate(clone.model_dump())

    # --------------------------------------------------------------- helpers
    @property
    def bundle_dir(self) -> Path:
        """Stable location of the deployable artifact for this recipe."""
        return self.output_dir / self.project

    @property
    def run_root(self) -> Path:
        """Where lightning checkpoints / logs / metric dumps go."""
        return self.runs_dir / self.project


def load_config(path: str | Path, overrides: list[str] | None = None) -> AipConfig:
    """Load + patch a recipe in one call."""
    return AipConfig.from_yaml(path).with_overrides(overrides)


def _set_path(node: Any, parts: list[str], value: Any) -> None:  # noqa: ANN401
    """Assign ``value`` at ``parts`` inside a model/dict tree.

    ``model.args`` is a free-form dict, so a path can cross both pydantic models
    and plain dicts; handle both instead of assuming attributes all the way down.
    """
    head, *rest = parts
    if not rest:
        if isinstance(node, dict):
            node[head] = value
        else:
            setattr(node, head, value)
        return
    child = node[head] if isinstance(node, dict) else getattr(node, head)
    _set_path(child, rest, value)
