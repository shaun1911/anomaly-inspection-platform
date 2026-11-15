# Windows 部署说明（服务端）

> 目标：把服务端搬到一个新的 Windows 电脑，**不装 CUDA、不装 torch**，只跑服务。
> 适用：生产前置机、演示机、备用机。训练仍需要 GPU 机器（另装训练依赖）。

---

## 1. 准备

| 项 | 要求 |
|---|---|
| 系统 | Windows 10/11 64 位 |
| Python | **3.10+ 64 位**（python.org 安装包，勾选 Add to PATH） |
| 磁盘 | 服务端代码 + 依赖约 300 MB；数据目录另算 |
| 网络 | 与工位客户端同一内网 |

验证 Python：

```powershell
python --version
```

## 2. 拿到代码

两种方式任选：

```powershell
# A. 有 git
git clone https://github.com/shaun1911/anomaly-inspection-platform.git aip
cd aip

# B. 无 git：从 GitHub 下载 zip 解压到任意目录
```

## 3. 安装（一条命令）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

它会：创建 `.venv` → 安装 `requirements-server.txt`（FastAPI/uvicorn/Pillow/numpy）→
`pip install -e aip --no-deps` → 自检导入。

> 不装 torch / anomalib / onnxruntime / opencv —— 这些只在训练模块用。

**离线安装**（目标机不能上外网）：

```powershell
# 在有网机器上（同 Python 版本、同架构）
pip download -r requirements-server.txt -d wheelhouse
# 把 wheelhouse 一起拷到目标机，然后
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse -r requirements-server.txt
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse -e .\aip --no-deps
```

## 4. 启动

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

默认监听 **0.0.0.0:8100**，输出：

```
工位面板：http://0.0.0.0:8100/panel
管理后台：http://0.0.0.0:8100/admin
```

自定义端口/数据目录：

```powershell
... -Port 8100 -DataDir "D:\aip-data"
```

只允许本机访问：`-Bind 127.0.0.1`。

'## 4.1 推理运行时（可选，但接真模型需要）

- **CPU 推理**：`requirements-server.txt` 已包含 `onnxruntime`，安装时自动装好，无需额外操作。
- **GPU 推理**（大体积，按需自行安装）：

```powershell
.\.venv\Scripts\python.exe -m pip install onnxruntime-gpu
```

CUDA 与 cuDNN 不随项目分发，需按 NVIDIA 官方文档自行安装匹配版本（GPU 显存建议 ≥8 GB）。

'**导出与挂载**：

- 演示/链路验证：训练与发布 → 版本行 → **「导出 ONNX」**（服务端生成一个真实的亮度均值图，落 `data/models/<model>-v<ver>.onnx` 并自动挂载）；
- 真实模型：在训练机用 anomalib 导出后，版本行 → **「挂 ONNX」** → 填绝对路径。

> 服务端导出演示模型需要可选依赖：`pip install -r requirements-export.txt`（含 `onnx`）。

**把模型挂到版本**：训练与发布 → 版本行 → 「挂 ONNX」→ 填导出文件绝对路径；'
工位推图时若该版本有 ONNX 路径则走 ONNX Runtime，否则退回演示用假预测器。

相关设置（设置 → 接入）：

| 项 | 说明 |
|---|---|
| `infer.onnx_input_range` | `pm1`（[-1,1]）或 `unit`（[0,1]），需与导出时预处理一致 |
| `infer.onnx_aggregate` | `max` 取异常峰值 / `mean` 取均值 |

> 不同 anomalib 导出的输出版本差异较大，首次接入须用真实模型冒烟验证分数尺度，
> 不要直接拿演示阈值上线。

## 5. 让局域网其它电脑访问'

需要放行防火墙（**管理员** PowerShell，一次即可）：

```powershell
New-NetFirewallRule -DisplayName "AIP 8100" -Direction Inbound -Protocol TCP -LocalPort 8100 -Action Allow
```

查本机 IP：

```powershell
ipconfig | findstr IPv4
```

工位客户端配置：

> `/panel` 是测试页，生产建议在「设置 → 接入 → 开放工位面板」关闭，接口不受影响。
> 节拍紧的客户端用 `POST /infer?sync=1`，一次拿到 label 与 score。


```
服务地址   http://<本机IP>:8100
站位令牌   管理后台 → 设置 → 接入 → 生成/复制
```

## 6. 开机自启（二选一）

**A. 任务计划（推荐，不装额外软件）**

任务计划程序 → 创建任务 → 触发器"登录时" → 操作：

```
程序：powershell.exe
参数：-ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\aip\scripts\start.ps1"
起始于：C:\aip
```

**B. NSSM 注册为服务**

```powershell
nssm install AIP "C:\aip\.venv\Scripts\python.exe" "C:\aip\scripts\dev_server.py --host 0.0.0.0 --port 8100"
nssm set AIP AppDirectory "C:\aip"
nssm start AIP
```

## 7. 数据与备份

- 数据默认在 `data/`（DB + 裁片 + 判例图 + 冒烟图）；
- 换盘：管理后台 → 设置 → 存储 → 预检 → 执行迁移 → 用新目录重启；
- 备份：设置 → 存储 → 立即备份（生成 zip，含 manifest 与校验）；
- 还原：设置 → 存储 → 还原到**空目录**，再用该目录重启。

从旧机器搬家：

1. 旧机器备份出 zip；
2. 新机器部署代码 + 安装；
3. 新机器"还原"到 `D:\aip-data`；
4. `start.ps1 -DataDir "D:\aip-data"`。

## 8. 升级与回滚

```powershell
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements-server.txt
# 重启服务；启动时自动执行数据库迁移
```

回滚代码：

```powershell
git checkout <上一个提交或 tag>
# 若迁移需要回退（一般不必），在离线数据库上执行 down 脚本
```

升级前先做一次整目录备份——**数据比代码重要**。

## 9. 验证部署是否成功

```powershell
# 本机
Invoke-RestMethod http://127.0.0.1:8100/health
# 从另一台电脑
Invoke-RestMethod http://<本机IP>:8100/health
```

期望：`status=ok`、`db=ok`。

页面自检：`/panel`（工位）与 `/admin`（后台）都能打开，后台"工作台"能看到服务与资源。

## 10. 常见问题

| 现象 | 处理 |
|---|---|
| 端口被占用 | `netstat -ano | findstr :8100` 找 PID 结束，或换 `-Port` |
| 其它电脑打不开 | 检查防火墙规则、`-Bind` 是否为 `0.0.0.0`、是否同网段 |
| 提示找不到 python | 重装 Python 勾选 Add to PATH，或改用绝对路径 |
| 页面白屏 | 看是否有"加载失败"提示；升级后强制刷新（Ctrl+F5） |
| 数据在旧盘 | 用备份/还原或存储迁移，不要手工只拷 `aip.db` |

---

## 附：口径

- 服务端**不需要 GPU**；GPU 只影响训练与真实 ONNX 推理（接入后）。
- 当前预测器为 `FakePredictor`（演示用），部署后"能跑通流程"，但指标不代表模型能力。
- 后台没有登录系统，**只能部署在内网**；工位令牌在"设置 → 接入"里生成。
