param(
    [int]$ApiPort = 8788,
    [int]$WebPort = 4180,
    [string]$Python = "",
    [string]$ProductRoot = "",
    [switch]$Install,
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PrepareScript = Join-Path $ProjectRoot "tools\prepare_semifinal_demo.py"
$VerifyScript = Join-Path $ProjectRoot "tools\verify_semifinal_demo_manifest.py"
$WorkbenchScript = Join-Path $ProjectRoot "run_workbench.ps1"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$WebNodeModules = Join-Path $ProjectRoot "web\node_modules"

if (-not (Test-Path -LiteralPath $PrepareScript)) {
    throw "The semifinal demo preparation tool is missing: $PrepareScript"
}
if (-not (Test-Path -LiteralPath $VerifyScript)) {
    throw "The semifinal demo manifest verifier is missing: $VerifyScript"
}
if (-not (Test-Path -LiteralPath $WorkbenchScript)) {
    throw "The workbench launcher is missing: $WorkbenchScript"
}
if ($Python) {
    $PythonExe = (Get-Command $Python -ErrorAction Stop).Source
}
elseif (Test-Path -LiteralPath $VenvPython) {
    $PythonExe = $VenvPython
}
else {
    throw "No project-local .venv found. Run .\setup_env.ps1, or pass -Python <path>."
}

$ResolvedProductRoot = if ($ProductRoot) {
    if ([System.IO.Path]::IsPathRooted($ProductRoot)) {
        [System.IO.Path]::GetFullPath($ProductRoot)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $ProductRoot))
    }
}
else {
    Join-Path $ProjectRoot "output\semifinal_demo\product"
}

Set-Location -LiteralPath $ProjectRoot
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
Write-Host "Preparing an isolated, idempotent semifinal reviewer project..."
$PrepareOutput = (& $PythonExe $PrepareScript --product-root $ResolvedProductRoot | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Semifinal demo preparation failed with code $LASTEXITCODE."
}
$ManifestPath = Join-Path $ResolvedProductRoot "semifinal_demo_manifest.json"
$ManifestJson = (
    & $PythonExe $VerifyScript `
        --manifest $ManifestPath `
        --expected-product-root $ResolvedProductRoot |
        Out-String
).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Semifinal demo manifest verification failed with code $LASTEXITCODE."
}
try {
    $Manifest = $ManifestJson | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "Semifinal demo preparation returned an invalid manifest."
}
if (
    $Manifest.status -ne "PASS_LOCAL_DEMO_PREPARED" -or
    $Manifest.project_source_kind -ne "synthetic_demo" -or
    $Manifest.review_start_path -notmatch '^/review\?task=tsk_[0-9a-f]{20}$' -or
    $Manifest.task_final_decision -ne "PASS" -or
    $Manifest.task_release_readiness_status -ne "DEMO_ONLY" -or
    $Manifest.decision_kind -ne "CONTINUE_HOLD" -or
    $Manifest.child_incident_recommendation -ne "CONTINUE_HOLD" -or
    $Manifest.production_release_allowed -ne $false -or
    $Manifest.machine_write_permitted -ne $false -or
    $Manifest.customer_validation -ne "NOT_CLAIMED" -or
    $Manifest.factory_shadow_metrics -ne "NOT_MEASURED_PENDING_ADJUDICATION" -or
    $Manifest.remaining_open_question_count -ne 1 -or
    $Manifest.manifest_sha256 -notmatch '^[0-9a-f]{64}$'
) {
    throw "Semifinal demo manifest failed the isolated reviewer contract."
}
$ReviewStartPath = [string]$Manifest.review_start_path
Write-Host $ManifestJson

$EffectiveInstall = $Install.IsPresent -or -not (Test-Path -LiteralPath $WebNodeModules)
if ($EffectiveInstall -and -not $Install.IsPresent) {
    Write-Host (
        "Web dependencies are absent in this clean extraction; " +
        "running the lockfile-pinned npm ci automatically."
    )
}

Write-Host "Starting the real multi-page workbench in Reviewer Mode."
Write-Host "Synthetic fixture replay remains explicitly labelled; production authority stays false."
& $WorkbenchScript `
    -Mode Preview `
    -ApiPort $ApiPort `
    -WebPort $WebPort `
    -StartPath $ReviewStartPath `
    -ProductRoot $ResolvedProductRoot `
    -Install:$EffectiveInstall `
    -NoBrowser:$NoBrowser
exit $LASTEXITCODE
