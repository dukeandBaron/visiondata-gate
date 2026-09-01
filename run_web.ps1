param(
    [ValidateSet("Preview", "Dev")]
    [string]$Mode = "Preview",
    [int]$Port = 0,
    [switch]$Install
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$WebRoot = Join-Path $ProjectRoot "web"
$PackageJson = Join-Path $WebRoot "package.json"
$NodeModules = Join-Path $WebRoot "node_modules"

if (-not (Test-Path -LiteralPath $PackageJson)) {
    throw "The VisionData Gate Web package is missing: $PackageJson"
}

$NodeCommand = Get-Command node -ErrorAction Stop
$NpmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $NpmCommand) {
    $NpmCommand = Get-Command npm -ErrorAction Stop
}

$NodeVersion = & $NodeCommand.Source -p "process.versions.node"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read the Node.js version."
}
$NodeMajor = [int](($NodeVersion -split '\.')[0])
if ($NodeMajor -lt 22) {
    throw "VisionData Gate Web requires Node.js 22 or newer; found $NodeVersion."
}

Set-Location -LiteralPath $WebRoot

if ($Install) {
    Write-Host "Installing the lockfile-pinned Web dependencies with npm ci..."
    & $NpmCommand.Source ci
    if ($LASTEXITCODE -ne 0) {
        throw "npm ci failed with code $LASTEXITCODE."
    }
}
elseif (-not (Test-Path -LiteralPath $NodeModules)) {
    throw "Web dependencies are missing. Run .\run_web.ps1 -Install once."
}

if ($Port -le 0) {
    $Port = if ($Mode -eq "Dev") { 5173 } else { 4173 }
}

if ($Mode -eq "Preview") {
    # Serve a per-process immutable bundle.  A later `npm run build` may replace
    # web/dist, but it must not invalidate chunks already referenced by an open
    # operator session.
    $PreviewRoot = Join-Path $ProjectRoot "output\web_preview"
    $PreviewInstance = Join-Path $PreviewRoot (
        "preview-{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmssfff"), $PID
    )
    New-Item -ItemType Directory -Force -Path $PreviewInstance | Out-Null

    Write-Host "Building an immutable production Web bundle..."
    & $NpmCommand.Source run build -- --outDir $PreviewInstance
    if ($LASTEXITCODE -ne 0) {
        throw "The Web build failed with code $LASTEXITCODE."
    }
    Write-Host "VisionData Gate Web preview: http://127.0.0.1:$Port"
    Write-Host "Immutable preview assets: $PreviewInstance"
    Write-Host "This is the Web core; no desktop installer or production release is implied."
    & $NpmCommand.Source run preview -- --host 127.0.0.1 --port $Port --strictPort --outDir $PreviewInstance
}
else {
    Write-Host "VisionData Gate Web development server: http://127.0.0.1:$Port"
    & $NpmCommand.Source run dev -- --host 127.0.0.1 --port $Port
}

if ($LASTEXITCODE -ne 0) {
    throw "VisionData Gate Web exited with code $LASTEXITCODE."
}
