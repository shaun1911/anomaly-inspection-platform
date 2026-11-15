# API 端点清单（自动生成）

> 由 `scripts/gen_api_doc.py` 从 OpenAPI 生成，不要手改。
> 字段级说明见运行中的 `/docs`（Swagger UI）或 `/openapi.json`。

## 推理（工位客户端）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/infer/{job_id}` | 查询推理任务与结果（含 decision） |
| POST | `/infer` | 推图判定（默认异步 202；`?sync=1` 同步 200 返回结果） |
| POST | `/infer/feedback` | 提交人工复核反馈 |

## 站位配置

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/station/config` | 换型：取编码对应的模型版本/ROI/阈值 |
| POST | `/station/heartbeat` | 站位心跳 |

## 结果与复核确认

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/results` | 查询 结果 |
| GET | `/results/{result_id}` | 查询 结果 |
| GET | `/results/{result_id}/image` | 查询 结果 / 图片 |
| GET | `/results/{result_id}/references` | 查询 结果 / 参考图 |

## 复核队列

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/review/pending` | 工位待复核列表 |
| GET | `/review/queue` | 复核队列（可按编码/结果/编码族/批次分组） |
| GET | `/review/skipped` | 查询 复核 / skipped |
| POST | `/review/claim-batch` | 提交 复核 / claim-batch |
| POST | `/review/skip-batch` | 提交 复核 / skip-batch |
| POST | `/review/{result_id}/claim` | 领取复核项 |
| POST | `/review/{result_id}/confirm` | 确认复核结论 |
| POST | `/review/{result_id}/release` | 提交 复核 / 释放 |
| POST | `/review/{result_id}/restore` | 提交 复核 / 还原 |
| POST | `/review/{result_id}/skip` | 提交 复核 / 暂缓 |

## 编码 / 模型 / 绑定

| 方法 | 路径 | 说明 |
|---|---|---|
| DELETE | `/api/codes/{code}` | 删除 编码 |
| GET | `/api/codes` | 查询 编码 |
| GET | `/api/codes/{code}/detail` | 查询 编码 / detail |
| GET | `/api/codes/{code}/timeline` | 查询 编码 / timeline |
| POST | `/api/codes` | 提交 编码 |
| POST | `/api/codes/{code}/active` | 提交 编码 / active |
| POST | `/api/codes/{code}/archive` | 提交 编码 / 归档 |
| POST | `/api/codes/{code}/restore` | 提交 编码 / 还原 |
| PUT | `/api/codes/{code}` | 更新 编码 |

## 模型版本与发布

| 方法 | 路径 | 说明 |
|---|---|---|
| DELETE | `/api/models/{model_id}` | 删除 模型 |
| GET | `/api/models` | 查询 模型 |
| POST | `/api/models` | 提交 模型 |
| POST | `/api/models/{model_id}/archive` | 提交 模型 / 归档 |
| POST | `/api/models/{model_id}/rollback` | 提交 模型 / 回滚 |
| POST | `/api/models/{model_id}/versions` | 提交 模型 / 版本 |
| POST | `/api/models/{model_id}/versions/{version_no}/export` | 提交 版本 / 导出 |
| POST | `/api/models/{model_id}/versions/{version_no}/smoke` | 提交 版本 / 冒烟 |
| PUT | `/api/models/{model_id}` | 更新 模型 |
| PUT | `/api/models/{model_id}/versions/{version_no}/onnx` | 更新 版本 / ONNX |
| PUT | `/api/models/{model_id}/versions/{version_no}/status` | 更新 版本 / status |

## 数据集

| 方法 | 路径 | 说明 |
|---|---|---|
| DELETE | `/api/datasets/{dataset_id}/items/{case_id}` | 删除 数据集 / 成员 |
| GET | `/api/datasets` | 查询 数据集 |
| GET | `/api/datasets/{dataset_id}` | 查询 数据集 |
| GET | `/api/datasets/{dataset_id}/audit` | 查询 数据集 / 审计 |
| GET | `/api/datasets/{dataset_id}/export.csv` | 查询 数据集 / export.csv |
| POST | `/api/datasets` | 提交 数据集 |
| POST | `/api/datasets/{dataset_id}/freeze` | 提交 数据集 / 冻结 |
| POST | `/api/datasets/{dataset_id}/items` | 提交 数据集 / 成员 |

## 训练

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/train` | 查询 训练 |
| POST | `/api/train` | 用冻结数据集启动训练 |
| POST | `/api/train/{job_id}/cancel` | 提交 训练 / cancel |

