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
    $PythonExe = (Get-Command $Python -ErrorAction Stop).Source
}
elseif (Test-Path -LiteralPath $VenvPython) {
    $PythonExe = $VenvPython
}
else {
    throw "No project-local .venv found. Run .\setup_env.ps1, or pass -Python <path>."
}

$ReleaseRoot = Join-Path $ProjectRoot "evidence\submission\vdg-20260816-rc1"
$GateResult = Join-Path $ReleaseRoot "omni_gate_result.json"
$SyntheticRoot = Join-Path $ProjectRoot "07_results\frozen_demo_20260809"
$FrontendRoot = Join-Path $ProjectRoot "reviewer_workbench"
if (-not (Test-Path -LiteralPath $GateResult)) {
    throw "The frozen redacted Reviewer Demo evidence is missing."
}
if (-not (Test-Path -LiteralPath (Join-Path $FrontendRoot "index.html"))) {
    throw "The Reviewer Workbench frontend is missing."
}

$env:PYTHONPATH = Join-Path $ProjectRoot "src"
$PreviousFrontendRoot = $env:VISIONDATA_REVIEWER_FRONTEND_ROOT
$PreviousReleaseRoot = $env:VISIONDATA_REVIEWER_RELEASE_ROOT
$PreviousSyntheticRoot = $env:VISIONDATA_REVIEWER_SYNTHETIC_ROOT

try {
    $env:VISIONDATA_REVIEWER_FRONTEND_ROOT = $FrontendRoot
    $env:VISIONDATA_REVIEWER_RELEASE_ROOT = $ReleaseRoot
    $env:VISIONDATA_REVIEWER_SYNTHETIC_ROOT = $SyntheticRoot

    & $PythonExe tools\check_release_consistency.py
    if ($LASTEXITCODE -ne 0) {
        throw "Frozen Reviewer Demo evidence failed consistency verification."
    }

    & $PythonExe -c "import fastapi, uvicorn; from visiondata_gate.reviewer_server import create_reviewer_app; create_reviewer_app()"
    if ($LASTEXITCODE -ne 0) {
        throw "Reviewer Demo dependencies are missing. Run .\setup_env.ps1."
    }

    Write-Host "VisionData Gate Reviewer Workbench starting at http://127.0.0.1:$Port"
    Write-Host "The workbench is read-only and serves only validated redacted evidence."
    & $PythonExe -m uvicorn visiondata_gate.reviewer_server:create_reviewer_app `
        --factory `
        --host 127.0.0.1 `
        --port $Port `
        --no-access-log
    if ($LASTEXITCODE -ne 0) {
        throw "Reviewer Demo exited with code $LASTEXITCODE."
    }
}
finally {
    $env:VISIONDATA_REVIEWER_FRONTEND_ROOT = $PreviousFrontendRoot
    $env:VISIONDATA_REVIEWER_RELEASE_ROOT = $PreviousReleaseRoot
    $env:VISIONDATA_REVIEWER_SYNTHETIC_ROOT = $PreviousSyntheticRoot
}
