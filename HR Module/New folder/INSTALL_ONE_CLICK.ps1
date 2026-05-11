param(
    [string]$Config = "configs/dev.yaml",
    [switch]$NoAutoStart,
    [switch]$NoStartNow,
    [switch]$InstallSqlServerPrereqs,
    [switch]$SkipPrereqInstall,
    [switch]$EnableCloudflareTunnel,
    [string]$CloudflareToken = "",
    [int]$CloudflareLocalPort = 0
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function New-PythonCommand {
    param(
        [string]$Command,
        [string[]]$Prefix = @()
    )

    return [PSCustomObject]@{
        Command = $Command
        Prefix  = $Prefix
    }
}

function Test-PythonCommand {
    param([object]$Python)

    try {
        $args = @()
        $args += $Python.Prefix
        $args += @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
        & $Python.Command @args *> $null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        $probeArgs = @()
        $probeArgs += $Python.Prefix
        $probeArgs += @("-c", "import sys; print(sys.executable)")
        $resolvedExe = (& $Python.Command @probeArgs).Trim()
        return $resolvedExe -notmatch '\\WindowsApps\\'
    } catch {
        return $false
    }
}

function Resolve-PythonCommand {
    $candidates = @(
        @{ Command = "py"; Prefix = @("-3.11") },
        @{ Command = "py"; Prefix = @("-3") },
        @{ Command = "python"; Prefix = @() }
    )

    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if (-not $cmd) {
            continue
        }

        $python = New-PythonCommand -Command $cmd.Source -Prefix $candidate.Prefix
        if (Test-PythonCommand -Python $python) {
            return $python
        }
    }

    return $null
}

function Get-PythonVersionText {
    param([object]$Python)

    $args = @()
    $args += $Python.Prefix
    $args += @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
    return (& $Python.Command @args).Trim()
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (($machinePath, $userPath) -join ";").Trim(";")
}

function Test-ConfigNeedsSqlServer {
    param([string]$ConfigPath)

    if (-not (Test-Path $ConfigPath)) {
        return $false
    }

    $content = Get-Content -Raw $ConfigPath
    return $content -match 'db_url\s*:\s*".*mssql\+pyodbc' -or $content -match "db_url\s*:\s*'.*mssql\+pyodbc"
}

function Get-ConfiguredIngressPort {
    param(
        [string]$ConfigPath,
        [int]$Fallback = 9100
    )

    if (Test-Path $ConfigPath) {
        $content = Get-Content -Raw $ConfigPath
        $match = [Regex]::Match($content, '(?m)^\s*ingress_port\s*:\s*(\d+)\s*$')
        if ($match.Success) {
            return [int]$match.Groups[1].Value
        }
    }

    return $Fallback
}

function Install-WithWinget {
    param(
        [string]$Id,
        [string]$DisplayName
    )

    Write-Host "Installing/checking $DisplayName..." -ForegroundColor Yellow

    $args = @(
        "install",
        "--id", $Id,
        "-e",
        "--silent",
        "--disable-interactivity",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--force"
    )

    if (Test-IsAdmin) {
        $args += @("--scope", "machine")
    }

    & winget @args
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install '$DisplayName' (package id: $Id)."
    }
}

$projectRoot = (Resolve-Path $PSScriptRoot).Path
Set-Location $projectRoot

$enableAutoStart = -not $NoAutoStart
$startNow = -not $NoStartNow
$configAbsPath = Join-Path $projectRoot $Config
$needsSqlServer = $InstallSqlServerPrereqs -or (Test-ConfigNeedsSqlServer -ConfigPath $configAbsPath)
$configuredPort = Get-ConfiguredIngressPort -ConfigPath $configAbsPath
$effectiveCloudflareLocalPort = if ($CloudflareLocalPort -gt 0) { $CloudflareLocalPort } else { $configuredPort }

