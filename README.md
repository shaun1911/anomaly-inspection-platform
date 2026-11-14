# AIP · 工业异常检测平台

面向单条产线的表面缺陷检测平台：**中心推理 + 判例沉淀 + 抽检验收**，Windows 单机部署，纯内网运行。

> 当前处于 **v1 开发中**：接口与页面可跑通，预测器为假实现（确定性分数），训练为模拟器。
> 设计冻结与验收标准见 [`docs/designs/工业表面缺陷检测平台-v1.md`](docs/designs/工业表面缺陷检测平台-v1.md)。

---

## 现在能跑什么

| 能力 | 状态 |
|---|---|
| 编码 / 模型 / 版本 / 绑定 / ROI / 阈值 CRUD | ✅ 含停用、归档、解绑 |
| 推理链路：入口守门 → 三态判定 → 证据落库 → 裁片查看 | ✅ 假预测器 |
| 复核队列：按件聚合、领取、暂缓回收站、筛选、参考样例 | ✅ 键盘可操作 |
| 判例库：去重、冲突检测、软删、来源回指、按件聚合、分页、导出 | ✅ |
| 数据集：族/模型快照、冻结、校验和、导出 | ✅ |
| 训练与发布：训练必须引用冻结数据集 → 候选 → 发布 → 回滚 | ✅ 模拟训练器 |
| 设置：14 项运行时配置，守门阈值已生效 | ✅ |
| 抽检批次：盲判（不泄底）+ 三方签字 + 漏检/过杀指标 | ✅ |
| 五步新建向导 | ⬜ 待做 |

测试：`pytest` 136 项全绿。

---

## 快速开始

```powershell
# 1) 依赖（本机已建 .venv；缺失时重建）
python -m venv .venv --system-site-packages
.\.venv\Scripts\python.exe -m pip install -e .\aip

# 2) 起开发服务（自动迁移数据库）
.\.venv\Scripts\python.exe scripts\dev_server.py --port 8100

# 3) 打开界面
#    服务端：http://127.0.0.1:8100/admin
#    工位面板：http://127.0.0.1:8100/panel
#    接口文档：http://127.0.0.1:8100/docs
```

演示数据：

```powershell
.\.venv\Scripts\python.exe scripts\seed_dev.py        # 编码/模型/版本/绑定 + 5 条判定
.\.venv\Scripts\python.exe scripts\seed_cases.py      # ok/ng 判例，供参考样例
```

---

## 目录结构

```
aip/src/aip/            服务端（store 迁移、cases、importer、settings、api/*）
aip/web/                工位面板与后台页面（单文件，无构建）
aip/src/aip/db/migrations/   SQL 迁移（可升可降）
scripts/                开发服务、演示数据、回填工具
tests/                  pytest（107 项）
docs/designs/           设计文档与页面设计
docs/review/            四轮金鱼评审记录与索引
docs/tasks/             W1–W14 任务拆解
docs/report/shots/      页面截图
configs/                白名单等启动级配置
```

---

## 技术栈与约束

- Python 3.12（开发机 3.13 可跑）、FastAPI、SQLite（WAL + 短事务）
- 生产推理用 ONNX，训练侧 torch + anomalib
- **Windows 11 单机部署**，NSSM 托管服务，不用 Docker / WSL
- 纯内网：依赖离线 wheelhouse，不访问公网

---

## 不放进仓库的东西

`.gitignore` 已挡掉：虚拟环境、模型权重、运行时数据（`data/`）、演示视频与音频、打包产物、外部的 anomalib 克隆，以及本地 `.internal/`（决策稿、评审记录、旧版归档）。

需要 anomalib 时自行获取：

```powershell
git clone https://github.com/open-edge-platform/anomalib
```

---

## 阅读顺序

1. [`docs/designs/工业表面缺陷检测平台-v1.md`](docs/designs/工业表面缺陷检测平台-v1.md) — 范围、门槛、验收协议
2. [`docs/designs/page-design.md`](docs/designs/page-design.md) — 页面为何这样分
3. [`docs/tasks/w1-w14.md`](docs/tasks/w1-w14.md) — 任务与人日

---

## 许可

[Apache License 2.0](LICENSE)。可商用、可修改、可再分发，需保留版权与许可声明；附带专利授权。
