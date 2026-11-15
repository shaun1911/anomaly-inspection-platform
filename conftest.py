"""Make ``aip`` importable from a fresh clone without installing."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "aip" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import pytest as _pytest


@_pytest.fixture(autouse=True)
def reset_model_cache():
    """模型缓存是进程级单例，测试间必须清空。"""
    from aip.serving.cache import cache

    cache.reset()
    yield
    cache.reset()
