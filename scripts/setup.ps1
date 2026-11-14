# One-shot environment setup for a fresh machine (Windows / PowerShell).
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Strategy: reuse the already-validated torch install of the base interpreter
# (venv --system-site-packages), then install only what anomalib + aip need.
# This avoids pip replacing torch+cu130 with a CPU wheel.
param(
    [string]$Python = "python",
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Recreate -and (Test-Path ".venv")) {
    Write-Host "Removing existing .venv" -ForegroundColor Yellow
    Remove-Item -Recurse -Force ".venv"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv (system-site-packages)" -ForegroundColor Green
    & $Python -m venv .venv --system-site-packages
}

$py = Join-Path $root ".venv\Scripts\python.exe"
& $py -m pip install --disable-pip-version-check -q --upgrade pip

Write-Host "Installing anomalib (editable, no deps)" -ForegroundColor Green
& $py -m pip install --disable-pip-version-check -q --no-deps -e .\anomalib

Write-Host "Installing runtime dependencies" -ForegroundColor Green
& $py -m pip install --disable-pip-version-check -q `
    "timm" "einops" "freia>=0.2" "kornia>=0.6.6" "omegaconf>=2.1.1" `
    "jsonargparse[signatures]>=4.27.7,<4.47.0" "rich>=13.5.2" "docstring_parser" "rich_argparse" `
    "imagecodecs" "tifffile" "platformdirs>=4.9.4" `
    "onnx" "onnxscript" "onnxruntime" "fastapi" "uvicorn[standard]" "python-multipart" "pytest"

Write-Host "Installing aip (editable)" -ForegroundColor Green
& $py -m pip install --disable-pip-version-check -q --no-deps -e .\aip

Write-Host ""
& (Join-Path $root ".venv\Scripts\aip.exe") doctor
Write-Host "`nNext: .\.venv\Scripts\aip.exe demo ; .\.venv\Scripts\aip.exe train -c configs\demo_patchcore.yaml" -ForegroundColor Green
