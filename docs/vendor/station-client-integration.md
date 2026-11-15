# 工位客户端对接说明（供应商版）

> 读者：负责开发工位客户端的供应商工程师。
> 平台服务端地址、站位令牌由甲方在联调前提供。接口的权威定义以服务端 `/docs`（OpenAPI）为准，本文说明**流程与约束**。

---

## 1. 分工边界

| 角色 | 负责 |
|---|---|
| 工位客户端（供应商） | 扫码换型、按 ROI 裁图、上传判定、展示结论、NG/灰区提示人工复核、断网缓存与重放 |
| 平台服务端（甲方） | 型号解析、入口守门、判定、证据落库、复核队列、训练与版本、审计 |

客户端**不承担**：模型推理、版本选择、阈值判断、复核结论裁决。这些一律以服务端返回为准。

---

## 2. 一次完整循环

```
① 换型   GET  /station/config?code=<编码>
           ↓ 成功：拿到 model_version_id / roi_rect / roi_rev
② 拍照   本地按 roi_rect 裁剪（像素坐标，与 roo_rect 宽高一致）
③ 推图   POST /infer   (multipart: code, station, part_no, batch_no, image)
           ↓ 202 {job_id}
④ 取结果  GET  /infer/{job_id}   （1s 轮询，最多 30s）
           ↓ {result:{label,score}}  label ∈ ok / gray / ng
⑤ 处置   ok   → 放行
          ng   → 拦下，等人工
          gray → 提示"需人工确认"，等人工
⑥ 心跳   POST /station/heartbeat   （建议 10s 一次）
```

复核结论由服务端队列统一管理（`GET /review/pending?station=...` → `POST /review/{id}/confirm`），
客户端只做展示与录入入口，不自行判定。

---

## 3. 接口契约

### 3.1 通用

| 项 | 要求 |
|---|---|
| 协议 | HTTP/1.1，纯内网 |
| 鉴权 | `X-Station-Token: <令牌>`（甲方在「设置 → 接入」生成后提供；未配置时可省略） |
| 编码 | UTF-8；`Content-Type: multipart/form-data` |
| 超时 | 建议连接 5s、读 30s |
| 重试 | 见 §5，**必须带相同 `Idempotency-Key`** |

错误统一返回：

```json
{"error_code": "crop_too_small", "message": "裁片过小", "action": "检查镜头倍率或 ROI 设置"}
```

`action` 是给人看的下一步，客户端应优先展示它。

### 3.2 换型

`GET /station/config?code=AB-1234-01`

成功：

```json
{
  "code": "AB-1234-01",
  "model_version_id": 2,
  "version_no": 2,
  "roi_rect": [0, 0, 512, 512],
  "roi_rev": 1
}
```

| 状态码 | error_code | 客户端动作 |
|---|---|---|
| 401 | `bad_station_token` | 检查令牌配置，提示联系技师 |
| 403 | `not_in_shift` | 该编码不在本班白名单，提示换件或联系技师 |
| 409 | `no_binding` / `no_active_version` | 该编码无可用模型，提示联系技师 |
| 410 | `code_inactive` / `code_archived` | 编码已停用/归档，禁止换型 |
| 422 | `no_config` | 版本缺 ROI 配置，提示联系技师 |

### 3.3 推图

`POST /infer`

| 字段 | 必填 | 说明 |
|---|---|---|
| `code` | 是 | 产品编码 |
| `station` | 是 | 站位名（甲方约定的固定值） |
| `part_no` | 视配置 | 件号，追溯用；甲方可开启强制 |
| `batch_no` | 视配置 | 批次，按批统计用；甲方可开启强制；只允许字母数字与 `. _ - /` |
| `image` | 是 | 裁片，PNG/JPEG |

请求头：`Idempotency-Key: <每次上传唯一>`、`X-Station-Token`（如启用）。

成功：`202 {"job_id": 123, "status": "done", "model_version_id": 2, "roi_rev": 1}`

常见错误：

| 状态码 | error_code | 含义 | 客户端动作 |
|---|---|---|---|
| 401 | `bad_station_token` | 令牌错误 | 停止推图，报修 |
| 400 | `missing_part_no` / `missing_batch_no` | 缺少追溯字段 | 补采后重发 |
| 400 | `batch_invalid` | 批次字符不合法 | 纠正批次号 |
| 422 | `crop_too_small` | 裁片 < 32px | 检查镜头/ROI |
| 422 | `crop_too_dark` / `crop_too_bright` | 亮度越界 | 检查光源 |
| 422 | `crop_low_contrast` | 无纹理 | 检查对焦/镜头遮挡 |
| 422 | `crop_roi_mismatch` | 裁片宽高与 ROI 不一致 | **按 ROI 重新裁剪** |
| 403 | `not_in_shift` | 不在白名单 | 提示换件 |
| 409 | `no_binding` / `no_active_version` / `no_config` | 型号未就绪 | 提示联系技师 |
| 409 | `code_inactive` / `code_archived` | 编码不可用 | 禁止推图 |

### 3.4 取结果

`GET /infer/{job_id}`

