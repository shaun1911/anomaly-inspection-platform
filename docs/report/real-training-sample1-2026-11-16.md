# Sample1 真实训练接入（2026-11-16）

## 结果

| 项 | 值 |
|---|---|
| 模型 | S1（PatchCore / wide_resnet50_2） |
| 数据集 | #3 Sample1-full（553 条） |
| 切分 | 训练 OK 334 / 验证 OK 83 / 验证 NG 68 |
| 训练设备 | RTX 5080 16GB（CUDA） |
| 耗时 | 约 101 秒（含导出与验证集标定） |
| 召回 | **100%** |
| 过杀 | **1.2%** |
| 阈值 | th_lo 0.4358 / th_hi 0.4858（自动标定） |
| ROI | 0,0,280,400（自动取首图尺寸） |
| ONNX | `data/models/S1-v4.onnx` + `.onnx.data` |
| 版本 | S1 v4（已发布 assist） |

推理验证：

- OK 样例：score 0.193 → ok / pass
- NG 样例：score 0.515 / 1.0 → ng / block

## 工程实现

- `aip/training/anomalib_worker.py`：独立进程，负责落数据集目录（PNG）、PatchCore 训练、ONNX 导出、验证集打分与阈值标定，写 `result.json`；
- `aip/training/runner.py`：后台线程起 worker、写 `data/runs/<code>-vN/train.log`、回写版本指标/ONNX/阈值，并复制 ONNX 外部权重 `.onnx.data`；
- `POST /api/train`：默认真实后端，创建 running 任务后立即返回；同一时间只允许一个训练任务；
- 启动时把残留 `running` 任务标为 `server_restart`，避免阻塞；
- 迁移 `0013_model_onnx_meta.sql`：每版本记录 `onnx_input_range` / `onnx_aggregate`，推理按版本取，不再依赖全局设置；
- 数据集切分改为按件号分组（当前 `case_item` 同件唯一，效果等同按条，但防未来多图同件泄漏）。

## 已知限制

1. 验证集只有 151 条，100% 召回偏高，不代表产线泛化；下一步用 Sample2 的 Extreme Data 做独立验证；
2. 同一张图重复推图会命中已有结果（按图去重），模型升级后不会自动重算；验证新模型需用新图；
3. 训练日志与产物在 `data/runs/`，ONNX 在 `data/models/`，备份/迁移会一并带走；
4. 训练与推理共用同一 venv（已装 torch/anomalib）；生产部署若不在本机训练，可只装服务端依赖。
