# aip — 工业表面缺陷检测平台（服务端）

> 面向单条产线的中心推理服务：编码/模型/版本管理、推理与复核、判例沉淀、数据集冻结、训练发布、盲判抽检。
> 运行平台 Windows 11 单机，纯内网。设计见 [`docs/designs/data-logic.md`](../docs/designs/data-logic.md) 与 [v1 设计](../docs/designs/工业表面缺陷检测平台-v1.md)。

## 模块地图

| 模块 | 职责 |
|---|---|
| `aip/store.py` | 连接（WAL、外键、busy_timeout）、`tx()` 事务、迁移升降级 |
| `aip/db/migrations/` | `NNNN_name.sql` 与 `NNNN_down.sql`，成对存在 |
| `aip/cases.py` | 判例：sha256/件号去重、冲突标记、来源回指、软删 |
| `aip/datasets.py` | 数据集：族推导、加入判例、冻结与校验和 |
| `aip/dataset_audit.py` | 冻结快照与事后核对（改判/换图/归档/删除） |
| `aip/backfill.py` | 存量批次回填（daily/shift/csv，留 `batch_source`） |
| `aip/retention.py` | 证据保留：判例与待复核永不删，其余按保留期 |
| `aip/settings.py` | 运行时配置：声明式规格（类型/范围/默认）+ 批量保存 |
| `aip/audit.py` | 审计写入（失败不阻断业务） |
| `aip/inference/service.py` | 预测器接口、三态判定、入口守门 |
| `aip/api/*` | HTTP 路由，按领域拆文件 |

## 接口分组

| 前缀 | 内容 |
|---|---|
| `/api/codes` `/api/models` `/api/bindings` | 编码、模型、版本、绑定、ROI、阈值 |
| `/api/families` | 族与"族 → 模型"一致性 |
| `/infer` `/results` `/review` | 推理、结果、复核队列（按件聚合/领取/暂缓） |
| `/api/cases` | 判例（分页、冲突、上传、导出） |
| `/api/datasets` | 数据集（加入/冻结/核对/导出） |
| `/api/train` | 训练（必须引用冻结数据集）、冒烟、发布、回滚 |
| `/api/blind` | 抽检批次（盲判不泄底、三方签字、指标冻结） |
| `/api/settings` | 运行时配置（含 `/bulk` 原子批量保存） |
| `/api/maintenance/retention` | 存储清理（预览/执行） |
| `/station/*` | 工位换型与心跳（白名单、归档/停用拦截） |

## 迁移规则

1. 每个 `NNNN_name.sql` **必须**有配套 `NNNN_down.sql`；
2. 只加不删优先（`ALTER TABLE ... ADD COLUMN`），必须删时在 down 里恢复；
3. 迁移要能在空库与已有库上都跑通；
4. 演练测试 `tests/test_migrations_drill.py` 会做 **升 → 全降 → 再升**，down 写坏即红。

新增一版：

```powershell
# aip/src/aip/db/migrations/0013_xxx.sql
# aip/src/aip/db/migrations/0013_down.sql
.\.venv\Scripts\python.exe -m pytest tests/test_migrations.py tests/test_migrations_drill.py -q
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q          # 全量
```

重点测试：

| 文件 | 守护什么 |
|---|---|
| `test_migrations_drill.py` | 迁移可回滚 |
| `test_data_logic_invariants.py` | 四层不变量 + 全链追溯（件号 → 族 → 版本 → 判例 → 数据集 → 训练） |
| `test_api_review_queue.py` | 按件聚合、领取冲突、暂缓回收 |
| `test_api_datasets.py` / `test_api_dataset_audit.py` | 冻结不可变、校验和、事后核对 |
| `test_api_blind.py` | 盲判不泄底、签字门槛、指标口径 |
| `test_retention.py` | 判例与待复核证据不被误删 |

'## 页面冒烟（可选）

```powershell
# 起 Edge 调试端口
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new --remote-debugging-port=9223 --user-data-dir=$env:TEMP\edge-cdp
# 另一个窗口
node scripts/ui_smoke.mjs
```

逐个打开 10 个 hash 路由，检查渲染文本、`加载失败` 与 JS 异常；任一路由异常退出码非 0。
这是补 JS 层缺口的：pytest 只做静态检查，语法/声明对但运行时报错只有浏览器能发现。

## 已知的"假"部分'

- `FakePredictor`：按图片 sha256 生成确定性分数，仅打通链路；
- `routes_train._fake_metrics`：确定性假指标，接 anomalib 时替换这一段；
- 真实训练需要 Gate 0 数据（样品、基线导出、驱动 ≥580），未接入前指标不代表模型能力。

## 本地开发

```powershell
.\.venv\Scripts\python.exe scripts\dev_server.py --port 8100
.\.venv\Scripts\python.exe scripts\seed_dev.py        # 演示数据
```

脚本：`seed_*`（演示）、`backfill_batch.py`（批次回填）、`backfill_case_sha.py`（判例补 sha）、
`backfill_dataset_snapshot.py`（数据集补快照）、`retention.py`（清理）。

## 数据目录（不入库）

```
data/aip.db          主库（WAL）
data/crops/          判定裁片（按 sha256）
data/cases/          判例上传图
data/smoke/          冒烟图
```
