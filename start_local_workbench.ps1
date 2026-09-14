param(
    [ValidateSet("start", "status", "open")][string]$Action = "start",
    [ValidateSet("Dev", "Preview")][string]$Mode = "Dev",
    [string]$ProductRoot = "",
    [int]$ApiPort = 8787,
    [int]$WebPort = 5173,
    [switch]$Initialize,
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Project-local Python is missing. Run setup_env.ps1 first."
}
if ($Action -eq "start") {
    $LocalEnvPath = Join-Path $ProjectRoot ".env.local"
    if (Test-Path -LiteralPath $LocalEnvPath) {
        & (Join-Path $ProjectRoot "tools\import_local_env.ps1") -Path $LocalEnvPath | Out-Null
    }
}
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
$LaunchArgs = @("-m", "visiondata_gate.local_workbench", $Action,
    "--repo-root", $ProjectRoot, "--mode", $Mode,
    "--api-port", "$ApiPort", "--web-port", "$WebPort")
if ($ProductRoot) { $LaunchArgs += @("--product-root", $ProductRoot) }
if ($Initialize) { $LaunchArgs += "--initialize" }
if ($NoBrowser) { $LaunchArgs += "--no-browser" }
& $PythonExe @LaunchArgs
if ($LASTEXITCODE -ne 0) { throw "Local workbench is not ready. See the message above." }
