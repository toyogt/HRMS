param(
    [string]$TaskName = "HRMS-Middleware-Supervisor",
    [int]$Port = 9100
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

Write-Host "== HRMS Middleware Status ==" -ForegroundColor Cyan
Write-Host "Project: $projectRoot"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Scheduled task: $TaskName ($($task.State))"
    Write-Host "Last run: $($info.LastRunTime) result=$($info.LastTaskResult)"
    Write-Host "Next run: $($info.NextRunTime)"
} else {
    Write-Host "Scheduled task: not installed"
}

Write-Host ""
Write-Host "Processes:"
$processes = Get-Process | Where-Object { $_.ProcessName -match 'python|cloudflared' } |
    Select-Object Id, ProcessName, Path, StartTime
if ($processes) {
    $processes | Format-Table -AutoSize
} else {
    Write-Host "No python/cloudflared processes found."
}

Write-Host ""
Write-Host "Port check:"
$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $listeners | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize
} else {
    Write-Host "Nothing is listening on port $Port."
}

Write-Host ""
Write-Host "HTTP check:"
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/docs" -UseBasicParsing -TimeoutSec 5
    Write-Host "Swagger docs reachable: HTTP $($response.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "Swagger docs not reachable: $($_.Exception.Message)" -ForegroundColor Yellow
}

$cloudflareLog = Join-Path $projectRoot "var\logs\cloudflared.log"
$cloudflareErrLog = Join-Path $projectRoot "var\logs\cloudflared.err.log"
if ((Test-Path $cloudflareLog) -or (Test-Path $cloudflareErrLog)) {
    Write-Host ""
    Write-Host "Recent Cloudflare log lines:"
    $lines = @()
    if (Test-Path $cloudflareLog) {
        $lines += Get-Content $cloudflareLog -Tail 20
    }
    if (Test-Path $cloudflareErrLog) {
        $lines += Get-Content $cloudflareErrLog -Tail 20
    }
    $lines | Select-Object -Unique | ForEach-Object { Write-Host $_ }

    $urlMatch = ($lines | Select-String -Pattern "https://[a-z0-9.-]+trycloudflare.com" -AllMatches).Matches.Value | Select-Object -Last 1
    if ($urlMatch) {
        Write-Host ""
        Write-Host "Cloudflare public URL: $urlMatch" -ForegroundColor Green
    }
}
