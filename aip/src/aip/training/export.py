"""ONNX 导出。

当前训练是模拟器，没有真实权重可导。这里提供两条路：

1. `export_stub`：生成一个**真实的 ONNX 计算图**（输入 [-1,1] 图像 → 亮度均值分数），
   用于把"导出 → 挂载 → 冒烟 → 发布"整条链路跑通并测试；
2. `export_with_anomalib`：训练机装好 torch/anomalib 后，从 checkpoint 导出；
   未安装时给出可执行的错误，而不是静默返回假文件。

导出文件落在 `<data-dir>/models/<model>-v<version>.onnx`。
"""

from __future__ import annotations

from pathlib import Path


class ExportUnavailable(RuntimeError):
    pass


def _import_onnx():
    try:
        import onnx  # noqa: PLC0415
        from onnx import TensorProto, helper  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 环境相关
        raise ExportUnavailable(
            "未安装 onnx；服务端导出演示模型需 pip install onnx；"
            "真实模型请在训练机用 anomalib 导出后「挂 ONNX」"
        ) from exc
    return onnx, TensorProto, helper


def export_stub(out_path: Path, height: int = 256, width: int = 256) -> Path:
    """生成亮度均值模型：score = (mean(pixels)+1)/2，输入默认 [-1,1]。"""
    onnx, TensorProto, helper = _import_onnx()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    inp = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, height, width])
    out = helper.make_tensor_value_info("score", TensorProto.FLOAT, [1, 1, 1, 1])

    one = helper.make_tensor("one", TensorProto.FLOAT, [1], [1.0])
    half = helper.make_tensor("half", TensorProto.FLOAT, [1], [0.5])

    nodes = [
        helper.make_node("ReduceMean", ["images"], ["mean"], axes=[1, 2, 3], keepdims=1),
        helper.make_node("Add", ["mean", "one"], ["shifted"]),
        helper.make_node("Mul", ["shifted", "half"], ["score"]),
    ]
    graph = helper.make_graph(nodes, "aip_stub", [inp], [out], initializer=[one, half])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(out_path))
    return out_path


def export_with_anomalib(onnx_path: Path, checkpoint: str, model_name: str = "patchcore") -> Path:
    """训练机导出（需要 torch + anomalib）。"""
    try:
        from anomalib.deploy import ExportType, export_to_onnx  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 训练机才有
        raise ExportUnavailable(
            "当前环境没有 anomalib；真实导出请在训练机执行："
            "pip install anomalib torch，并配置 checkpoint 路径"
        ) from exc

    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    export_to_onnx(model=None, export_root=str(onnx_path.parent), model_name=model_name)  # type: ignore[arg-type]
    return onnx_path


def default_export_path(data_dir: Path, model_code: str, version_no: int) -> Path:
    safe = "".join(ch for ch in model_code if ch.isalnum() or ch in "-_") or "model"
    return data_dir / "models" / f"{safe}-v{version_no}.onnx"