if ($enableAutoStart -and -not (Test-IsAdmin)) {
    Write-Host "Re-launching with Administrator privileges for full one-click setup..." -ForegroundColor Yellow
    $argList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Config", "`"$Config`""
    )
    if ($NoAutoStart) { $argList += "-NoAutoStart" }
    if ($NoStartNow) { $argList += "-NoStartNow" }
    if ($InstallSqlServerPrereqs) { $argList += "-InstallSqlServerPrereqs" }
    if ($SkipPrereqInstall) { $argList += "-SkipPrereqInstall" }
    if ($EnableCloudflareTunnel) { $argList += "-EnableCloudflareTunnel" }
    if ($CloudflareToken) { $argList += @("-CloudflareToken", "`"$CloudflareToken`"") }
    if ($CloudflareLocalPort -gt 0) { $argList += @("-CloudflareLocalPort", $CloudflareLocalPort) }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList | Out-Null
    exit 0
}

Write-Host "== One-Click HRMS Middleware Setup ==" -ForegroundColor Cyan
Write-Host "Project: $projectRoot"

if (-not $SkipPrereqInstall) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is not available. Install 'App Installer' from Microsoft Store, then rerun INSTALL_ONE_CLICK.cmd."
    }

    $python = Resolve-PythonCommand
    if (-not $python) {
        Install-WithWinget -Id "Python.Python.3.11" -DisplayName "Python 3.11"
        Refresh-ProcessPath
    } else {
        $versionText = Get-PythonVersionText -Python $python
        Write-Host "Python $versionText already installed on this PC." -ForegroundColor Green
    }

    Install-WithWinget -Id "Microsoft.VCRedist.2015+.x64" -DisplayName "Visual C++ Runtime"

    if ($needsSqlServer) {
        Install-WithWinget -Id "Microsoft.msodbcsql.18" -DisplayName "ODBC Driver 18 for SQL Server"
    }

    if ($EnableCloudflareTunnel) {
        Install-WithWinget -Id "Cloudflare.cloudflared" -DisplayName "Cloudflare Tunnel client"
    }
} else {
    Write-Host "Skipping prerequisite installation by request." -ForegroundColor Yellow
}

$python = Resolve-PythonCommand
if (-not $python) {
    throw "Python 3.11+ is still not discoverable after prerequisite setup. Open a new terminal or install Python 3.11 manually, then rerun INSTALL_ONE_CLICK.cmd."
}
$versionText = Get-PythonVersionText -Python $python
Write-Host "Installer will build .venv using Python $versionText from: $($python.Command) $($python.Prefix -join ' ')"

$installArgs = @{
    Config = $Config
}
if ($needsSqlServer) {
    $installArgs.InstallSqlServerDeps = $true
}

& (Join-Path $projectRoot "scripts\install_local_pc.ps1") @installArgs

if (Test-IsAdmin) {
    try {
        New-NetFirewallRule `
            -DisplayName "HRMS Middleware Gateway $configuredPort" `
            -Direction Inbound `
            -Protocol TCP `
            -Action Allow `
            -LocalPort $configuredPort `
            -ErrorAction SilentlyContinue | Out-Null
    } catch {
        Write-Warning "Could not create firewall rule automatically: $($_.Exception.Message)"
    }
}

if ($enableAutoStart) {
    $autoStartArgs = @{
        Config = $Config
        StartNow = $startNow
        EnableCloudflareTunnel = $EnableCloudflareTunnel
        CloudflareToken = $CloudflareToken
        CloudflareLocalPort = $effectiveCloudflareLocalPort
    }
    & (Join-Path $projectRoot "scripts\setup_autostart.ps1") @autoStartArgs
} elseif ($startNow) {
    $supervisorArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$projectRoot\scripts\run_stack_forever.ps1`"",
        "-Config", "`"$Config`""
    )
    if ($EnableCloudflareTunnel) {
        $supervisorArgs += "-EnableCloudflareTunnel"
        if ($CloudflareToken) {
            $supervisorArgs += @("-CloudflareToken", "`"$CloudflareToken`"")
        }
        $supervisorArgs += @("-CloudflareLocalPort", $effectiveCloudflareLocalPort)
    }

    Write-Host "Starting middleware stack now (manual mode)..." -ForegroundColor Yellow
    Start-Process powershell.exe `
        -ArgumentList $supervisorArgs `
        -WindowStyle Hidden | Out-Null
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "API base: http://127.0.0.1:$configuredPort"
Write-Host "Swagger docs: http://127.0.0.1:$configuredPort/docs"
if ($EnableCloudflareTunnel -and -not $CloudflareToken) {
    Write-Host "Cloudflare quick tunnel enabled. Check var\logs\cloudflared.log for the public trycloudflare.com URL."
}
