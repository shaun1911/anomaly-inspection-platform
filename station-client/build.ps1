param(
    [string]$OutDir = "$PSScriptRoot\release"
)

$ErrorActionPreference = "Stop"
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { throw "找不到 .NET Framework 4.8 编译器：$csc" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$refs = @(
    "System.dll",
    "System.Core.dll",
    "System.Drawing.dll",
    "System.Windows.Forms.dll",
    "System.Net.Http.dll",
    "System.Web.Extensions.dll"
)
$args = @(
    "/nologo", "/target:winexe", "/platform:anycpu", "/optimize+",
    "/out:$OutDir\AipStation.exe"
) + ($refs | ForEach-Object { "/r:$_" }) + @("$PSScriptRoot\StationClient.cs")

& $csc $args
if ($LASTEXITCODE -ne 0) { throw "编译失败（exit $LASTEXITCODE）" }

Copy-Item "$PSScriptRoot\README.md" "$OutDir\README.md" -Force
$zip = Join-Path $OutDir "AipStation-client.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$OutDir\AipStation.exe", "$OutDir\README.md" -DestinationPath $zip
Write-Host "OK: $OutDir\AipStation.exe"
Write-Host "ZIP: $zip"
