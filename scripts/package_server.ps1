# 打一个"拷过去就能装"的服务端包（不含 .git/.venv/数据/训练产物/演示媒体）
#
#   powershell -ExecutionPolicy Bypass -File scripts\package_server.ps1
#   ... -OutDir "D:\deliver"

param(
    [string]$OutDir = "out"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$stage = Join-Path $env:TEMP "aip-pkg-$stamp"
$outPath = if ([System.IO.Path]::IsPathRooted($OutDir)) { $OutDir } else { Join-Path $root $OutDir }
New-Item -ItemType Directory -Force -Path $outPath | Out-Null

$excludeDirs = @(
    ".git", ".venv", "data", "out", ".tools", "anomalib", "downloads",
    "node_modules", "runs", "artifacts", "datasets", "logs", "package",
    "docs\report\video", ".internal", ".pytest_cache", ".ruff_cache"
) | ForEach-Object { Join-Path $root $_ }

Write-Host "== 复制到暂存目录（排除运行时与媒体） ==" -ForegroundColor Cyan
$roboArgs = @($root, $stage, "/E", "/NFL", "/NDL", "/NJH", "/NJS")
$roboArgs += "/XD"
$roboArgs += $excludeDirs
$roboArgs += "/XF"
$roboArgs += @("*.pyc", "*.pyo", "*.wav", "*.mp4", "*.mp3", "*.silk", "*.avi", "*.mov", "App*.png")
robocopy @roboArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy 失败: $LASTEXITCODE" }

# 二次确认：暂存目录里不应出现运行时数据
foreach ($forbidden in @(".venv", "data", "runs", "artifacts", "datasets")) {
    if (Test-Path (Join-Path $stage $forbidden)) {
        throw "暂存目录混入了 $forbidden，检查排除规则"
    }
}

$zip = Join-Path $outPath ("aip-server-$stamp.zip")
Write-Host "== 打包 $zip ==" -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item $stage -Recurse -Force

$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "已生成：$zip（$size MB）" -ForegroundColor Green
Write-Host "目标电脑解压后执行："
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\start.ps1"
