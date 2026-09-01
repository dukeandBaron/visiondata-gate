param(
    [ValidateSet("Quick", "Backend", "Release", "Benchmark", "UI", "Full")]
    [string]$Tier = "Quick",
    [switch]$NoJUnit
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$MarkerExpression = switch ($Tier) {
    "Quick" { "(tier_core or tier_integration) and not slow" }
    "Backend" { "tier_core or tier_integration" }
    "Release" { "tier_release" }
    "Benchmark" { "tier_benchmark" }
    "UI" { "tier_ui" }
    "Full" { $null }
}

$Arguments = @(
    "run",
    "--frozen",
    "python",
    "-m",
    "pytest",
    "-q"
)
if ($MarkerExpression) {
    $Arguments += @("-m", $MarkerExpression)
}
if (-not $NoJUnit) {
    $JUnitPath = ".pytest_cache/regression-$($Tier.ToLowerInvariant()).xml"
    $Arguments += "--junitxml=$JUnitPath"
}

& uv @Arguments
exit $LASTEXITCODE
