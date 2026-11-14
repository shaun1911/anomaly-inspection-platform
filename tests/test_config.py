"""Recipe loading and CLI-style overrides."""

from __future__ import annotations

from pathlib import Path

import pytest

from aip.config import AipConfig, load_config

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "demo_patchcore.yaml"


def test_loads_demo_recipe() -> None:
    config = load_config(CONFIG)
    assert config.project == "demo-metal"
    assert config.data.kind == "folder"
    assert config.data.image_size == (256, 256)
    assert config.model.name == "Patchcore"
    assert config.data.root.is_absolute()
    # bundle lives next to the repo, not next to the yaml
    assert config.bundle_dir.name == "demo-metal"


def test_override_nested_model_arg() -> None:
    config = load_config(CONFIG, ["model.args.backbone=wide_resnet50_2", "project=line-a"])
    assert config.model.args["backbone"] == "wide_resnet50_2"
    assert config.project == "line-a"
    assert config.bundle_dir.name == "line-a"


def test_override_image_size_from_cli_string() -> None:
    config = load_config(CONFIG, ["data.image_size=[320,384]"])
    assert config.data.image_size == (320, 384)


def test_override_rejects_malformed_item() -> None:
    with pytest.raises(ValueError, match="key=value"):
        load_config(CONFIG, ["model.args.backbone"])


def test_roundtrip_dump(tmp_path: Path) -> None:
    config = load_config(CONFIG)
    path = config.dump(tmp_path / "config.yaml")
    reloaded = AipConfig.from_yaml(path)
    assert reloaded.model.args == config.model.args
    assert reloaded.data.image_size == config.data.image_size
