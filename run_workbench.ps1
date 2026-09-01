param(
    [ValidateSet("Preview", "Dev")]
    [string]$Mode = "Preview",
    [int]$ApiPort = 8787,
    [int]$WebPort = 0,
    [string]$StartPath = "/workspace",
    [string]$ProductRoot = "",
    [switch]$Install,
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApiScript = Join-Path $ProjectRoot "run_api.ps1"
$WebScript = Join-Path $ProjectRoot "run_web.ps1"

if (-not (Test-Path -LiteralPath $ApiScript)) {
    throw "The API launcher is missing: $ApiScript"
}
if (-not (Test-Path -LiteralPath $WebScript)) {
    throw "The Web launcher is missing: $WebScript"
}
if ($WebPort -le 0) {
    $WebPort = if ($Mode -eq "Dev") { 5173 } else { 4173 }
}
if ($StartPath -notmatch '^/(workspace|review)(?:\?[^#]*)?$') {
    throw "StartPath must target /workspace or /review with an optional query string."
}

$ApiHealthUrl = "http://127.0.0.1:$ApiPort/v1/health"
$WorkbenchBaseUrl = "http://127.0.0.1:$WebPort$StartPath"
$WebOrigin = "http://127.0.0.1:$WebPort"
$OwnedJobs = [System.Collections.Generic.List[System.Management.Automation.Job]]::new()
$SessionBytes = New-Object byte[] 32
$SessionGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $SessionGenerator.GetBytes($SessionBytes)
}
finally {
    $SessionGenerator.Dispose()
}
$SessionToken = [Convert]::ToBase64String($SessionBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
$SessionActor = "usr_local_demo"
$WorkbenchUrl = "$WorkbenchBaseUrl#visiondata_session=$SessionToken"

function Test-LocalEndpoint {
    param([Parameter(Mandatory = $true)][string]$Url)

    try {
        $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $Response.StatusCode -ge 200 -and $Response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Wait-LocalEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Label,
        [int]$TimeoutSeconds = 120
    )

    $Deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $Deadline) {
        if (Test-LocalEndpoint -Url $Url) {
            Write-Host "$Label ready: $Url"
            return
        }
        foreach ($Job in $OwnedJobs) {
            Receive-Job -Job $Job -ErrorAction SilentlyContinue
            if ($Job.State -in @("Failed", "Stopped", "Completed")) {
                throw "$Label launcher stopped before the endpoint became ready."
            }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$Label did not become ready within $TimeoutSeconds seconds: $Url"
}

if (Test-LocalEndpoint -Url $ApiHealthUrl) {
    throw (
        "API port $ApiPort is already in use. The launcher will not disclose a new " +
        "session capability to an unverified listener. Choose a free -ApiPort or " +
        "stop the existing API."
    )
}
else {
    Write-Host "Starting the local API..."
    $ApiJob = Start-Job -Name "visiondata-gate-api" -ScriptBlock {
        param($ScriptPath, $Port, $AllowedWebOrigin, $RequestedProductRoot, $Token, $Actor)
        $env:VISIONDATA_WEB_ORIGINS = $AllowedWebOrigin
        & $ScriptPath -Port $Port -ProductRoot $RequestedProductRoot `
            -SessionToken $Token -ActorUserId $Actor
    } -ArgumentList $ApiScript, $ApiPort, $WebOrigin, $ProductRoot, $SessionToken, $SessionActor
    $OwnedJobs.Add($ApiJob)
}

if (Test-LocalEndpoint -Url $WorkbenchUrl) {
    throw (
        "Web port $WebPort is already in use; the existing proxy session cannot be " +
        "proven. Choose a free -WebPort or stop the existing workbench."
    )
}
else {
    Write-Host "Starting the Web workbench..."
    $WebJob = Start-Job -Name "visiondata-gate-web" -ScriptBlock {
        param($ScriptPath, $SelectedMode, $Port, $InstallDependencies, $ApiBaseUrl)
        $env:VISIONDATA_WEB_API_TARGET = $ApiBaseUrl
        & $ScriptPath -Mode $SelectedMode -Port $Port -Install:$InstallDependencies
    } -ArgumentList $WebScript, $Mode, $WebPort, $Install.IsPresent, "http://127.0.0.1:$ApiPort"
    $OwnedJobs.Add($WebJob)
}

try {
    Wait-LocalEndpoint -Url $ApiHealthUrl -Label "API"
    Wait-LocalEndpoint -Url $WorkbenchUrl -Label "Operator Workbench"

    Write-Host "VisionData Gate Operator Workbench: $WorkbenchBaseUrl"
    if ($ProductRoot) {
        Write-Host "Product data remains under the requested isolated root: $ProductRoot"
    }
    else {
        Write-Host "Product data remains under output\product and is not sent to OpenToken."
    }
    if (-not $NoBrowser) {
        Start-Process $WorkbenchUrl
    }
    else {
        Write-Host "Browser launch disabled; no session capability was printed."
    }

    if ($OwnedJobs.Count -gt 0) {
        Write-Host "Press Ctrl+C to stop the services started by this launcher."
        while ($true) {
            foreach ($Job in $OwnedJobs) {
                Receive-Job -Job $Job -ErrorAction SilentlyContinue
                if ($Job.State -in @("Failed", "Stopped", "Completed")) {
                    throw "A workbench service stopped unexpectedly."
                }
            }
            Start-Sleep -Milliseconds 750
        }
    }
}
finally {
    foreach ($Job in $OwnedJobs) {
        Stop-Job -Job $Job -ErrorAction SilentlyContinue
        Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue
    }
}
