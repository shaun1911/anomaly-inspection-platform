"""admin 页面静态冒烟：防止整段替换时删掉函数或状态声明。

只做静态检查（不跑浏览器）：
1. 路由里调用的 renderX 必须都有定义；
2. 页面级状态声明必须存在；
3. 内联脚本必须只有一段。
"""

from __future__ import annotations

import re
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "aip" / "web" / "admin.html"


def _script() -> str:
    text = HTML.read_text(encoding="utf-8")
    blocks = re.findall(r"<script>(.*?)</script>", text, re.S)
    assert len(blocks) == 1, f"内联脚本应为 1 段，实际 {len(blocks)}"
    return blocks[0]


def test_route_functions_are_defined():
    script = _script()
    called = set(re.findall(r"await (render\w+)\(", script))
    called |= set(re.findall(r"return (render\w+)\(", script))
    defined = set(re.findall(r"async function (render\w+)\(", script))
    defined |= set(re.findall(r"function (render\w+)\(", script))
    missing = sorted(called - defined)
    assert not missing, f"路由调用了未定义的函数: {missing}"


def test_page_state_declarations_exist():
    script = _script()
    required = [
        "let wiz =",
        "let trainingState =",
        "let datasetState =",
        "let blindState =",
        "let systemState =",
        "let reviewState =",
        "let caseState =",
        "let settingsState =",
        "const TITLES =",
        "const ACTIONS =",
    ]
    missing = [name for name in required if name not in script]
    assert not missing, f"缺少状态声明: {missing}"


def test_global_error_surface_present():
    """白屏兜底：脚本错误要能显示在页面上。"""
    script = _script()
    assert "unhandledrejection" in script
    assert 'addEventListener("error"' in script
