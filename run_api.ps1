param(
    [int]$Port = 8787,
    [string]$Python = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if ($Python) {
    $PythonExe = (Get-Command $Python -ErrorAction Stop).Source
}
elseif (Test-Path -LiteralPath $VenvPython) {
    $PythonExe = $VenvPython
}
else {
    throw "No project-local .venv found. Run .\setup_env.ps1, or pass -Python <path>."
}

$env:PYTHONPATH = Join-Path $ProjectRoot "src"
$env:VISIONDATA_PRODUCT_ROOT = Join-Path $ProjectRoot "output\product"
& $PythonExe -c "import fastapi; import uvicorn; import visiondata_gate.api"
if ($LASTEXITCODE -ne 0) { throw "API dependencies are missing. Run uv sync --extra api." }

Write-Host "VisionData Gate API starting at http://127.0.0.1:$Port"
& $PythonExe -m uvicorn visiondata_gate.api:app `
    --app-dir (Join-Path $ProjectRoot "src") `
    --host 127.0.0.1 `
    --port $Port
if ($LASTEXITCODE -ne 0) { throw "VisionData Gate API exited with code $LASTEXITCODE." }
