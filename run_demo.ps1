param(
    [int]$Seed = 20260809,
    [string]$Output = "07_results\demo",
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
& $PythonExe -m visiondata_gate.cli demo --seed $Seed --output $Output
if ($LASTEXITCODE -ne 0) { throw "Demo failed with code $LASTEXITCODE." }

