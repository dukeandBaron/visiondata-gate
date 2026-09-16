#requires -Version 7.0

param(
    [Parameter(Mandatory = $true)]
    [string]$Application,

    [Parameter(Mandatory = $true)]
    [string]$WorkRoot,

    [int]$TimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "WINDOWS_REQUIRED"
}
if ($TimeoutSeconds -lt 10 -or $TimeoutSeconds -gt 120) {
    throw "TIMEOUT_SECONDS_OUT_OF_RANGE"
}

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Get-AbsolutePath([string]$Value) {
    return [System.IO.Path]::GetFullPath($Value)
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-Utf8Json([string]$Path, [object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText(
        $Path,
        $json + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Get-WindowRoot([System.Diagnostics.Process]$Process) {
    $Process.Refresh()
    if ($Process.HasExited -or $Process.MainWindowHandle -eq [IntPtr]::Zero) {
        return $null
    }
    return [System.Windows.Automation.AutomationElement]::FromHandle(
        $Process.MainWindowHandle
    )
}

function Find-Element(
    [System.Windows.Automation.AutomationElement]$Root,
    [string]$AutomationId,
    [string]$Name,
    [System.Windows.Automation.ControlType]$ControlType,
    [string]$NameContains
) {
    if ($null -eq $Root) {
        return $null
    }
    if ($AutomationId) {
        $condition = [System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
            $AutomationId
        )
        return $Root.FindFirst(
            [System.Windows.Automation.TreeScope]::Descendants,
            $condition
        )
    }
    if ($Name -and $null -ne $ControlType) {
        $condition = [System.Windows.Automation.AndCondition]::new(
            [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::NameProperty,
                $Name
            ),
            [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                $ControlType
            )
        )
        return $Root.FindFirst(
            [System.Windows.Automation.TreeScope]::Descendants,
            $condition
        )
    }
    if ($NameContains) {
        $items = $Root.FindAll(
            [System.Windows.Automation.TreeScope]::Descendants,
            [System.Windows.Automation.Condition]::TrueCondition
        )
        for ($index = 0; $index -lt $items.Count; $index += 1) {
            $item = $items.Item($index)
            $itemName = [string]$item.Current.Name
            if (
                $itemName.Contains($NameContains) -and
                ($null -eq $ControlType -or $item.Current.ControlType -eq $ControlType)
            ) {
                return $item
            }
        }
    }
    return $null
}

function Wait-Element(
    [System.Diagnostics.Process]$Process,
    [string]$AutomationId = "",
    [string]$Name = "",
    [System.Windows.Automation.ControlType]$ControlType = $null,
    [string]$NameContains = ""
) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "DESKTOP_EXITED_BEFORE_UI_READY"
        }
        $root = Get-WindowRoot $Process
        $element = Find-Element $root $AutomationId $Name $ControlType $NameContains
        if ($null -ne $element) {
            return $element
        }
        Start-Sleep -Milliseconds 200
    }
    $label = if ($AutomationId) { $AutomationId } elseif ($Name) { $Name } else { $NameContains }
    throw "UI_ELEMENT_TIMEOUT:$label"
}

function Set-ElementValue(
    [System.Windows.Automation.AutomationElement]$Element,
    [string]$Value
) {
    $pattern = $Element.GetCurrentPattern(
        [System.Windows.Automation.ValuePattern]::Pattern
    )
    $pattern.SetValue($Value)
}

function Invoke-Element([System.Windows.Automation.AutomationElement]$Element) {
    $pattern = $Element.GetCurrentPattern(
        [System.Windows.Automation.InvokePattern]::Pattern
    )
    $pattern.Invoke()
}

function Start-Desktop(
    [string]$Executable,
    [string]$Root
) {
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Executable
    $start.WorkingDirectory = [System.IO.Path]::GetDirectoryName($Executable)
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $false
    $start.Environment["LOCALAPPDATA"] = Join-Path $Root "local"
    $start.Environment["APPDATA"] = Join-Path $Root "roaming"
    $start.Environment["USERPROFILE"] = Join-Path $Root "profile"
    $start.Environment["TEMP"] = Join-Path $Root "temp"
    $start.Environment["TMP"] = Join-Path $Root "temp"
    $start.Environment["WEBVIEW2_USER_DATA_FOLDER"] = Join-Path $Root "webview"
    $start.Environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] =
        "--force-renderer-accessibility"
    $process = [System.Diagnostics.Process]::Start($start)
    if ($null -eq $process) {
        throw "DESKTOP_PROCESS_START_FAILED"
    }
    $null = Wait-Element $process -AutomationId "RootWebArea" 2>$null
    return $process
}

