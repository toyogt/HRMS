param(
    [string]$Config = "configs/dev.yaml",
    [switch]$NoCloudflareTunnel,
    [string]$CloudflareToken = "",
    [int]$CloudflareLocalPort = 0,
    [switch]$InstallSqlServerPrereqs,
    [switch]$SkipPrereqInstall
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
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

function Invoke-HealthCheck {
    param([int]$Port)

    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }

    return $false
}

function Stop-OldRuntime {
    param(
        [string]$ProjectRoot,
        [string]$TaskName,
        [int]$Port
    )

    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            Write-Host "Stopping existing scheduled task: $TaskName"
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Warning "Could not stop existing scheduled task: $($_.Exception.Message)"
    }

    $fullProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $name = $_.Name
            $cmd = $_.CommandLine
            (($name -in @("python.exe", "pythonw.exe", "powershell.exe", "pwsh.exe")) -and
                $cmd -and
                ($cmd.IndexOf($fullProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                 $cmd.IndexOf("run_stack_forever.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0)) -or
            ($name -eq "cloudflared.exe" -and
                $cmd -and
                $cmd.IndexOf("http://127.0.0.1:$Port", [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
        }

    foreach ($process in $processes) {
        if ($process.ProcessId -eq $PID) {
            continue
        }
        try {
            Write-Host "Stopping old runtime process pid=$($process.ProcessId) name=$($process.Name)"
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Warning "Could not stop pid=$($process.ProcessId): $($_.Exception.Message)"
        }
    }

    if ($processes) {
        Start-Sleep -Seconds 3
    }
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$logDir = Join-Path $projectRoot "var\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$installLog = Join-Path $logDir "windows10_install_forever.log"

if (-not (Test-IsAdmin)) {
    Write-Host "Re-launching as Administrator for Windows auto-start setup..." -ForegroundColor Yellow
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Config", "`"$Config`""
    )
    if ($NoCloudflareTunnel) { $args += "-NoCloudflareTunnel" }
    if ($CloudflareToken) { $args += @("-CloudflareToken", "`"$CloudflareToken`"") }
    if ($CloudflareLocalPort -gt 0) { $args += @("-CloudflareLocalPort", $CloudflareLocalPort) }
    if ($InstallSqlServerPrereqs) { $args += "-InstallSqlServerPrereqs" }
    if ($SkipPrereqInstall) { $args += "-SkipPrereqInstall" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $args | Out-Null
    exit 0
}

Start-Transcript -Path $installLog -Append | Out-Null
try {
    Write-Host "== HRMS Middleware Windows 10 Forever Installer ==" -ForegroundColor Cyan
    Write-Host "Project: $projectRoot"
    Write-Host "Config: $Config"
    Write-Host "Install log: $installLog"

    $configPath = Join-Path $projectRoot $Config
    $port = Get-ConfiguredIngressPort -ConfigPath $configPath
    $cloudflarePort = if ($CloudflareLocalPort -gt 0) { $CloudflareLocalPort } else { $port }
    $enableCloudflare = -not $NoCloudflareTunnel

    Stop-OldRuntime -ProjectRoot $projectRoot -TaskName "HRMS-Middleware-Supervisor" -Port $port

    $installArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$projectRoot\INSTALL_ONE_CLICK.ps1`"",
        "-Config", "`"$Config`"",
        "-CloudflareLocalPort", $cloudflarePort
    )
    if ($enableCloudflare) { $installArgs += "-EnableCloudflareTunnel" }
    if ($CloudflareToken) { $installArgs += @("-CloudflareToken", "`"$CloudflareToken`"") }
    if ($InstallSqlServerPrereqs) { $installArgs += "-InstallSqlServerPrereqs" }
    if ($SkipPrereqInstall) { $installArgs += "-SkipPrereqInstall" }

    & powershell.exe @installArgs
    if ($LASTEXITCODE -ne 0) {
        throw "INSTALL_ONE_CLICK.ps1 failed with exit code $LASTEXITCODE"
    }

    Write-Host ""
    Write-Host "Waiting for middleware health on port $port..."
    if (Invoke-HealthCheck -Port $port) {
        Write-Host "Middleware health check passed: http://127.0.0.1:$port/health" -ForegroundColor Green
    } else {
        Write-Warning "Middleware did not respond on http://127.0.0.1:$port/health within 45 seconds."
    }

    Write-Host ""
    & (Join-Path $projectRoot "scripts\windows10_health_check.ps1") -Config $Config

    Write-Host ""
    Write-Host "Windows 10 forever setup finished." -ForegroundColor Green
    Write-Host "Local API: http://127.0.0.1:$port"
    Write-Host "Docs:      http://127.0.0.1:$port/docs"
    Write-Host "Task:      HRMS-Middleware-Supervisor"
    Write-Host "Logs:      $logDir"
} finally {
    Stop-Transcript | Out-Null
}
