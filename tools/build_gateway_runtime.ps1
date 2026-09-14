param(
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$GatewayRoot = Join-Path $ProjectRoot "gateway"
$ToolchainPath = Join-Path $ProjectRoot ".build-tools\toolchain.json"
if (-not (Test-Path -LiteralPath $ToolchainPath)) {
    throw "Portable Java toolchain is missing. Run tools\bootstrap_java_toolchain.ps1 first."
}

$Toolchain = Get-Content -Raw -LiteralPath $ToolchainPath | ConvertFrom-Json
$Java = [System.IO.Path]::GetFullPath([string]$Toolchain.java)
$Jlink = [System.IO.Path]::GetFullPath([string]$Toolchain.jlink)
$Maven = [System.IO.Path]::GetFullPath([string]$Toolchain.maven)
$JavaHome = Split-Path -Parent (Split-Path -Parent $Java)
foreach ($Required in @($Java, $Jlink, $Maven)) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Portable Java toolchain entry is missing: $Required"
    }
}

$env:JAVA_HOME = $JavaHome
$MavenArgs = @("-f", (Join-Path $GatewayRoot "pom.xml"), "clean", "package")
if ($SkipTests) {
    $MavenArgs += "-DskipTests"
}
& $Maven @MavenArgs
if ($LASTEXITCODE -ne 0) {
    throw "Spring Boot gateway build failed with code $LASTEXITCODE."
}

$GatewayJar = Join-Path $GatewayRoot "target\visiondata-gate-gateway.jar"
if (-not (Test-Path -LiteralPath $GatewayJar -PathType Leaf)) {
    throw "Spring Boot gateway JAR is missing: $GatewayJar"
}

$RuntimeRoot = [System.IO.Path]::GetFullPath((Join-Path $GatewayRoot "runtime"))
$ExpectedPrefix = [System.IO.Path]::GetFullPath($GatewayRoot).TrimEnd("\") + "\"
if (-not $RuntimeRoot.StartsWith($ExpectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to manage Java runtime outside gateway root: $RuntimeRoot"
}
if (Test-Path -LiteralPath $RuntimeRoot) {
    $RuntimeItem = Get-Item -LiteralPath $RuntimeRoot -Force
    if (($RuntimeItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to replace a reparse-point runtime directory: $RuntimeRoot"
    }
    Remove-Item -LiteralPath $RuntimeRoot -Recurse -Force
}

$RuntimeModules = @(
    "java.base",
    "java.compiler",
    "java.desktop",
    "java.instrument",
    "java.management",
    "java.naming",
    "java.net.http",
    "java.prefs",
    "java.security.jgss",
    "java.sql",
    "java.transaction.xa",
    "java.xml",
    "jdk.crypto.ec",
    "jdk.management",
    "jdk.naming.dns",
    "jdk.unsupported",
    "jdk.zipfs"
)

& $Jlink `
    --add-modules ($RuntimeModules -join ",") `
    --bind-services `
    --strip-debug `
    --no-header-files `
    --no-man-pages `
    --compress=2 `
    --output $RuntimeRoot
if ($LASTEXITCODE -ne 0) {
    throw "jlink failed with code $LASTEXITCODE."
}

$RuntimeJava = Join-Path $RuntimeRoot "bin\java.exe"
$RuntimeJavaw = Join-Path $RuntimeRoot "bin\javaw.exe"
if (-not (Test-Path -LiteralPath $RuntimeJava -PathType Leaf)) {
    throw "jlink runtime is missing java.exe"
}
if (-not (Test-Path -LiteralPath $RuntimeJavaw -PathType Leaf)) {
    throw "jlink runtime is missing javaw.exe"
}
& $RuntimeJava -version
if ($LASTEXITCODE -ne 0) {
    throw "Generated Java runtime failed its version probe."
}

$Receipt = [ordered]@{
    schema_version = "visiondata-gate.gateway-runtime-build.v1"
    status = "PASS_LOCAL_BUILD"
    spring_boot_version = "4.1.1"
    java_version = [string]$Toolchain.jdk_version
    gateway_jar_sha256 = (Get-FileHash -LiteralPath $GatewayJar -Algorithm SHA256).Hash.ToLowerInvariant()
    runtime_java_sha256 = (Get-FileHash -LiteralPath $RuntimeJava -Algorithm SHA256).Hash.ToLowerInvariant()
    runtime_modules = $RuntimeModules
    bind_scope = "LOOPBACK_ONLY"
    production_release_allowed = $false
    machine_write_permitted = $false
}
$ReceiptPath = Join-Path $GatewayRoot "target\gateway-runtime-receipt.json"
$Serialized = ($Receipt | ConvertTo-Json -Depth 6) + "`n"
[System.IO.File]::WriteAllText($ReceiptPath, $Serialized, [System.Text.UTF8Encoding]::new($false))
$Serialized
