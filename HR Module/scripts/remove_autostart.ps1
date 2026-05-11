param(
    [string]$TaskName = "HRMS-Middleware-Supervisor"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task: $TaskName" -ForegroundColor Green
} else {
    Write-Host "Task not found: $TaskName"
}
