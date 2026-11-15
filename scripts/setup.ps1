# 服务端一键安装（Windows）
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Venv "D:\aip\.venv"
#
# 只装服务端依赖，不装 torch/anomalib/CUDA。

param(
    [string]$Venv = ".venv",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== 检查 Python ==" -ForegroundColor Cyan
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "未找到 python。请先安装 Python 3.10+ 64 位，并勾选 Add to PATH。"
}
$ver = & python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
Write-Host "Python $ver"

$venvPath = if ([System.IO.Path]::IsPathRooted($Venv)) { $Venv } else { Join-Path $root $Venv }
$py = Join-Path $venvPath "Scripts\python.exe"

if ($Force -and (Test-Path $venvPath)) {
    Write-Host "== 删除旧虚拟环境 ==" -ForegroundColor Yellow
    Remove-Item $venvPath -Recurse -Force
}

if (-not (Test-Path $py)) {
    Write-Host "== 创建虚拟环境 $venvPath ==" -ForegroundColor Cyan
    & python -m venv $venvPath
}

Write-Host "== 安装依赖（仅服务端） ==" -ForegroundColor Cyan
& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $root "requirements-server.txt")
& $py -m pip install -e (Join-Path $root "aip") --no-deps

Write-Host "== 自检 ==" -ForegroundColor Cyan
& $py -c "import aip, fastapi, uvicorn, PIL, numpy; print('aip', aip.__version__ if hasattr(aip, '__version__') else 'ok')"

Write-Host ""
Write-Host "安装完成。启动：" -ForegroundColor Green
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\start.ps1"
Write-Host "  （默认监听 0.0.0.0:8100，局域网内其它电脑可访问）"