function Stop-Desktop([System.Diagnostics.Process]$Process, [bool]$Strict) {
    if ($null -eq $Process) {
        return $true
    }
    $Process.Refresh()
    if ($Process.HasExited) {
        return $true
    }
    $null = $Process.CloseMainWindow()
    $closed = $Process.WaitForExit(20000)
    if (-not $closed -and $Strict) {
        throw "DESKTOP_GRACEFUL_EXIT_TIMEOUT"
    }
    return $closed
}

function Fill-Credentials(
    [System.Diagnostics.Process]$Process,
    [string]$Login,
    [string]$Password
) {
    Set-ElementValue (Wait-Element $Process -AutomationId "identity-login-name") $Login
    Set-ElementValue (Wait-Element $Process -AutomationId "identity-password") $Password
}

function Login(
    [System.Diagnostics.Process]$Process,
    [string]$Login,
    [string]$Password
) {
    Fill-Credentials $Process $Login $Password
    Invoke-Element (Wait-Element $Process -Name "登录" `
        -ControlType ([System.Windows.Automation.ControlType]::Button))
    $null = Wait-Element $Process -Name "工作空间导航" `
        -ControlType ([System.Windows.Automation.ControlType]::Group)
}

function Open-Account(
    [System.Diagnostics.Process]$Process,
    [string]$DisplayName
) {
    $link = Wait-Element $Process -NameContains $DisplayName `
        -ControlType ([System.Windows.Automation.ControlType]::Hyperlink)
    Invoke-Element $link
    $null = Wait-Element $Process -Name "账户与权限" `
        -ControlType ([System.Windows.Automation.ControlType]::Text)
}

$applicationPath = Get-AbsolutePath $Application
$workRootPath = Get-AbsolutePath $WorkRoot
if (-not [System.IO.Path]::IsPathFullyQualified($applicationPath)) {
    throw "APPLICATION_PATH_MUST_BE_ABSOLUTE"
}
if (-not (Test-Path -LiteralPath $applicationPath -PathType Leaf)) {
    throw "APPLICATION_NOT_FOUND"
}
if (Test-Path -LiteralPath $workRootPath) {
    throw "FRESH_WORK_ROOT_REQUIRED"
}

New-Item -ItemType Directory -Path $workRootPath | Out-Null
foreach ($name in @("local", "roaming", "profile", "temp", "webview")) {
    New-Item -ItemType Directory -Path (Join-Path $workRootPath $name) | Out-Null
}

$actions = [System.Collections.Generic.List[string]]::new()
$process = $null
$adminLogin = "uia-smoke-admin"
$memberLogin = "uia-smoke-member"
$adminDisplay = "UIA Smoke Admin"
$memberDisplay = "UIA Smoke Member"
$password = "UIA-" + [Guid]::NewGuid().ToString("N") + "!"
$receiptPath = Join-Path $workRootPath "IDENTITY_DESKTOP_UIA_SMOKE.json"
$failurePath = Join-Path $workRootPath "FAILURE.json"

try {
    $process = Start-Desktop $applicationPath $workRootPath
    Set-ElementValue (Wait-Element $process -AutomationId "identity-login-name") $adminLogin
    Set-ElementValue (Wait-Element $process -AutomationId "identity-display-name") $adminDisplay
    Set-ElementValue (Wait-Element $process -AutomationId "identity-password") $password
    Set-ElementValue (
        Wait-Element $process -AutomationId "identity-password-confirmation"
    ) $password
    Invoke-Element (Wait-Element $process -Name "创建管理员并登录" `
        -ControlType ([System.Windows.Automation.ControlType]::Button))
    $null = Wait-Element $process -Name "任务总览" `
        -ControlType ([System.Windows.Automation.ControlType]::Text)
    $actions.Add("SETUP_AND_LOGIN")

    Open-Account $process $adminDisplay
    Invoke-Element (Wait-Element $process -Name "退出登录" `
        -ControlType ([System.Windows.Automation.ControlType]::Button))
    $null = Wait-Element $process -Name "登录工作台" `
        -ControlType ([System.Windows.Automation.ControlType]::Text)

    Fill-Credentials $process $adminLogin "incorrect-isolated-password"
    Invoke-Element (Wait-Element $process -Name "登录" `
        -ControlType ([System.Windows.Automation.ControlType]::Button))
    $null = Wait-Element $process -NameContains "登录信息无效" `
        -ControlType ([System.Windows.Automation.ControlType]::Text)
    $loginButton = Wait-Element $process -Name "登录" `
        -ControlType ([System.Windows.Automation.ControlType]::Button)
    if (-not $loginButton.Current.IsEnabled) {
        throw "LOGIN_BUTTON_DID_NOT_RECOVER"
    }
    $actions.Add("INVALID_PASSWORD_RECOVERABLE")

    Invoke-Element (Wait-Element $process -Name "没有账户？提交注册申请" `
        -ControlType ([System.Windows.Automation.ControlType]::Button))
    $null = Wait-Element $process -Name "提交注册申请" `
        -ControlType ([System.Windows.Automation.ControlType]::Button)
    Set-ElementValue (Wait-Element $process -AutomationId "identity-login-name") $memberLogin
    Set-ElementValue (Wait-Element $process -AutomationId "identity-display-name") $memberDisplay
    Set-ElementValue (Wait-Element $process -AutomationId "identity-password") $password
    Set-ElementValue (
        Wait-Element $process -AutomationId "identity-password-confirmation"
    ) $password
    Invoke-Element (Wait-Element $process -Name "提交注册申请" `
        -ControlType ([System.Windows.Automation.ControlType]::Button))
    $null = Wait-Element $process `
        -NameContains "注册申请已登记，当前状态为待管理员审批" `
        -ControlType ([System.Windows.Automation.ControlType]::Text)
    $null = Wait-Element $process -Name "登录工作台" `
        -ControlType ([System.Windows.Automation.ControlType]::Text)
    $actions.Add("REGISTER_PENDING")

    Login $process $adminLogin $password
    Open-Account $process $adminDisplay
    Invoke-Element (Wait-Element $process -Name "批准注册" `
        -ControlType ([System.Windows.Automation.ControlType]::Button))
    Invoke-Element (Wait-Element $process -Name "确认批准注册" `
        -ControlType ([System.Windows.Automation.ControlType]::Button))
    $null = Wait-Element $process -NameContains $memberDisplay `
        -ControlType ([System.Windows.Automation.ControlType]::DataItem)
    $actions.Add("ADMIN_APPROVAL")

    Invoke-Element (Wait-Element $process -Name "退出登录" `
        -ControlType ([System.Windows.Automation.ControlType]::Button))
    $null = Wait-Element $process -Name "登录工作台" `
        -ControlType ([System.Windows.Automation.ControlType]::Text)
    Login $process $memberLogin $password
    Open-Account $process $memberDisplay
    $null = Wait-Element $process -Name $memberLogin `
        -ControlType ([System.Windows.Automation.ControlType]::Text)
    $actions.Add("MEMBER_LOGIN")

    if (-not (Stop-Desktop $process $true)) {
        throw "DESKTOP_GRACEFUL_EXIT_FAILED"
    }
    $process = $null

    $process = Start-Desktop $applicationPath $workRootPath
    $null = Wait-Element $process -Name "登录工作台" `
        -ControlType ([System.Windows.Automation.ControlType]::Text)
    Login $process $memberLogin $password
    Open-Account $process $memberDisplay
    $actions.Add("RESTART_AND_LOGIN")
    Invoke-Element (Wait-Element $process -Name "退出登录" `
        -ControlType ([System.Windows.Automation.ControlType]::Button))
    $null = Wait-Element $process -Name "登录工作台" `
        -ControlType ([System.Windows.Automation.ControlType]::Text)
    $actions.Add("LOGOUT")
    if (-not (Stop-Desktop $process $true)) {
        throw "DESKTOP_GRACEFUL_EXIT_FAILED"
    }
    $process = $null

    $startupPath = Join-Path $workRootPath "local\VisionData Gate\logs\desktop-startup.json"
    $databasePath = Join-Path $workRootPath "local\VisionData Gate\product\product.sqlite3"
    if (-not (Test-Path -LiteralPath $startupPath -PathType Leaf)) {
        throw "DESKTOP_STARTUP_RECEIPT_MISSING"
    }
    if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
        throw "IDENTITY_DATABASE_MISSING"
    }
    $startup = Get-Content -LiteralPath $startupPath -Raw | ConvertFrom-Json
    if ($startup.status -ne "READY" -or -not $startup.hmac_readiness_verified) {
        throw "DESKTOP_STARTUP_RECEIPT_NOT_READY"
    }
    if ($startup.production_release_allowed -ne $false) {
        throw "PRODUCTION_AUTHORITY_WIDENED"
    }
    if ($startup.machine_write_permitted -ne $false) {
        throw "MACHINE_AUTHORITY_WIDENED"
    }

    $receipt = [ordered]@{
        schema_version = "visiondata-gate.windows-desktop-identity-uia-smoke.v1"
        status = "PASS_REAL_DESKTOP_IDENTITY_UIA"
        application_sha256 = Get-Sha256 $applicationPath
        validation_tool_sha256 = Get-Sha256 $PSCommandPath
        scope = "REAL_RELEASE_WEBVIEW_UIA_SPRING_FASTAPI_ISOLATED_DATA"
        actions = $actions.ToArray()
        startup = [ordered]@{
            status = $startup.status
            gateway = $startup.gateway
            bind_scope = $startup.bind_scope
            hmac_readiness_verified = $startup.hmac_readiness_verified
        }
        database_created = $true
        webview_devtools_enabled = $false
        accessibility_flag = "--force-renderer-accessibility"
        clean_machine_validation = "NOT_RUN"
        production_release_allowed = $false
        machine_write_permitted = $false
    }
    Write-Utf8Json $receiptPath $receipt
    $receipt | ConvertTo-Json -Depth 20
    exit 0
}
catch {
    $closed = $false
    try {
        $closed = Stop-Desktop $process $false
    }
    catch {
        $closed = $false
    }
    $failure = [ordered]@{
        schema_version = "visiondata-gate.windows-desktop-identity-uia-smoke.v1"
        status = "HOLD_REAL_DESKTOP_IDENTITY_UIA"
        failure_type = $_.Exception.GetType().Name
        failure_code = $_.Exception.Message
        actions = $actions.ToArray()
        owned_desktop_closed = $closed
        clean_machine_validation = "NOT_RUN"
        production_release_allowed = $false
        machine_write_permitted = $false
    }
    Write-Utf8Json $failurePath $failure
    $failure | ConvertTo-Json -Depth 20
    exit 1
}
