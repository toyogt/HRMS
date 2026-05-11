param(
    [string]$Config = "configs/dev.yaml",
    [string]$TaskName = "HRMS-Middleware-Supervisor",
    [switch]$StartNow,
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

if (-not (Test-IsAdmin)) {
    throw "Run this script as Administrator to create boot-start scheduled task."
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$supervisorScript = Join-Path $projectRoot "scripts\run_stack_forever.ps1"
if (-not (Test-Path $supervisorScript)) {
    throw "Supervisor script not found: $supervisorScript"
}

$configAbs = (Resolve-Path (Join-Path $projectRoot $Config)).Path

$argLine = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$supervisorScript`" -Config `"$configAbs`""
if ($EnableCloudflareTunnel) {
    $argLine += " -EnableCloudflareTunnel -CloudflareLocalPort $CloudflareLocalPort"
    if ($CloudflareToken) {
        $argLine += " -CloudflareToken `"$CloudflareToken`""
    }
}
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argLine -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "HRMS middleware supervisor (gateway + worker + webhook dispatcher)" `
    -Force | Out-Null

Write-Host "Scheduled task created: $TaskName" -ForegroundColor Green

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Task started now: $TaskName"
}
