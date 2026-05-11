param(
    [string]$Config = "configs/dev.yaml",
    [string]$TaskName = "HRMS-Middleware-Supervisor"
)

$ErrorActionPreference = "Continue"

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

function Write-Check {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Detail = ""
    )

    $status = if ($Ok) { "OK" } else { "FAIL" }
    $color = if ($Ok) { "Green" } else { "Yellow" }
    if ($Detail) {
        Write-Host "[$status] $Name - $Detail" -ForegroundColor $color
    } else {
        Write-Host "[$status] $Name" -ForegroundColor $color
    }
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot
$configPath = Join-Path $projectRoot $Config
$port = Get-ConfiguredIngressPort -ConfigPath $configPath

Write-Host "== HRMS Middleware Windows 10 Health Check ==" -ForegroundColor Cyan
Write-Host "Project: $projectRoot"
Write-Host "Config: $Config"
Write-Host "Port: $port"
Write-Host ""

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    try {
        $version = (& $venvPython --version 2>&1 | Out-String).Trim()
        Write-Check "Virtual environment" $true $version
    } catch {
        Write-Check "Virtual environment" $false $_.Exception.Message
    }
} else {
    Write-Check "Virtual environment" $false ".venv\Scripts\python.exe not found"
}

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    $detail = "state=$($task.State)"
    if ($taskInfo) {
        $detail += " last_result=$($taskInfo.LastTaskResult)"
    }
    Write-Check "Auto-start scheduled task" $true $detail
} catch {
    Write-Check "Auto-start scheduled task" $false "$TaskName not installed or not readable"
}

try {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
        $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ","
        Write-Check "Port listener" $true "port $port pid=$owners"
    } else {
        Write-Check "Port listener" $false "nothing listening on port $port"
    }
} catch {
    Write-Check "Port listener" $false $_.Exception.Message
}

try {
    $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/health" -TimeoutSec 5
    Write-Check "Local health endpoint" ($health.StatusCode -eq 200) "HTTP $($health.StatusCode)"
} catch {
    Write-Check "Local health endpoint" $false $_.Exception.Message
}

try {
    $docs = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/docs" -TimeoutSec 5
    Write-Check "Swagger docs" ($docs.StatusCode -eq 200) "HTTP $($docs.StatusCode)"
} catch {
    Write-Check "Swagger docs" $false $_.Exception.Message
}

$cloudflareUrl = ""
$cloudflareLines = @()
foreach ($logName in @("cloudflared.log", "cloudflared.err.log")) {
    $path = Join-Path $projectRoot "var\logs\$logName"
    if (Test-Path $path) {
        $cloudflareLines += Get-Content $path -Tail 80
    }
}

if ($cloudflareLines) {
    $cloudflareUrl = ($cloudflareLines | Select-String -Pattern "https://[a-z0-9.-]+trycloudflare.com" -AllMatches).Matches.Value | Select-Object -Last 1
}

if ($cloudflareUrl) {
    try {
        $remoteHealth = Invoke-WebRequest -UseBasicParsing -Uri "$cloudflareUrl/health" -TimeoutSec 15
        Write-Check "Cloudflare tunnel" ($remoteHealth.StatusCode -eq 200) "$cloudflareUrl HTTP $($remoteHealth.StatusCode)"
    } catch {
        Write-Check "Cloudflare tunnel" $false "$cloudflareUrl $($_.Exception.Message)"
    }
} else {
    Write-Check "Cloudflare tunnel" $false "no trycloudflare.com URL found in var\logs"
}

Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Start/check app: .\CHECK_WINDOWS10_APP.cmd"
Write-Host "  Local health:    curl.exe http://127.0.0.1:$port/health"
Write-Host "  Task Scheduler:  taskschd.msc"
