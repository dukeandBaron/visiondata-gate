param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [switch]$OverwriteExisting
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ResolvedPath = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
$SeenNames = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
$LoadedNames = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::Ordinal
)
$LoadedCount = 0
$SkippedCount = 0
$SuppressedProductKeyCount = 0
$SuppressedAgentTeamsCredentialCount = 0

foreach ($RawLine in [System.IO.File]::ReadAllLines($ResolvedPath, [System.Text.Encoding]::UTF8)) {
    $Line = $RawLine.Trim()
    if (-not $Line -or $Line.StartsWith("#", [System.StringComparison]::Ordinal)) {
        continue
    }

    $Separator = $Line.IndexOf("=", [System.StringComparison]::Ordinal)
    if ($Separator -lt 1) {
        throw "Invalid local environment entry; expected NAME=value."
    }

    $Name = $Line.Substring(0, $Separator).Trim()
    $Value = $Line.Substring($Separator + 1).Trim()
    if ($Name -cnotmatch "^[A-Z][A-Z0-9_]*$") {
        throw "Invalid local environment variable name: $Name"
    }
    if (-not $SeenNames.Add($Name)) {
        throw "Duplicate local environment variable name: $Name"
    }

    $Existing = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not $OverwriteExisting -and $null -ne $Existing) {
        $SkippedCount += 1
        continue
    }
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    $null = $LoadedNames.Add($Name)
    $LoadedCount += 1
}

$ProductKeysEnabled = [Environment]::GetEnvironmentVariable(
    "VISIONDATA_PRODUCT_MODEL_KEYS_ENABLED",
    "Process"
) -ceq "true"
if (-not $ProductKeysEnabled) {
    foreach ($TargetName in @(
        "VISIONDATA_INCIDENT_MODEL_API_KEY",
        "VISIONDATA_MULTIMODAL_ADVISOR_API_KEY"
    )) {
        if ($LoadedNames.Contains($TargetName)) {
            [Environment]::SetEnvironmentVariable($TargetName, $null, "Process")
            $SuppressedProductKeyCount += 1
        }
    }
}

$AgentTeamsCredentialsEnabled = [Environment]::GetEnvironmentVariable(
    "VISIONDATA_AGENTTEAMS_CREDENTIALS_ENABLED",
    "Process"
) -ceq "true"
if (-not $AgentTeamsCredentialsEnabled) {
    foreach ($TargetName in @(
        "VISIONDATA_AGENTTEAMS_AUTH_TOKEN",
        "VISIONDATA_AGENTTEAMS_AUTH_TOKEN_FILE",
        "VISIONDATA_AGENTTEAMS_MATRIX_ACCESS_TOKEN",
        "VISIONDATA_AGENTTEAMS_MATRIX_ACCESS_TOKEN_FILE",
        "AGENTTEAMS_AUTH_TOKEN",
        "AGENTTEAMS_AUTH_TOKEN_FILE"
    )) {
        if ($LoadedNames.Contains($TargetName)) {
            [Environment]::SetEnvironmentVariable($TargetName, $null, "Process")
            $SuppressedAgentTeamsCredentialCount += 1
        }
    }
}

[pscustomobject]@{
    path = $ResolvedPath
    loaded = $LoadedCount
    skipped_existing = $SkippedCount
    product_keys_enabled = $ProductKeysEnabled
    product_keys_suppressed = $SuppressedProductKeyCount
    agentteams_credentials_enabled = $AgentTeamsCredentialsEnabled
    agentteams_credentials_suppressed = $SuppressedAgentTeamsCredentialCount
    values_exposed = $false
}
