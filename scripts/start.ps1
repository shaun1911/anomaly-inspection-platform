# 启动服务（Windows）
#
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
#   ... -Port 8100 -DataDir "D:\aip-data"
#   ... -Bind 127.0.0.1        # 仅本机访问
#
# 默认绑定 0.0.0.0，局域网内其它电脑可直接访问 http://<本机IP>:8100/panel

param(
    [string]$Bind = "0.0.0.0",
    [int]$Port = 8100,
    [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw "未找到虚拟环境。先运行：powershell -ExecutionPolicy Bypass -File scripts\setup.ps1"
}

$env:PYTHONUTF8 = "1"
$args = @("scripts\dev_server.py", "--host", $Bind, "--port", "$Port")
if ($DataDir -ne "") {
    $args += @("--data-dir", $DataDir)
}

Write-Host "服务地址：http://$Bind`:$Port" -ForegroundColor Green
Write-Host "工位面板：http://$Bind`:$Port/panel"
Write-Host "管理后台：http://$Bind`:$Port/admin"
Write-Host ""

& $py @args
