"""运行时配置（P2）。

只放"运行时可改、且改完要留痕"的项。启动级配置（端口、DB 路径、白名单路径）
不在这里——改了会断服务，应该走部署流程。
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from .audit import record
from .store import tx


@dataclass(frozen=True)
class Spec:
    key: str
    group: str
    label: str
    kind: str  # int | float | str | time | list | bool
    default: Any
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None


SPECS: tuple[Spec, ...] = (
    Spec("sampling.weekly_target", "抽样", "每周抽检量（件）", "int", 300, "盲判批次的抽样数", 1, 5000),
    Spec("sampling.min_ng", "抽样", "判定所需最小 NG 数", "int", 20, "人判 NG 少于此数时只能判不可判定", 1, 500),
    Spec("sampling.extend_weeks", "抽样", "样本不足时延长周数", "int", 8, "延长后仍不足则走低置信结项", 4, 26),
    Spec("judge.gray_rate_max", "判定", "灰区率上限", "float", 0.10, "超过则提示检查光源或阈值", 0.0, 1.0),
    Spec("judge.overkill_max", "判定", "过杀率上限", "float", 0.05, "发布门槛的一部分", 0.0, 1.0),
    Spec("judge.overkill_delta_pp", "判定", "过杀率允许增量（百分点）", "float", 2.0, "相对在用版本", 0.0, 20.0),
    Spec("train.window_start", "训练", "夜间窗口开始", "time", "01:00", "HH:MM", None, None),
    Spec("train.window_end", "训练", "夜间窗口结束", "time", "05:00", "HH:MM", None, None),
    Spec("train.max_minutes", "训练", "单次训练最长（分钟）", "int", 240, "超时视为失败", 10, 720),
    Spec("retention.crop_days", "存储", "判定裁片保留天数", "int", 30,
         "判例与待复核证据不受此限制", 1, 3650),
    Spec("retention.smoke_days", "存储", "冒烟图保留天数", "int", 7,
         "试判图只用于核对，可短保留", 1, 365),
    Spec("audit.retention_days", "存储", "审计保留天数", "int", 180,
         "超过该天数的审计记录可归档为 CSV 后删除；最少 30 天", 30, 3650),
    Spec("maintenance.auto_hour", "存储", "每日维护时间（UTC 小时）", "int", 3,
         "自动归档/清理在每天该小时执行；0-23", 0, 23),
    Spec("maintenance.auto_audit", "存储", "自动归档审计", "bool", False,
         "开启后每天把超过 audit.retention_days 的审计导出 CSV 并删除"),
    Spec("maintenance.auto_retention", "存储", "自动清理过期证据", "bool", False,
         "开启后每天按 retention.* 清理裁片与冒烟图（判例引用不删）"),
    Spec("infer.require_part_no", "接入", "必须带件号", "bool", False,
         "开启后未带 part_no 的请求会被拒绝（追溯要求）"),
    Spec("infer.require_batch_no", "接入", "必须带批次", "bool", False,
         "开启后未带 batch_no 的请求会被拒绝（按批统计要求）"),
    Spec("infer.crop_size_tolerance", "接入", "裁片与 ROI 尺寸容差（px）", "int", 8,
         "裁片宽高与 ROI 宽高偏差超过该值则拒绝；0=关闭", 0, 200),
    Spec("station.token", "接入", "站位接入令牌", "str", "",
         "非空时 /infer 与 /station/* 必须带 X-Station-Token"),
    Spec("ui.panel_enabled", "接入", "开放工位面板", "bool", True,
         "生产环境可关闭 /panel（测试页），关闭后访问返回 404"),
    Spec("serving.cache_ttl_min", "服务", "模型空闲回收（分钟）", "int", 15,
         "站位无请求超过该时长即释放引用；无引用后卸载模型", 1, 1440),
    Spec("serving.cache_max", "服务", "同时常驻模型上限", "int", 4,
         "超过时优先卸载无引用且最久未用的模型", 1, 16),
    Spec("infer.onnx_input_range", "接入", "ONNX 输入范围", "str", "pm1",
         "pm1=[-1,1]（anomalib 导出默认）；unit=[0,1]；需与导出时的预处理一致"),
    Spec("infer.onnx_aggregate", "接入", "ONNX 分数聚合", "str", "max",
         "max=取异常峰值；mean=取均值"),
    Spec("gate.min_side", "守门", "裁片最小边长（px）", "int", 32, "低于则拒绝", 8, 2048),
    Spec("gate.min_brightness", "守门", "亮度下限", "float", 10.0, "0–255", 0.0, 255.0),
    Spec("gate.max_brightness", "守门", "亮度上限", "float", 245.0, "0–255", 0.0, 255.0),
    Spec("gate.min_contrast", "守门", "对比度下限（标准差）", "float", 5.0, "低于则视为无纹理", 0.0, 128.0),
    Spec(
        "review.show_references_default",
        "复核",
        "默认显示参考样例",
        "bool",
        True,
        "关掉后复核页默认折叠，需手动展开",
    ),
    Spec("review.gray_route", "复核", "灰区处理方式", "str", "queue",
         "queue=进待复核并提示人工；stop=直接拦停，等人工放行"),
    Spec(
        "reasons.list",
        "理由预设",
        "改判理由",
        "list",
        ["划痕", "脏污", "压伤", "误报", "其他"],
        "逐个添加，最多 10 条",
        None,
        None,
    ),
)

BY_KEY = {s.key: s for s in SPECS}
GROUPS = ("抽样", "判定", "复核", "训练", "守门", "服务", "接入", "存储", "理由预设")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _decode(spec: Spec, raw: str) -> Any:
    value = json.loads(raw)
    return _coerce(spec, value)


def _coerce(spec: Spec, value: Any) -> Any:
    if spec.kind == "int":
        ivalue = int(value)
        if spec.minimum is not None and ivalue < spec.minimum:
            raise ValueError(f"{spec.label} 不能小于 {spec.minimum}")
        if spec.maximum is not None and ivalue > spec.maximum:
            raise ValueError(f"{spec.label} 不能大于 {spec.maximum}")
        return ivalue
    if spec.kind == "float":
        fvalue = float(value)
        if spec.minimum is not None and fvalue < spec.minimum:
            raise ValueError(f"{spec.label} 不能小于 {spec.minimum}")
        if spec.maximum is not None and fvalue > spec.maximum:
            raise ValueError(f"{spec.label} 不能大于 {spec.maximum}")
        return fvalue
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{spec.label} 只能是 true/false")
    if spec.kind == "time":
        text = str(value)
        if not _TIME_RE.match(text):
            raise ValueError(f"{spec.label} 需要 HH:MM 格式")
        return text
    if spec.kind == "list":
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        items = [str(v).strip() for v in value if str(v).strip()]
        if not items:
            raise ValueError(f"{spec.label} 不能为空")
        if len(items) > 10:
            raise ValueError(f"{spec.label} 最多 10 条")
        return items
    return str(value)


def get_value(conn: sqlite3.Connection, key: str) -> Any:
    spec = BY_KEY[key]
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    if row is None:
        return spec.default
    return _decode(spec, row["value"])


def all_settings(conn: sqlite3.Connection) -> list[dict]:
    rows = {r["key"]: r for r in conn.execute("SELECT * FROM setting").fetchall()}
    out: list[dict] = []
    for spec in SPECS:
        row = rows.get(spec.key)
        out.append(
            {
                "key": spec.key,
                "group": spec.group,
                "label": spec.label,
                "kind": spec.kind,
                "description": spec.description,
                "default": spec.default,
                "value": _decode(spec, row["value"]) if row else spec.default,
                "updated_by": row["updated_by"] if row else None,
                "updated_at": row["updated_at"] if row else None,
                "minimum": spec.minimum,
                "maximum": spec.maximum,
            }
        )
    return out


def set_value(conn: sqlite3.Connection, key: str, value: Any, *, actor: str) -> Any:
    spec = BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"未知配置项: {key}")
    coerced = _coerce(spec, value)
    with tx(conn):
        conn.execute(
            "INSERT INTO setting (key, value, updated_by, updated_at)"
            " VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " updated_by = excluded.updated_by, updated_at = excluded.updated_at",
            (key, json.dumps(coerced, ensure_ascii=False), actor),
        )
        record(
            conn,
            actor=actor,
            action="setting.update",
            entity="setting",
            entity_id=key,
            payload={"value": coerced},
        )
    return coerced


def set_many(
    conn: sqlite3.Connection, values: dict[str, Any], *, actor: str = "web"
) -> dict[str, Any]:
    """批量保存：任一键非法则整体拒绝，不做半套写入。"""
    if not values:
        raise ValueError("没有要保存的配置")
    coerced: dict[str, Any] = {}
    for key, value in values.items():
        spec = BY_KEY.get(key)
        if spec is None:
            raise KeyError(f"未知配置项: {key}")
        coerced[key] = _coerce(spec, value)

    with tx(conn):
        for key, value in coerced.items():
            conn.execute(
                "INSERT INTO setting (key, value, updated_by, updated_at)"
                " VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                " updated_by = excluded.updated_by, updated_at = excluded.updated_at",
                (key, json.dumps(value, ensure_ascii=False), actor),
            )
        record(
            conn,
            actor=actor,
            action="setting.bulk_update",
            entity="setting",
            payload={"keys": sorted(coerced), "values": coerced},
        )
    return coerced


def gate_config(conn: sqlite3.Connection) -> dict[str, float]:
    """给入口守门用的四个阈值。"""
    return {
        "min_side": get_value(conn, "gate.min_side"),
        "min_brightness": get_value(conn, "gate.min_brightness"),
        "max_brightness": get_value(conn, "gate.max_brightness"),
        "min_contrast": get_value(conn, "gate.min_contrast"),
    }
