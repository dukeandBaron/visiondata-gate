param(
    [string]$Python = "python",
    [string]$Uv = "uv"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$PythonExe = (Get-Command $Python -ErrorAction Stop).Source
try {
    $UvExe = (Get-Command $Uv -ErrorAction Stop).Source
}
catch {
    throw "uv is required for a lockfile-reproducible install. Install uv from https://docs.astral.sh/uv/ and rerun this script."
}

& $UvExe sync --frozen --all-extras --python $PythonExe
if ($LASTEXITCODE -ne 0) {
    throw "uv sync failed with code $LASTEXITCODE. The lockfile was not modified."
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "uv completed without creating the expected project-local .venv."
}

& $VenvPython -c "import streamlit; import fastapi; import visiondata_gate"
if ($LASTEXITCODE -ne 0) {
    throw "The locked environment was created but the product imports failed."
}

Write-Host "VisionData Gate locked environment is ready: $VenvPython"
