# AIP 工位客户端 · 规格（v1）

## 目标

给产线工位一个可独立运行的 C# 客户端：换型、取图/裁 ROI、调用服务端判定、显示结果、复核、误判上报，并可通过 PLC 触发相机/回写结果。

## 用户

工位操作员/技师。

## 范围

- 平台：Windows 10/11，WinForms + .NET Framework 4.8；
- 连接：服务器地址 + 站位令牌；
- 换型：`GET /station/config?code=`，展示模型版本、ROI、阈值；
- 取图：手动选图 + 监听文件夹；按 ROI 裁剪；
- PLC：Modbus RTU（串口）与 Siemens S7（Sharp7），信号地址可配；
- 触发：PLC Trigger 上升沿 → 等待相机写图 → 判定 → 写 Result/Done；
- 判定：`POST /infer?sync=1`，显示 ok/ng/gray、分数、decision；
- 复核：`POST /review/{id}/confirm`，写审计；
- 误判上报：`POST /station/misjudge`，进入后台「误判上报」队列；
- 心跳：10 秒一次 `/station/heartbeat`；
- 待复核数：15 秒刷新 `/review/pending`；
- 配置持久化：`station-config.json`、`plc-config.json`。

## 验收

1. 双击 exe 可启动，无 .NET SDK 依赖；
2. 填服务器/令牌/站位/编码，点「连接 / 换型」显示模型版本与 ROI；
3. 放入一张图，显示 OK/NG/灰区、分数、结果号；
4. 「复核判 OK/NG」后服务端结果更新、审计可查；
5. 「误判上报」提交后后台待处理数 +1；
6. PLC 接入后：Trigger 上升沿能触发取图，Result 写回正确结果码，Done 脉冲；
7. 服务端不可达时显示失败原因，不白屏；
8. 关闭重开保留配置。

## 不做（v1）

- 相机 SDK 直连（相机触发由 PLC/相机完成，客户端读文件）；
- 离线队列/离线推理；
- 配方号只支持数字映射到编码；PLC 字符串配方名、报警码表后续扩展；
- 自动更新、安装包签名；
- 多工位调度与权限体系（v1 使用共享站位令牌）。

## PLC 结果码

`0=OK`、`1=NG`、`2=灰区`、`3=错误`；地址与信号约定见 `README.md`。