## 盲判抽检

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/blind/batches` | 查询 抽检 / batches |
| GET | `/api/blind/batches/{batch_id}` | 查询 抽检 / batches |
| GET | `/api/blind/items/{item_id}/image` | 查询 成员 / 图片 |
| POST | `/api/blind/batches` | 提交 抽检 / batches |
| POST | `/api/blind/batches/{batch_id}/close` | 提交 batches / close |
| POST | `/api/blind/items/{item_id}/judge` | 提交 成员 / judge |

## 判例库

| 方法 | 路径 | 说明 |
|---|---|---|
| DELETE | `/api/cases/{case_id}` | 删除 判例 |
| GET | `/api/cases` | 查询 判例 |
| GET | `/api/cases/conflicts` | 查询 判例 / conflicts |
| GET | `/api/cases/page` | 查询 判例 / page |
| GET | `/api/cases/{case_id}/image` | 查询 判例 / 图片 |
| POST | `/api/cases` | 提交 判例 |
| POST | `/api/cases/upload` | 提交 判例 / upload |
| POST | `/api/cases/{case_id}/archive` | 提交 判例 / 归档 |
| POST | `/api/cases/{case_id}/restore` | 提交 判例 / 还原 |
| PUT | `/api/cases/{case_id}` | 更新 判例 |

## 设置

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/settings` | 读取全部设置项 |
| POST | `/api/settings/bulk` | 批量保存设置（一次事务） |
| PUT | `/api/settings/{key}` | 更新 设置 |

## 维护（迁移/备份/审计归档）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/maintenance/audit` | 查询 维护 / 审计 |
| GET | `/api/maintenance/storage` | 查询 维护 / 存储 |
| POST | `/api/maintenance/audit/archive` | 提交 审计 / 归档 |
| POST | `/api/maintenance/audit/import` | 提交 审计 / 导入 |
| POST | `/api/maintenance/backup` | 提交 维护 / 备份 |
| POST | `/api/maintenance/restore` | 提交 维护 / 还原 |
| POST | `/api/maintenance/retention` | 提交 维护 / retention |
| POST | `/api/maintenance/storage/move` | 提交 存储 / 迁移 |

## 审计日志

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/audit` | 审计日志分页查询（动作/人/时间） |
| GET | `/api/audit/recent` | 查询 审计 / recent |

## 统计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/stats/today` | 查询 统计 / today |

## 监控指标

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/metrics` | 查询 指标 |

## 全局搜索

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/search` | 全局搜索（编码/件号/模型） |

## 健康检查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查（服务/数据库/队列） |

## 其他管理接口

| 方法 | 路径 | 说明 |
|---|---|---|
| DELETE | `/api/bindings/{binding_id}` | 删除 绑定 |
| GET | `/api/bindings` | 查询 绑定 |
| GET | `/api/export/dataset` | 查询 导出 / dataset |
| GET | `/api/families` | 查询 产品族 |
| GET | `/api/families/{family_id}/models` | 查询 产品族 / 模型 |
| GET | `/api/model-cache` | 查询 model-cache |
| GET | `/api/overview` | 查询 overview |
| GET | `/api/stations` | 查询 站位 |
| POST | `/api/bindings` | 提交 绑定 |
| POST | `/api/configs` | 提交 ROI 配置 |
| POST | `/api/families` | 提交 产品族 |
| POST | `/api/model-cache/{key}/unload` | 提交 model-cache / unload |
| POST | `/api/thresholds` | 提交 阈值 |
