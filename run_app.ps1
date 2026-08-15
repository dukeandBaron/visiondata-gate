param(
    [int]$Port = 8502,
    [string]$Python = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if ($Python) {
    $PythonCommand = Get-Command $Python -ErrorAction Stop
    $PythonExe = $PythonCommand.Source
}
elseif (Test-Path -LiteralPath $VenvPython) {
    $PythonExe = $VenvPython
}
else {
    throw "No project-local .venv found. Run .\setup_env.ps1, or pass -Python <path>."
}

$env:PYTHONPATH = Join-Path $ProjectRoot "src"
& $PythonExe -c "import streamlit; import visiondata_gate"
if ($LASTEXITCODE -ne 0) { throw "Product dependencies are missing." }

Write-Host "VisionData Gate starting at http://127.0.0.1:$Port"
& $PythonExe -m streamlit run app.py `
    --global.developmentMode=false `
    --server.address=127.0.0.1 `
    --server.port=$Port `
    --server.headless=true `
    --browser.gatherUsageStats=false
if ($LASTEXITCODE -ne 0) { throw "VisionData Gate exited with code $LASTEXITCODE." }

