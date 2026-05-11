param(
    [string]$Config = "configs/dev.yaml",
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment not found. Run scripts/install_local_pc.ps1 first."
}

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

$configuredPort = Get-ConfiguredIngressPort -ConfigPath $Config

if ($OpenFirewall) {
    Write-Host "Opening inbound firewall port $configuredPort..."
    try {
        New-NetFirewallRule `
            -DisplayName "HRMS Middleware Gateway $configuredPort" `
            -Direction Inbound `
            -Protocol TCP `
            -Action Allow `
            -LocalPort $configuredPort `
            -ErrorAction SilentlyContinue | Out-Null
    } catch {
        Write-Warning "Could not create firewall rule automatically. Run as Administrator if needed."
    }
}

Write-Host "Starting gateway on configured host/port..."
& $pythonExe scripts/run_gateway.py --config $Config
