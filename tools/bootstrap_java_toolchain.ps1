param(
    [string]$ToolsRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ([string]::IsNullOrWhiteSpace($ToolsRoot)) {
    $ToolsRoot = Join-Path $ProjectRoot ".build-tools"
}
$ToolsRoot = [System.IO.Path]::GetFullPath($ToolsRoot)

$JdkVersion = "21.0.12.1+1"
$JdkArchive = Join-Path $ToolsRoot "OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip"
$JdkUrl = "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip"
$JdkSha256 = "f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e"
$JdkHome = Join-Path $ToolsRoot "jdk-21"

$MavenVersion = "3.9.11"
$MavenArchive = Join-Path $ToolsRoot "apache-maven-3.9.11-bin.zip"
$MavenUrl = "https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.11/apache-maven-3.9.11-bin.zip"
$MavenSha512 = "03e2d65d4483a3396980629f260e25cac0d8b6f7f2791e4dc20bc83f9514db8d0f05b0479e699a5f34679250c49c8e52e961262ded468a20de0be254d8207076"
$MavenHome = Join-Path $ToolsRoot "maven-3.9.11"

function Assert-UnderToolsRoot {
    param([Parameter(Mandatory = $true)][string]$Path)
    $ResolvedParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $Path))
    if (-not $ResolvedParent.StartsWith($ToolsRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to manage a toolchain path outside ${ToolsRoot}: $Path"
    }
}

function Get-VerifiedArchive {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][ValidateSet("SHA256", "SHA512")][string]$Algorithm,
        [Parameter(Mandatory = $true)][string]$ExpectedDigest
    )
    Assert-UnderToolsRoot -Path $Destination
    if (Test-Path -LiteralPath $Destination) {
        $Observed = (Get-FileHash -LiteralPath $Destination -Algorithm $Algorithm).Hash.ToLowerInvariant()
        if ($Observed -ne $ExpectedDigest) {
            throw "Existing archive failed ${Algorithm}: $Destination"
        }
        return
    }
    $Partial = "$Destination.part"
    if (Test-Path -LiteralPath $Partial) {
        throw "Interrupted download exists; inspect before retrying: $Partial"
    }
    Invoke-WebRequest -Uri $Url -OutFile $Partial -UseBasicParsing
    $Observed = (Get-FileHash -LiteralPath $Partial -Algorithm $Algorithm).Hash.ToLowerInvariant()
    if ($Observed -ne $ExpectedDigest) {
        throw "Downloaded archive failed ${Algorithm}: $Destination"
    }
    Move-Item -LiteralPath $Partial -Destination $Destination
}

function Expand-SingleRootArchive {
    param(
        [Parameter(Mandatory = $true)][string]$Archive,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$RequiredRelativeFile
    )
    Assert-UnderToolsRoot -Path $Destination
    $Required = Join-Path $Destination $RequiredRelativeFile
    if (Test-Path -LiteralPath $Required) {
        return
    }
    if (Test-Path -LiteralPath $Destination) {
        throw "Incomplete toolchain directory already exists: $Destination"
    }
    $Staging = "$Destination.extracting"
    if (Test-Path -LiteralPath $Staging) {
        throw "Interrupted extraction exists; inspect before retrying: $Staging"
    }
    New-Item -ItemType Directory -Path $Staging | Out-Null
    Expand-Archive -LiteralPath $Archive -DestinationPath $Staging
    $Roots = @(Get-ChildItem -LiteralPath $Staging -Directory)
    if ($Roots.Count -ne 1) {
        throw "Expected one archive root in $Archive, observed $($Roots.Count)"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $Roots[0].FullName $RequiredRelativeFile))) {
        throw "Archive root is missing $RequiredRelativeFile"
    }
    Move-Item -LiteralPath $Roots[0].FullName -Destination $Destination
    Remove-Item -LiteralPath $Staging -Force
}

New-Item -ItemType Directory -Path $ToolsRoot -Force | Out-Null
Get-VerifiedArchive -Url $JdkUrl -Destination $JdkArchive -Algorithm SHA256 -ExpectedDigest $JdkSha256
Expand-SingleRootArchive -Archive $JdkArchive -Destination $JdkHome -RequiredRelativeFile "bin\javac.exe"

Get-VerifiedArchive -Url $MavenUrl -Destination $MavenArchive -Algorithm SHA512 -ExpectedDigest $MavenSha512
Expand-SingleRootArchive -Archive $MavenArchive -Destination $MavenHome -RequiredRelativeFile "bin\mvn.cmd"

$Java = Join-Path $JdkHome "bin\java.exe"
$Javac = Join-Path $JdkHome "bin\javac.exe"
$Jlink = Join-Path $JdkHome "bin\jlink.exe"
$Jdeps = Join-Path $JdkHome "bin\jdeps.exe"
$Maven = Join-Path $MavenHome "bin\mvn.cmd"
foreach ($Required in @($Java, $Javac, $Jlink, $Jdeps, $Maven)) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Portable toolchain is incomplete: $Required"
    }
}

$Receipt = [ordered]@{
    schema_version = "visiondata-gate.local-java-toolchain.v1"
    jdk_version = $JdkVersion
    jdk_archive_sha256 = $JdkSha256
    java = $Java
    javac = $Javac
    jlink = $Jlink
    jdeps = $Jdeps
    maven_version = $MavenVersion
    maven_archive_sha512 = $MavenSha512
    maven = $Maven
    system_path_modified = $false
    registry_modified = $false
}
$ReceiptPath = Join-Path $ToolsRoot "toolchain.json"
$Receipt | ConvertTo-Json | Set-Content -LiteralPath $ReceiptPath -Encoding utf8NoBOM
$Receipt | ConvertTo-Json
