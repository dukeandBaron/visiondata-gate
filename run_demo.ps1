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
$Launcher = Join-Path $ProjectRoot "run_semifinal_demo.ps1"
if (-not (Test-Path -LiteralPath $Launcher)) {
    throw "The guided demo launcher is missing: $Launcher"
}

# Stable product-facing alias. The delegated launcher prepares and verifies an
# isolated synthetic project before opening the real React/FastAPI workbench.
& $Launcher @PSBoundParameters
exit $LASTEXITCODE
