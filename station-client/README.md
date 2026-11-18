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

## 配置

首次运行后在 exe 同目录生成 `station-config.json`，保存服务器、令牌、站位、编码、批次、监听目录。

## 图像与 ROI

客户端按服务端 `/station/config` 返回的 `roi_rect` 从原图裁剪后上传；
ROI 必须在图片范围内，否则本地直接报错。上传 PNG。

## 构建

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

产物：`release\AipStation.exe`、`release\AipStation-client.zip`。

## 边界

- 第一版不接相机 SDK、不接 PLC、不做离线队列/离线推理；
- 推理、阈值、版本选择全部以服务端返回为准；
- 断网时判定失败会直接提示，不上传缓存。
