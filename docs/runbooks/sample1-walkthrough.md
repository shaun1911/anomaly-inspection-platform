# Sample1 全流程走查

目标：用 `sample/Sample1`（417 OK / 136 NG，BMP 280×400）走一遍"判例 → 数据集 → 训练 → 配置 → 发布 → 推图 → 复核"。

> **训练后端**：服务端 anomalib 2.7 / PatchCore，独立 worker 进程；训练完自动导出 ONNX 并标定阈值。

## 已准备好的数据

| 项 | 值 |
|---|---|
| 编码 | `VPTXDF-18B955-CP`（零件：排线口B） |
| 模型 | `S1`（Sample1 排线口B） |
| 判例 | 553 条（417 ok / 136 ng），图片为 BMP |
| 数据集 | `Sample1-full`（id 3，已冻结，校验和 `4ca4a365…`） |
| 训练集/验证集 | 416 / 137 |

## 步骤

### 0. 启动

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

打开 `http://127.0.0.1:8100/admin`。

### 1. 确认数据

- 侧栏「数据集」：能看到 `Sample1-full`，总数 553，状态 **已冻结**；
- 「判例库」筛选编码 `VPTXDF-18B955-CP`：OK/NG 都有，缩略图能显示（BMP）。

### 2. 训练（模拟）

侧栏「训练与发布」：

1. 模型下拉选 **S1 · Sample1 排线口B**；
2. 数据集下拉选 **#3 Sample1-full**；
3. 点「开始训练」。

预期：训练任务状态为「运行中」→「成功」（Sample1 约 1.5 分钟，首次会下载预训练权重）。完成后模型 S1 下出现候选版本，带真实召回/过杀、ONNX 与自动配置的 ROI/阈值。

'### 3. 配置 ROI 与阈值（针对候选版本）

侧栏「编码与模型」→ 点编码 `VPTXDF-18B955-CP` → 「操作」区。

刚训练出的版本是 **candidate（候选）**，页面会提示"当前配置作用于候选版本 vN，发布后生效"：

1. 「改 ROI」填 `0,0,280,400` → 保存 ROI（必须与 BMP 裁片 280×400 一致，否则推图报 `crop_roi_mismatch`）；
2. 「改阈值」填 `0.4,0.7` → 保存阈值（灰区演示用）。

> 之前只有在 assist/shadow 版本下才显示这两个输入；已改为候选版本也能配置。\n>\n> 页面「配置历史管理」按钮打开弹窗：ROI / 阈值两个页签、当前值标记、相对上一版差异、变更原因，以及「回滚」按钮。

### 4. 导出 ONNX 与冒烟

回到「训练与发布」→ 模型 S1 的候选版本行（如 v2）：

1. 点「导出 ONNX」→ 生成演示用亮度模型并自动挂载；
2. 冒烟试判一张 Sample1 图片。

### 5. 发布

同一行点「发布为生效」。这会把该候选版本设为 S1 的 assist 版本，编码绑定跟随生效。'

### 6. 工位推图

打开 `http://127.0.0.1:8100/panel`：

1. 编码填 `VPTXDF-18B955-CP` → 「换型」；
2. 选一张 `sample/Sample1/NG/*.bmp` → 「推图判定」；
3. 看结果：分数、label（ok/gray/ng）、decision（pass/block/review）。

演示导出的 ONNX 是"亮度均值"模型，分数只用于验证链路；真实模型接入后才有判别意义。

### 7. 复核

若结果进灰区/NG，侧栏「复核队列」→ 选理由 →「判为 OK/NG」→ 队列减少。

## 等价命令行（可选）

```powershell
# 重新导入（幂等，重复会跳过）
.\.venv\Scripts\python.exe scripts\import_samples.py --dir sample\Sample1 `
  --code VPTXDF-18B955-CP --family 排线口B --model S1 `
  --model-name "Sample1 排线口B" --dataset Sample1-full --freeze
```

## 已知限制

- BMP 支持刚刚补上：上传按 BMP 魔数存 `.bmp`，接口返回 `image/bmp`，浏览器可直接显示；
- 模拟训练不会读取图片内容，冻结校验和保证的是"数据集成员与版本可追溯"；
- 真实训练需要 GPU + anomalib，接入后同一套流程不变（训练页开始训练会走真实 backend）。
