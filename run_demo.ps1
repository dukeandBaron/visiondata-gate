param(
    [Alias("Port")][ValidateRange(1024, 65535)][int]$WebPort = 5173,
    [ValidateRange(1024, 65535)][int]$ApiPort = 8787,
    [string]$Python = "",
    [switch]$Check,
    [switch]$NoBrowser,
    [ValidateRange(0, 60)][int]$SmokeSeconds = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if ($Python) {
    $PythonExe = (Get-Command $Python -ErrorAction Stop).Source
}
elseif (Test-Path -LiteralPath $VenvPython) {
    $PythonExe = $VenvPython
}
else {
    throw "Project environment missing. Run: uv sync --locked --extra api --extra qa"
}

$Launcher = Join-Path $ProjectRoot "tools\run_cross_platform_workbench.py"
$LauncherArgs = @($Launcher, "--api-port", $ApiPort, "--web-port", $WebPort)
if ($Check) { $LauncherArgs += "--check" }
if ($NoBrowser) { $LauncherArgs += "--no-browser" }
if ($SmokeSeconds -gt 0) { $LauncherArgs += @("--smoke-seconds", $SmokeSeconds) }

Push-Location -LiteralPath $ProjectRoot
try {
    Write-Host "VisionData Gate local workbench. No private demo evidence is required."
    & $PythonExe @LauncherArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Workbench launcher failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
