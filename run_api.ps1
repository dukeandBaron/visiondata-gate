param(
    [int]$Port = 8787,
    [string]$Python = "",
    [string]$ProductRoot = "",
    [string]$SessionToken = "",
    [string]$ActorUserId = "usr_local_demo"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$LocalEnvPath = Join-Path $ProjectRoot ".env.local"
if (Test-Path -LiteralPath $LocalEnvPath) {
    & (Join-Path $ProjectRoot "tools\import_local_env.ps1") -Path $LocalEnvPath | Out-Null
    Write-Host "Loaded local OpenToken configuration from .env.local (values hidden)."
}

if ($SessionToken) {
    $env:VISIONDATA_SESSION_TOKEN = $SessionToken
}
if ($ActorUserId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
    throw "ActorUserId must be a plain local account token."
}
$env:VISIONDATA_SESSION_ACTOR_USER_ID = $ActorUserId
$ConfiguredSessionToken = [string]$env:VISIONDATA_SESSION_TOKEN
$ConfiguredDesktopToken = [string]$env:VISIONDATA_DESKTOP_SESSION_TOKEN
if (-not $ConfiguredSessionToken -and -not $ConfiguredDesktopToken) {
    throw (
        "Private API routes fail closed without a session. Start with " +
        ".\run_workbench.ps1, or set VISIONDATA_SESSION_TOKEN (32+ characters)."
    )
}
$EffectiveSessionToken = if ($ConfiguredSessionToken) {
    $ConfiguredSessionToken
}
else {
    $ConfiguredDesktopToken
}
if ($EffectiveSessionToken.Length -lt 32) {
    throw "VisionData Gate local session tokens must contain at least 32 characters."
}

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
$ResolvedProductRoot = if ($ProductRoot) {
    if ([System.IO.Path]::IsPathRooted($ProductRoot)) {
        [System.IO.Path]::GetFullPath($ProductRoot)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $ProductRoot))
    }
}
else {
    Join-Path $ProjectRoot "output\product"
}
$env:VISIONDATA_PRODUCT_ROOT = $ResolvedProductRoot
& $PythonExe -c "import fastapi; import uvicorn; import visiondata_gate.api"
if ($LASTEXITCODE -ne 0) { throw "API dependencies are missing. Run uv sync --extra api." }

Write-Host "VisionData Gate API starting at http://127.0.0.1:$Port"
Write-Host "Product data root: $ResolvedProductRoot"
& $PythonExe -m uvicorn visiondata_gate.api:app `
    --app-dir (Join-Path $ProjectRoot "src") `
    --host 127.0.0.1 `
    --port $Port
if ($LASTEXITCODE -ne 0) { throw "VisionData Gate API exited with code $LASTEXITCODE." }
