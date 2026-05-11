param(
    [string]$Config = "configs/dev.yaml",
    [int]$CheckIntervalSeconds = 5,
    [int]$WebhookIntervalSeconds = 60,
    [switch]$EnableCloudflareTunnel,
    [string]$CloudflareToken = "",
    [int]$CloudflareLocalPort = 0,
    [string]$CloudflaredPath = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment not found at $pythonExe. Run install script first."
}

$logDir = Join-Path $projectRoot "var\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Get-ConfiguredIngressPort {
    param(
        [string]$ConfigPath,
        [int]$Fallback = 9100
    )

    $resolvedConfig = $ConfigPath
    if (-not [System.IO.Path]::IsPathRooted($resolvedConfig)) {
        $resolvedConfig = Join-Path $projectRoot $resolvedConfig
    }

    if (Test-Path $resolvedConfig) {
        $content = Get-Content -Raw $resolvedConfig
        $match = [Regex]::Match($content, '(?m)^\s*ingress_port\s*:\s*(\d+)\s*$')
        if ($match.Success) {
            return [int]$match.Groups[1].Value
        }
    }

    return $Fallback
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$ScriptPath,
        [string]$ConfigPath
    )

    $args = @($ScriptPath, "--config", $ConfigPath)
    $stdout = Join-Path $logDir "$Name.out.log"
    $stderr = Join-Path $logDir "$Name.err.log"
    $proc = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList $args `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru

    Write-Host "Started $Name pid=$($proc.Id)"
    return $proc
}

function Resolve-Cloudflared {
    if ($CloudflaredPath -and (Test-Path $CloudflaredPath)) {
        return (Resolve-Path $CloudflaredPath).Path
    }

    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $commonPaths = @(
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
    )
    foreach ($path in $commonPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    $searchRoots = @()
    if ($env:LOCALAPPDATA) {
        $searchRoots += (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages")
    }
    if ($env:ProgramData) {
        $searchRoots += (Join-Path $env:ProgramData "Microsoft\WinGet\Packages")
    }
    $searchRoots = $searchRoots | Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $searchRoots) {
        $match = Get-ChildItem -Path $root -Recurse -Filter "cloudflared.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($match) {
            return $match.FullName
        }
    }

    throw "cloudflared.exe was not found. Re-run INSTALL_ONE_CLICK.cmd with -EnableCloudflareTunnel, or install cloudflared manually."
}

function Start-CloudflareTunnel {
    $cloudflaredExe = Resolve-Cloudflared
    $localPort = if ($CloudflareLocalPort -gt 0) { $CloudflareLocalPort } else { Get-ConfiguredIngressPort -ConfigPath $Config }
    if ($CloudflareToken) {
        $args = @("tunnel", "run", "--token", $CloudflareToken)
    } else {
        $args = @("tunnel", "--url", "http://127.0.0.1:$localPort")
    }

    $stdout = Join-Path $logDir "cloudflared.log"
    $stderr = Join-Path $logDir "cloudflared.err.log"
    $proc = Start-Process `
        -FilePath $cloudflaredExe `
        -ArgumentList $args `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru

    Write-Host "Started cloudflared pid=$($proc.Id)"
    return $proc
}

$gateway = Start-ManagedProcess -Name "gateway" -ScriptPath "scripts/run_gateway.py" -ConfigPath $Config
$worker = Start-ManagedProcess -Name "worker" -ScriptPath "scripts/run_worker.py" -ConfigPath $Config
$cloudflared = $null
if ($EnableCloudflareTunnel) {
    $cloudflared = Start-CloudflareTunnel
}
$nextWebhook = (Get-Date)

try {
    while ($true) {
        if ($gateway.HasExited) {
            Write-Host "Gateway exited code=$($gateway.ExitCode). Restarting..."
            Start-Sleep -Seconds 2
            $gateway = Start-ManagedProcess -Name "gateway" -ScriptPath "scripts/run_gateway.py" -ConfigPath $Config
        }

        if ($worker.HasExited) {
            Write-Host "Worker exited code=$($worker.ExitCode). Restarting..."
            Start-Sleep -Seconds 2
            $worker = Start-ManagedProcess -Name "worker" -ScriptPath "scripts/run_worker.py" -ConfigPath $Config
        }

        if ($EnableCloudflareTunnel -and $null -ne $cloudflared -and $cloudflared.HasExited) {
            Write-Host "cloudflared exited code=$($cloudflared.ExitCode). Restarting..."
            Start-Sleep -Seconds 2
            $cloudflared = Start-CloudflareTunnel
        }

        if ((Get-Date) -ge $nextWebhook) {
            try {
                & $pythonExe "scripts/run_webhook_dispatch.py" "--config" $Config | Out-Null
            } catch {
                Write-Warning "Webhook dispatch run failed: $($_.Exception.Message)"
            }
            $nextWebhook = (Get-Date).AddSeconds($WebhookIntervalSeconds)
        }

        Start-Sleep -Seconds $CheckIntervalSeconds
    }
}
finally {
    foreach ($proc in @($gateway, $worker, $cloudflared)) {
        if ($null -ne $proc -and -not $proc.HasExited) {
            try {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            } catch {
                # no-op
            }
        }
    }
}
