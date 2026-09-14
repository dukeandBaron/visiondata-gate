param(
    [switch]$SkipDependencySync,
    [switch]$SkipBackend,
    [switch]$SkipGateway
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WebRoot = Join-Path $ProjectRoot "web"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BackendSpec = Join-Path $ProjectRoot "desktop\visiondata_gate_backend.spec"
$BackendExe = Join-Path $ProjectRoot "desktop\dist\visiondata-gate-backend\visiondata-gate-backend.exe"
$BackendSmoke = Join-Path $ProjectRoot "tools\smoke_windows_sidecar.py"
$JavaBootstrap = Join-Path $ProjectRoot "tools\bootstrap_java_toolchain.ps1"
$GatewayBuild = Join-Path $ProjectRoot "tools\build_gateway_runtime.ps1"
$GatewaySmoke = Join-Path $ProjectRoot "tools\smoke_spring_gateway.py"
$GatewayJar = Join-Path $ProjectRoot "gateway\target\visiondata-gate-gateway.jar"
$GatewayJava = Join-Path $ProjectRoot "gateway\runtime\bin\java.exe"
$DeliveryRoot = Join-Path $ProjectRoot "deliverables\windows"
$BackendSmokeReceipt = Join-Path $DeliveryRoot "BACKEND_SIDECAR_SMOKE.json"
$GatewaySmokeReceipt = Join-Path $DeliveryRoot "GATEWAY_SMOKE.json"
$BuildManifestPath = Join-Path $DeliveryRoot "BUILD_MANIFEST.json"

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

if (-not $SkipGateway) {
    & $JavaBootstrap
    if ($LASTEXITCODE -ne 0) { throw "Java toolchain bootstrap failed with code $LASTEXITCODE." }
    & $GatewayBuild
    if ($LASTEXITCODE -ne 0) { throw "Spring Boot gateway build failed with code $LASTEXITCODE." }
}

if (-not (Test-Path -LiteralPath $GatewayJar -PathType Leaf)) {
    throw "The packaged Spring Boot gateway is missing: $GatewayJar"
}
if (-not (Test-Path -LiteralPath $GatewayJava -PathType Leaf)) {
    throw "The packaged Java runtime is missing: $GatewayJava"
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

& $PythonExe $GatewaySmoke `
    --backend-executable $BackendExe `
    --java-executable $GatewayJava `
    --gateway-jar $GatewayJar `
    --output $GatewaySmokeReceipt
if ($LASTEXITCODE -ne 0) {
    throw "Spring Boot and FastAPI joint smoke failed with code $LASTEXITCODE."
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

$BuildManifest = [ordered]@{
    schema_version = "visiondata-gate.windows-installer-build.v2"
    status = "BUILD_PASS_LOCAL"
    architecture = "windows-x64"
    installer = @(
        $Installers | ForEach-Object {
            $Delivered = Join-Path $DeliveryRoot $_.Name
            [ordered]@{
                filename = $_.Name
                size_bytes = (Get-Item -LiteralPath $Delivered).Length
                sha256 = (Get-FileHash -LiteralPath $Delivered -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    )
    fastapi_sidecar_sha256 = (Get-FileHash -LiteralPath $BackendExe -Algorithm SHA256).Hash.ToLowerInvariant()
    spring_gateway_jar_sha256 = (Get-FileHash -LiteralPath $GatewayJar -Algorithm SHA256).Hash.ToLowerInvariant()
    java_runtime_sha256 = (Get-FileHash -LiteralPath $GatewayJava -Algorithm SHA256).Hash.ToLowerInvariant()
    backend_smoke_receipt_sha256 = (Get-FileHash -LiteralPath $BackendSmokeReceipt -Algorithm SHA256).Hash.ToLowerInvariant()
    gateway_smoke_receipt_sha256 = (Get-FileHash -LiteralPath $GatewaySmokeReceipt -Algorithm SHA256).Hash.ToLowerInvariant()
    target_requires_python = $false
    target_requires_java = $false
    target_requires_node = $false
    target_requires_rust = $false
    bind_scope = "LOOPBACK_ONLY"
    code_signed = $false
    clean_machine_validation = "NOT_RUN"
    production_release_allowed = $false
}
$SerializedManifest = ($BuildManifest | ConvertTo-Json -Depth 8) + "`n"
[System.IO.File]::WriteAllText(
    $BuildManifestPath,
    $SerializedManifest,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "Unsigned Windows test installer generated in $DeliveryRoot"
Write-Host "This build is not code-signed and is not a production release."
