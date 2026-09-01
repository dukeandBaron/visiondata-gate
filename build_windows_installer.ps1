param(
    [switch]$SkipDependencySync,
    [switch]$SkipBackend
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WebRoot = Join-Path $ProjectRoot "web"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BackendSpec = Join-Path $ProjectRoot "desktop\visiondata_gate_backend.spec"
$BackendExe = Join-Path $ProjectRoot "desktop\dist\visiondata-gate-backend\visiondata-gate-backend.exe"
$BackendSmoke = Join-Path $ProjectRoot "tools\smoke_windows_sidecar.py"
$DeliveryRoot = Join-Path $ProjectRoot "deliverables\windows"
$BackendSmokeReceipt = Join-Path $DeliveryRoot "BACKEND_SIDECAR_SMOKE.json"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Project Python 3.12 environment is missing. Run .\setup_env.ps1 first."
}

Set-Location -LiteralPath $ProjectRoot

if (-not $SkipDependencySync) {
    & uv sync --all-extras
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed with code $LASTEXITCODE." }

    Set-Location -LiteralPath $WebRoot
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed with code $LASTEXITCODE." }
    Set-Location -LiteralPath $ProjectRoot
}

if (-not $SkipBackend) {
    & $PythonExe -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath (Join-Path $ProjectRoot "desktop\dist") `
        --workpath (Join-Path $ProjectRoot "desktop\build") `
        $BackendSpec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with code $LASTEXITCODE." }
}

if (-not (Test-Path -LiteralPath $BackendExe)) {
    throw "The packaged FastAPI sidecar is missing: $BackendExe"
}
if (Get-ChildItem -LiteralPath (Split-Path -Parent $BackendExe) -Recurse -File -Filter ".env.local") {
    throw "Secret-bearing .env.local was found in the sidecar bundle."
}

New-Item -ItemType Directory -Path $DeliveryRoot -Force | Out-Null
& $PythonExe $BackendSmoke `
    --executable $BackendExe `
    --output $BackendSmokeReceipt
if ($LASTEXITCODE -ne 0) {
    throw "Packaged sidecar smoke failed with code $LASTEXITCODE."
}

Set-Location -LiteralPath $WebRoot
& npm.cmd run desktop:build
if ($LASTEXITCODE -ne 0) { throw "Tauri build failed with code $LASTEXITCODE." }

$NsisRoot = Join-Path $WebRoot "src-tauri\target\release\bundle\nsis"
$Installers = @(Get-ChildItem -LiteralPath $NsisRoot -File -Filter "*.exe")
if ($Installers.Count -eq 0) {
    throw "Tauri completed without producing an NSIS installer."
}

$ManifestLines = @()
foreach ($Installer in $Installers) {
    $Destination = Join-Path $DeliveryRoot $Installer.Name
    Copy-Item -LiteralPath $Installer.FullName -Destination $Destination -Force
    $Digest = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    $ManifestLines += "$Digest  $($Installer.Name)"
}
$ManifestPath = Join-Path $DeliveryRoot "SHA256SUMS.txt"
[System.IO.File]::WriteAllLines($ManifestPath, $ManifestLines, [System.Text.UTF8Encoding]::new($false))

Write-Host "Unsigned Windows test installer generated in $DeliveryRoot"
Write-Host "This build is not code-signed and is not a production release."
