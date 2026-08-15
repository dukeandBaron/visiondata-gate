param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$PythonCommand = Get-Command $Python -ErrorAction Stop
$PythonExe = $PythonCommand.Source
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    & $PythonExe -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed with code $LASTEXITCODE" }
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed with code $LASTEXITCODE" }
& $VenvPython -m pip install -e ".[ui,api,qa]"
if ($LASTEXITCODE -ne 0) { throw "dependency install failed with code $LASTEXITCODE" }

Write-Host "VisionData Gate environment is ready: $VenvPython"
