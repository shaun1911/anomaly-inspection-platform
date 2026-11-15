"""从 FastAPI 应用生成 API 端点清单（docs/api/endpoints.md）。

    python scripts/gen_api_doc.py

离线生成，不需要起服务；不访问数据库（只读 openapi schema）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aip" / "src"))

from aip.api.app import create_app  # noqa: E402

# 分组顺序与中文名
GROUPS = [
    ("infer", "推理（工位客户端）"),
    ("station", "站位配置"),
    ("results", "结果与复核确认"),
    ("review", "复核队列"),
    ("api/codes", "编码 / 模型 / 绑定"),
    ("api/models", "模型版本与发布"),
    ("api/datasets", "数据集"),
    ("api/train", "训练"),
    ("api/blind", "盲判抽检"),
    ("api/cases", "判例库"),
    ("api/settings", "设置"),
    ("api/maintenance", "维护（迁移/备份/审计归档）"),
    ("api/audit", "审计日志"),
    ("api/stats", "统计"),
    ("api/metrics", "监控指标"),
    ("api/search", "全局搜索"),
    ("health", "健康检查"),
]


def group_of(path: str) -> str:
    for prefix, title in GROUPS:
        if path == f"/{prefix}" or path.startswith(f"/{prefix}/") or path.startswith(f"/{prefix}?"):
            return title
    if path.startswith("/api/"):
        return "其他管理接口"
    return "页面"


RESOURCE = {
    "codes": "编码", "models": "模型", "bindings": "绑定", "configs": "ROI 配置",
    "thresholds": "阈值", "config": "配置", "configs": "ROI 配置", "datasets": "数据集", "cases": "判例", "review": "复核",
    "results": "结果", "train": "训练", "blind": "抽检", "settings": "设置",
    "maintenance": "维护", "audit": "审计", "stations": "站位", "metrics": "指标",
    "stats": "统计", "search": "搜索", "infer": "推理", "station": "站位",
    "versions": "版本", "items": "成员", "families": "产品族", "image": "图片",
    "references": "参考图", "export": "导出", "smoke": "冒烟", "rollback": "回滚",
    "onnx": "ONNX", "archive": "归档", "restore": "恢复", "confirm": "确认",
    "claim": "领取", "skip": "暂缓", "release": "释放", "freeze": "冻结",
    "queue": "队列", "pending": "待复核", "heartbeat": "心跳", "health": "健康",
    "storage": "存储", "backup": "备份", "restore": "还原", "move": "迁移",
    "import": "导入", "feedback": "反馈", "thumb": "缩略图",
}
VERB = {"get": "查询", "post": "提交", "put": "更新", "patch": "修改", "delete": "删除"}

# 高频接口用明确说明，其余按「动词 + 资源」生成
OVERRIDES = {
    ("POST", "/infer"): "推图判定（默认异步 202；`?sync=1` 同步 200 返回结果）",
    ("GET", "/infer/{job_id}"): "查询推理任务与结果（含 decision）",
    ("POST", "/infer/feedback"): "提交人工复核反馈",
    ("GET", "/station/config"): "换型：取编码对应的模型版本/ROI/阈值",
    ("POST", "/station/heartbeat"): "站位心跳",
    ("GET", "/review/queue"): "复核队列（可按编码/结果/编码族/批次分组）",
    ("GET", "/review/pending"): "工位待复核列表",
    ("POST", "/review/{result_id}/claim"): "领取复核项",
    ("POST", "/review/{result_id}/confirm"): "确认复核结论",
    ("GET", "/api/settings"): "读取全部设置项",
    ("POST", "/api/settings/bulk"): "批量保存设置（一次事务）",
    ("GET", "/api/audit"): "审计日志分页查询（动作/人/时间）",
    ("GET", "/api/search"): "全局搜索（编码/件号/模型）",
    ("POST", "/api/train"): "用冻结数据集启动训练",
    ("GET", "/health"): "健康检查（服务/数据库/队列）",
}


def describe(method: str, path: str) -> str:
    if (method.upper(), path) in OVERRIDES:
        return OVERRIDES[(method.upper(), path)]
    parts = [p for p in path.strip("/").split("/") if p and not p.startswith("{")]
    skip = {"api"}
    words = [RESOURCE.get(p, p) for p in parts if p not in skip]
    tail = " / ".join(words[-2:]) if words else path
    if method == "get":
        return f"查询 {tail}"
    if method == "delete":
        return f"删除 {tail}"
    if method == "put" or method == "patch":
        return f"更新 {tail}"
    return f"提交 {tail}"


def main() -> int:
    app = create_app(ROOT / "data" / "aip.db")
    spec = app.openapi()
    rows: dict[str, list[tuple[str, str, str]]] = {}
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if op.get("include_in_schema") is False:
                continue
            rows.setdefault(group_of(path), []).append((method.upper(), path, describe(method, path)))

    out = ["# API 端点清单（自动生成）", "", "> 由 `scripts/gen_api_doc.py` 从 OpenAPI 生成，不要手改。",
           "> 字段级说明见运行中的 `/docs`（Swagger UI）或 `/openapi.json`。", ""]
    for _, title in GROUPS + [("other", "其他管理接口")]:
        items = rows.pop(title, None)
        if not items:
            continue
        out.append(f"## {title}")
        out.append("")
        out.append("| 方法 | 路径 | 说明 |")
        out.append("|---|---|---|")
        for method, path, text in sorted(items):
            out.append(f"| {method} | `{path}` | {text} |")
        out.append("")

    for title, items in rows.items():
        out.append(f"## {title}")
        out.append("")
        out.append("| 方法 | 路径 | 说明 |")
        out.append("|---|---|---|")
        for method, path, text in sorted(items):
            out.append(f"| {method} | `{path}` | {text} |")
        out.append("")

    dest = ROOT / "docs" / "api" / "endpoints.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out), encoding="utf-8")
    total = sum(len(v) for v in rows.values())
    print(f"written {dest} ({sum(1 for line in out if line.startswith('| ')) - 2 * 0} table rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
