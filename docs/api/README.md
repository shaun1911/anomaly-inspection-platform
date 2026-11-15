# API 使用说明

> 面向两类读者：**工位客户端（供应商）** 与 **内部集成/运维脚本**。
> 工位对接的完整流程与联调清单见 [`docs/vendor/station-client-integration.md`](../vendor/station-client-integration.md)；
> 全部端点清单见 [`endpoints.md`](endpoints.md)（自动生成），字段级细节以运行中的 `/docs`（Swagger UI）为准。

---

## 1. 基本信息

| 项 | 值 |
|---|---|
| Base URL | `http://<服务器>:8100` |
| 页面 | `/admin`（后台）、`/panel`（测试用面板，可在设置中关闭） |
| Swagger | `/docs`（**离线可用**：UI 资源随服务分发），机器可读 `/openapi.json` |
| 请求示例 | 写接口的请求体已内置示例，Swagger 里「Try it out」会预填；离线时看 [`endpoints.md`](endpoints.md) 与本文示例 |
| 编码 | UTF-8；JSON 接口 `Content-Type: application/json` |
| 时间 | 全部 **UTC**，格式 `2026-11-15T09:20:50.000Z` |

## 2. 认证

| 范围 | 方式 |
|---|---|
| `/infer`、`/station/*` | 设置里配了令牌后，必须带 `X-Station-Token: <令牌>`；未配置时可不带 |
| 其它管理接口 | **无认证**——服务只应部署在内网 |

令牌在「设置 → 接入」生成/复制；清空即关闭校验。

## 3. 通用约定

### 幂等

`POST /infer` 支持 `Idempotency-Key` 头（不传则用图片 sha256）。重复键返回同一 `job_id` 且 `duplicate: true`。

### 分页

列表接口用 `limit` + `offset`，返回：

```json
{"items": [...], "total": 123, "limit": 20, "offset": 0}
```

（部分列表接口直接返回数组，见 `endpoints.md` 与 Swagger。）

### 错误体

所有 4xx/5xx：

```json
{"error_code": "no_active_version", "message": "该模型没有可用版本", "action": "让技师发布版本"}
```

`action` 是给现场看的一步动作，不是堆栈。常见错误：

| HTTP | error_code | 含义 / 处理 |
|---|---|---|
| 400 | `missing_part_no` / `missing_batch_no` | 设置要求必须上报，客户端补字段 |
| 401 | `bad_station_token` | 令牌缺失或错误 |
| 403 | `not_in_shift` | 编码不在本班白名单 |
| 404 | `job_not_found` | 任务不存在（id 写错或已清理） |
| 409 | `no_active_version` / `no_config` | 模型没发布版本 / 没 ROI 配置 |
| 422 | `crop_roi_mismatch` | 裁片尺寸与 ROI 不一致（客户端需按 ROI 裁剪） |
| 422 | `unknown_code` | 编码未知或未绑定 |
| 503 | `maintenance` | 存储迁移中，暂停写入 |
| 503 | `model_load_failed` / `predictor_unavailable` | 模型加载失败/未装 onnxruntime |

### 判定与动作

结果里同时有 `result.label` 和 `decision`：

```json
{
  "result": {"score": 0.4683, "label": "gray"},
  "decision": {"action": "review", "human_required": true, "reason": "gray_review"}
}
```

**客户端只认 `decision.action`**：`pass` 放行、`block` 拦下、`review` 人工确认。
灰区走"队列"还是"拦停"由「设置 → 复核 → 灰区处理方式」决定，改规则不用改客户端。

## 4. 核心流程（工位）

```
① 换型   GET  /station/config?code=AB-1234-01     → 版本/ROI/阈值
② 推图   POST /infer?sync=1  (multipart)          → 200 完整结果
        或 POST /infer                            → 202 job_id
③ 处置   按 decision.action 放行 / 拦下 / 人工确认
④ 心跳   POST /station/heartbeat                  （建议 30–60s）
```

### 示例：同步推图

```bash
curl -X POST "http://127.0.0.1:8100/infer?sync=1" \
  -H "X-Station-Token: aip_xxx" \
  -F "code=AB-1234-01" \
  -F "station=S1" \
  -F "part_no=P-20261114-0001" \
  -F "batch_no=2026-11-B01" \
  -F "image=@crop.png"
```

```powershell
# Windows 现场常用
$form = @{
  code = "AB-1234-01"; station = "S1"
  part_no = "P-20261114-0001"; batch_no = "2026-11-B01"
  image = Get-Item ".\crop.png"
}
Invoke-RestMethod -Uri "http://127.0.0.1:8100/infer?sync=1" -Method Post -Form $form `
  -Headers @{ "X-Station-Token" = "aip_xxx" }
```

### 示例：异步 + 轮询

```bash
job=$(curl -s -X POST "http://127.0.0.1:8100/infer" -F "code=AB-1234-01" -F "image=@crop.png" | jq -r .job_id)
curl -s "http://127.0.0.1:8100/infer/$job"
```

### 示例：人工确认

```bash
curl -X POST "http://127.0.0.1:8100/review/1234/confirm" \
  -H "Content-Type: application/json" \
  -d '{"verdict":"ok","note":"划痕可接受"}'
```

## 5. 管理侧常用接口

| 用途 | 接口 |
|---|---|
| 今日统计 | `GET /api/stats/today` |
| 总览（待复核/站位） | `GET /api/overview` |
| 审计分页 | `GET /api/audit?limit=20&offset=0&action=&actor=&since=&until=` |
| 全局搜索 | `GET /api/search?q=AB` |
| 设置读写 | `GET /api/settings`、`POST /api/settings/bulk` |
| 模型缓存 | `GET /api/model-cache`、`POST /api/model-cache/{key}/unload` |
| 数据集冻结 | `POST /api/datasets/{id}/freeze` |
| 训练 | `POST /api/train`（需 `dataset_id` 已冻结） |
| 冒烟 | `POST /api/models/{id}/versions/{no}/smoke` |
| 导出 ONNX | `POST /api/models/{id}/versions/{no}/export` |

## 6. 边界与已知限制

- **管理接口无认证**：只能内网部署；对外必须加反代与鉴权。
- **预测器可能是假的**：版本未挂 ONNX 时走 `FakePredictor`，分数只用于链路验证。
- **模型加载是懒加载**：首次请求可能慢；缓存满返回 503，需要稍后重试。
- **API 未版本化**（当前 v0.1）：变更会记录在仓库提交与 [`endpoints.md`](endpoints.md) 中。