```json
{
  "job_id": 123,
  "status": "done",
  "code": "AB-1234-01",
  "part_no": "P-0001",
  "batch_no": "B-2026-11-01",
  "result": {"id": 456, "score": 0.643, "label": "ng", "boxes": null}
}
```

- `label` 三态：`ok` 放行 / `gray` 人工确认 / `ng` 拦截；
- `status != done` 时继续轮询；超过 30s 未完成按"服务异常"处理；
- 展示裁片可用 `GET /results/{result_id}/image`。

### 3.5 复核

| 接口 | 用途 |
|---|---|
| `GET /review/pending?station=<站位>&limit=20` | 本单位待复核列表 |
| `POST /review/{result_id}/confirm` `{verdict, note?, confirmed_by}` | 提交人工结论 |
| `POST /review/{result_id}/claim` `{actor}` | 领取（多人协作时防重复） |

规则：**NG / 灰区必须人工确认**；客户端不得把 `gray` 直接当 `ok` 放行。

### 3.6 心跳

`POST /station/heartbeat` `{station, config_rev}`，建议 10s 一次。服务端据此展示站位在线状态。

---

## 4. 图像要求

| 项 | 要求 |
|---|---|
| 格式 | PNG 或 JPEG |
| 尺寸 | **必须等于 ROI 宽高**（服务端容差默认 ±8px，可配） |
| 最小边长 | 32px |
| 亮度均值 | 10–245（0–255） |
| 对比度（灰度标准差） | ≥ 5 |
| 文件大小 | ≤ 20MB |

裁剪坐标：`roi_rect = [x1, y1, x2, y2]`，原图像素坐标，左上角为原点。

---

## 5. 幂等、重试与离线

**幂等键规则**：每次"拍照上传"生成一个 UUID，**重试必须复用同一个键**。

```
上传 → 等待超时 → 用同一 Idempotency-Key 重发
     → 服务端返回相同 job_id（duplicate: true）→ 继续轮询
```

- 不要用"件号"当幂等键——同一件可以有多张图（多拍）；
- 同一张图重复上传也会被服务端按图片 sha256 去重。

**离线**：本地队列缓存待传任务，恢复后按顺序重放；服务端不保证顺序语义，
但幂等键保证不会重复落库。断网期间**不得**用本地规则替代判定结果放行。

---

## 6. 服务端强制 vs 客户端信任（控制边界）

| 控制点 | 谁保证 | 说明 |
|---|---|---|
| 编码是否存在/启用/归档 | **服务端** | 403/410 拦截 |
| 本班白名单 | **服务端** | 配置文件，换班可改 |
| 型号是否有模型与 ROI/阈值 | **服务端** | 409/422 |
| 裁片尺寸与 ROI 一致 | **服务端** | ±8px 容差，超差拒绝 |
| 图片可用性（小/暗/无纹理） | **服务端** | 入口守门 |
| 判定与阈值 | **服务端** | 客户端不得本地判定 |
| 复核状态机（领取/暂缓/确认） | **服务端** | 并发领取冲突返回 409 |
| 幂等与去重 | **服务端** | 键 + 图片 sha256 |
| 站位身份 | 共享令牌（`X-Station-Token`） | 见残余风险 |
| 裁剪框是否真的对应 ROI | **客户端** | 服务端只能校验尺寸，无法校验内容 |
| 件号/批次是否真实 | **客户端** | 建议甲方开启强制项，但仍依赖客户端如实上报 |

**残余风险（甲方已知并接受）**

1. **共享令牌不是按站位签发**：一个站位泄露令牌会影响全部。v1.1 计划按站位独立令牌；
2. **裁剪内容不可验证**：客户端可能裁错区域，服务端只能发现尺寸异常；
3. **件号/批次真实性**：服务端只做格式校验，重复/伪造需靠 MES 对账。

---

## 7. 联调与交付自测清单

供应商交付前必须自测通过：

- [ ] 用错误令牌调用 `/station/config` 与 `/infer` → 均返回 401；\n- [ ] 甲方在「设置 → 接入」点「生成」得到令牌，复制填入客户端后连通；
- [ ] 未开启强制项时，缺 `part_no`/`batch_no` 仍可推图；开启后返回 400；
- [ ] 推一张 8×8 图 → 422 `crop_too_small`，客户端展示 `action` 文案；
- [ ] 推一张宽高与 ROI 不符的图 → 422 `crop_roi_mismatch`；
- [ ] 同一 `Idempotency-Key` 连发两次 → 返回同一 `job_id`，且 `duplicate: true`；
- [ ] 轮询 1s 间隔、30s 超时逻辑生效；
- [ ] 断网 30s 后恢复 → 队列重放，无重复记录；
- [ ] `gray` 不会被客户端自动放行；
- [ ] 心跳 10s 一次，服务端"系统"页可见该站位在线。

---

## 8. 变更与版本

- 服务端接口向后兼容；新增字段不破坏客户端；
- 删除/改名字段会提前一个版本通知，并在 `/docs` 标注 deprecated；
- 客户端应在启动时拉取 `GET /health` 与 `/docs` 做连通性与版本确认。
