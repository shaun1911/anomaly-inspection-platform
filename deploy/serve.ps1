# Native Windows service launcher (no Docker).
#
#   .\deploy\serve.ps1 -Bundle artifacts\demo-metal -Backend torch -Port 8000
#
# To run as a real Windows service, wrap this in NSSM:
#   nssm install AIP "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File C:\aip\deploy\serve.ps1"
#   nssm set AIP AppDirectory C:\aip
#   nssm start AIP
param(
    [string]$Bundle = "artifacts/demo-metal",
    [ValidateSet("auto", "onnx", "torch")][string]$Backend = "torch",
    [ValidateSet("auto", "cuda", "cpu")][string]$Device = "auto",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8000,
    [int]$MaxBatch = 8
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\aip.exe"
if (-not (Test-Path $python)) {
    throw "aip.exe not found at $python - run scripts\setup.ps1 first"
}
if (-not (Test-Path (Join-Path $root $Bundle))) {
    throw "bundle not found: $Bundle"
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:AIP_BUNDLE = (Resolve-Path $Bundle).Path
$env:AIP_BACKEND = $Backend
$env:AIP_DEVICE = $Device
$env:AIP_MAX_BATCH = "$MaxBatch"

Write-Host "AIP serving $Bundle  backend=$Backend device=$Device  http://${BindHost}:$Port" -ForegroundColor Green
& $python serve --bundle $Bundle --backend $Backend --device $Device --host $BindHost --port $Port
