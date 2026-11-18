param(
    [string]$OutDir = "$PSScriptRoot\release"
)

$ErrorActionPreference = "Stop"
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { throw "Cannot find .NET Framework 4.8 compiler: $csc" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$refs = @(
    "System.dll",
    "System.Core.dll",
    "System.Drawing.dll",
    "System.Windows.Forms.dll",
    "System.Net.Http.dll",
    "System.Web.Extensions.dll",
    "$PSScriptRoot\vendor\Sharp7.dll"
)
$sources = @(
    "$PSScriptRoot\StationClient.cs",
    "$PSScriptRoot\Plc.cs",
    "$PSScriptRoot\PlcConfigDialog.cs"
)
$args = @(
    "/nologo", "/target:winexe", "/platform:anycpu", "/optimize+",
    "/out:$OutDir\AipStation.exe"
) + ($refs | ForEach-Object { "/r:$_" }) + $sources

& $csc $args
if ($LASTEXITCODE -ne 0) { throw "Build failed (exit $LASTEXITCODE)" }

Copy-Item "$PSScriptRoot\README.md" "$OutDir\README.md" -Force
Copy-Item "$PSScriptRoot\vendor\Sharp7.dll" "$OutDir\Sharp7.dll" -Force
Copy-Item "$PSScriptRoot\vendor\Sharp7-LICENSE.txt" "$OutDir\Sharp7-LICENSE.txt" -Force
$zip = Join-Path $OutDir "AipStation-client.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$OutDir\AipStation.exe", "$OutDir\Sharp7.dll", "$OutDir\Sharp7-LICENSE.txt", "$OutDir\README.md" -DestinationPath $zip
Write-Host "OK: $OutDir\AipStation.exe"
Write-Host "ZIP: $zip"
