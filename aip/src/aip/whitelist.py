"""本班白名单（轻量防错）。

只放在 ``configs/shift_whitelist.yaml``，结构::

    codes:
      - AB-1234-01
      - CD-5566-02

文件不存在 = 不启用白名单（全部放行）；存在但空列表 = 全部拒绝。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _path() -> Path:
    override = os.environ.get("AIP_WHITELIST")
    if override:
        return Path(override)
    return ROOT / "configs" / "shift_whitelist.yaml"


@lru_cache(maxsize=8)
def _load(path_str: str, mtime: float) -> frozenset[str] | None:
    path = Path(path_str)
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    codes = data.get("codes") or []
    return frozenset(str(c) for c in codes)


def allowed_codes() -> frozenset[str] | None:
    """返回允许集合；None 表示未启用白名单。"""
    path = _path()
    if not path.exists():
        return None
    return _load(str(path), path.stat().st_mtime)


def is_allowed(code: str) -> bool:
    codes = allowed_codes()
    return True if codes is None else code in codes


def reset_cache() -> None:
    _load.cache_clear()
