param(
    [Parameter(Mandatory = $true)]
    [string]$Command,

    [string]$LogPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $PSScriptRoot "..\\var\\powershell_operations.log"
}

$resolvedLogPath = [System.IO.Path]::GetFullPath($LogPath)
$logDir = Split-Path -Path $resolvedLogPath -Parent
if ($logDir -and -not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

function Add-LogLine {
    param([string]$Text)
    Add-Content -Path $resolvedLogPath -Value $Text -Encoding UTF8
}

$startTime = Get-Date
Add-LogLine ""
Add-LogLine ("==== [{0}] COMMAND START ====" -f $startTime.ToString("yyyy-MM-dd HH:mm:ss.fff zzz"))
Add-LogLine $Command
Add-LogLine "---- OUTPUT ----"

$capturedLines = New-Object System.Collections.Generic.List[string]
$hadError = $false
$success = $true

try {
    $scriptBlock = [ScriptBlock]::Create($Command)
    & $scriptBlock 2>&1 | ForEach-Object {
        $text = ($_ | Out-String).TrimEnd("`r", "`n")
        if ($_ -is [System.Management.Automation.ErrorRecord]) {
            $hadError = $true
        }
        if (-not [string]::IsNullOrWhiteSpace($text)) {
            $capturedLines.Add($text) | Out-Null
            Write-Output $text
        }
    }
}
catch {
    $success = $false
    $hadError = $true
    $errText = ($_ | Out-String).TrimEnd("`r", "`n")
    if (-not [string]::IsNullOrWhiteSpace($errText)) {
        $capturedLines.Add($errText) | Out-Null
        Write-Output $errText
    }
}

if ($capturedLines.Count -eq 0) {
    Add-LogLine "(no output)"
}
else {
    foreach ($line in $capturedLines) {
        Add-LogLine $line
    }
}

$exitCode = 0
$nativeExitCode = $null
$lastExitVar = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
if ($null -ne $lastExitVar) {
    $nativeExitCode = $lastExitVar.Value
}

if ($nativeExitCode -is [int] -and $nativeExitCode -ne 0) {
    $exitCode = [int]$nativeExitCode
}
elseif (-not $success -or $hadError) {
    $exitCode = 1
}

$endTime = Get-Date
Add-LogLine ("---- EXIT CODE: {0} ----" -f $exitCode)
Add-LogLine ("==== [{0}] COMMAND END ====" -f $endTime.ToString("yyyy-MM-dd HH:mm:ss.fff zzz"))

exit $exitCode
