# AIP 工位客户端（WinForms / .NET Framework 4.8）

## 运行

1. 双击 `AipStation.exe`（Windows 10/11 自带 .NET Framework 4.8，无需安装运行时）。
2. 顶部填：
   - 服务器：`http://<服务端IP>:8100`
   - 令牌：管理端「设置 → 接入」生成
   - 站位：如 `S1`
   - 编码：如 `VPTXDF-18B955-CP`
   - 批次：留空自动用 `B-yyyyMMdd`
3. 点「连接 / 换型」，状态栏显示已连接、模型版本、ROI、阈值。
4. 取图：
   - 「打开图片」手动选一张；
   - 或「选择监听目录」后点「监听目录」，新图落盘自动判定。
5. 结果显示 OK / NG / 灰区、分数、决策。
6. 「复核判 OK / NG」：直接调服务端复核（写审计）。
7. 「误判上报」：选现场结论、理由、备注，提交到后台「误判上报」队列。

## PLC 接入

支持两种协议（`PLC 设置` 里切换）：

| 协议 | 说明 |
|---|---|
| **Modbus RTU** | 串口：COM、波特率、校验、数据位、停止位、从站号 |
| **Siemens S7** | 网口：IP、Rack、Slot（Sharp7，MIT） |

### 信号约定

| 信号 | 方向 | 地址示例（Modbus / S7） |
|---|---|---|
| Ready | 客户端→PLC | 线圈 0 / `DB1.DBX0.0` |
| Trigger | PLC→客户端 | 线圈 1 / `DB1.DBX0.1` |
| Busy | 客户端→PLC | 线圈 2 / `DB1.DBX0.2` |
| Done | 客户端→PLC | 线圈 3 / `DB1.DBX0.3` |
| Error | 客户端→PLC | 线圈 4 / `DB1.DBX0.4` |
| Result | 客户端→PLC | 保持寄存器 100 / `DB1.DBW2` |

结果码：`0=OK`、`1=NG`、`2=灰区`、`3=错误`。

### 触发流程

```
PLC Trigger 上升沿
  → 客户端 Ready=false, Busy=true
  → 等待相机把新图写入监听目录（超时 CameraTimeoutMs）
  → 裁 ROI、推图判定
  → 写 Result 结果码
  → Done 脉冲 300ms
  → Busy=false, Ready=true
```

相机触发由 PLC/相机硬件完成；客户端负责“触发后取图 + 判定 + 回写结果”。

### 地址格式

- Modbus RTU：线圈/保持寄存器均填十进制地址（0 基）；
- S7：`DB1.DBX0.0`（位）、`DB1.DBW2`（字）、`M0.0`、`I0.0`、`Q0.0`。

### 限制

- 未做 Ack 确认信号、配方号下发、报警复位；需要时在信号表上加；
- 未在真实 PLC 上联调（开发环境无串口/PLC），上线前必须做信号级测试；
- 共享令牌、配置文件明文保存。

## 配置

首次运行后在 exe 同目录生成：

- `station-config.json`：服务器、令牌、站位、编码、批次、监听目录；
- `plc-config.json`：协议、串口/S7 参数、信号地址。

## 构建

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

产物：`release\AipStation.exe`、`Sharp7.dll`、`release\AipStation-client.zip`。

## 边界

- 第一版不接相机 SDK（相机写文件到监听目录）、不做离线队列/离线推理；
- 推理、阈值、版本选择全部以服务端返回为准；
- Sharp7 为 MIT 许可，见 `vendor\Sharp7-LICENSE.txt`。
