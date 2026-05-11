param(
    [string]$Config = "configs/dev.yaml",
    [switch]$InstallSqlServerDeps,
    [string]$PythonExe = "",
    [switch]$ForceRecreateVenv
)

$ErrorActionPreference = "Stop"

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
        $args += @("-c", "import sys; print(sys.executable); raise SystemExit(0 if sys.version_info >= (3, 11) else 1)")
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
    if ($PythonExe) {
        $resolved = (Resolve-Path $PythonExe -ErrorAction Stop).Path
        $candidate = New-PythonCommand -Command $resolved
        if (Test-PythonCommand -Python $candidate) {
            return $candidate
        }

        throw "Python path was provided but is not Python 3.11+: $resolved"
    }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($selector in @("-3.11", "-3")) {
            try {
                & $pyLauncher.Source $selector --version *> $null
                if ($LASTEXITCODE -eq 0) {
                    $candidate = New-PythonCommand -Command $pyLauncher.Source -Prefix @($selector)
                    if (Test-PythonCommand -Python $candidate) {
                        return $candidate
                    }
                }
            } catch {
                # Keep trying other selectors.
            }
        }
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $candidate = New-PythonCommand -Command $pythonCmd.Source
        if (Test-PythonCommand -Python $candidate) {
            return $candidate
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

function Test-VenvIsReusable {
    param([string]$PythonPath)

    if ($ForceRecreateVenv) {
        return $false
    }

    if (-not (Test-Path $PythonPath)) {
        return $false
    }

    try {
        & $PythonPath -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        $cfgPath = Join-Path (Split-Path (Split-Path $PythonPath -Parent) -Parent) "pyvenv.cfg"
        if (Test-Path $cfgPath) {
            $cfg = Get-Content -Path $cfgPath -Raw
            $executableLine = ($cfg -split "`r?`n" | Where-Object { $_ -match '^executable\s*=' } | Select-Object -First 1)
            if ($executableLine) {
                $baseExe = ($executableLine -replace '^executable\s*=\s*', '').Trim()
                if ($baseExe -match '\\WindowsApps\\') {
                    Write-Host "Existing .venv uses Microsoft Store Python path and will be rebuilt for service reliability: $baseExe" -ForegroundColor Yellow
                    return $false
                }
                if ($baseExe -and -not (Test-Path $baseExe)) {
                    Write-Host "Existing .venv points to missing Python: $baseExe" -ForegroundColor Yellow
                    return $false
                }
            }
        }

        return $true
    } catch {
        return $false
    }
}

function Assert-PathInsideProject {
    param(
        [string]$Path,
        [string]$ProjectRoot
    )

    $resolvedParent = (Resolve-Path (Split-Path -Parent $Path)).Path
    $candidate = Join-Path $resolvedParent (Split-Path -Leaf $Path)
    $fullProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $fullCandidate = [System.IO.Path]::GetFullPath($candidate).TrimEnd('\')

    if (-not $fullCandidate.StartsWith($fullProjectRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify path outside project: $fullCandidate"
    }
}

function Stop-ExistingMiddlewareTask {
    try {
        $task = Get-ScheduledTask -TaskName "HRMS-Middleware-Supervisor" -ErrorAction SilentlyContinue
        if ($task) {
            Stop-ScheduledTask -TaskName "HRMS-Middleware-Supervisor" -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
    } catch {
        # The task may not exist or this shell may not be elevated. Process cleanup below still helps.
    }
}

function Stop-ProjectPythonProcesses {
    param(
        [string]$ProjectRoot,
        [string]$VenvPath
    )

    $fullProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $fullVenvPath = [System.IO.Path]::GetFullPath($VenvPath).TrimEnd('\')

    $processes = Get-CimInstance Win32_Process -Filter "name = 'python.exe' or name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $exe = $_.ExecutablePath
            $cmd = $_.CommandLine
            (($exe -and [System.IO.Path]::GetFullPath($exe).StartsWith($fullVenvPath + '\', [System.StringComparison]::OrdinalIgnoreCase)) -or
             ($cmd -and $cmd.IndexOf($fullProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0))
        }

    foreach ($process in $processes) {
        try {
            Write-Host "Stopping old middleware Python process pid=$($process.ProcessId) before rebuilding .venv..." -ForegroundColor Yellow
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        } catch {
            # Best effort; retry/delete below will surface any remaining lock.
        }
    }

    if ($processes) {
        Start-Sleep -Seconds 2
    }
}

function Stop-ProjectSupervisorProcesses {
    param([string]$ProjectRoot)

    $fullProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $processes = Get-CimInstance Win32_Process -Filter "name = 'powershell.exe' or name = 'pwsh.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -and
            $_.CommandLine.IndexOf("run_stack_forever.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            ($_.CommandLine.IndexOf($fullProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or
             $_.CommandLine.IndexOf(".\scripts\run_stack_forever.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or
             $_.CommandLine.IndexOf("scripts\run_stack_forever.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
        }

    foreach ($process in $processes) {
        try {
            Write-Host "Stopping old middleware supervisor pid=$($process.ProcessId) before rebuilding .venv..." -ForegroundColor Yellow
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        } catch {
            # Best effort; retry/delete below will surface any remaining lock.
        }
    }

    if ($processes) {
        Start-Sleep -Seconds 2
    }
}

Write-Host "== HRMS Middleware Local Installer ==" -ForegroundColor Cyan
Write-Host "Project: $PSScriptRoot\.."

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $projectRoot

$python = Resolve-PythonCommand
if (-not $python) {
    throw "Python 3.11+ is not installed or not discoverable. Install Python and retry."
}

$versionText = Get-PythonVersionText -Python $python
Write-Host "Using Python $versionText from current PC: $($python.Command) $($python.Prefix -join ' ')"

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$venvReusable = Test-VenvIsReusable -PythonPath $pythonExe
if ((Test-Path ".venv") -and -not $venvReusable) {
    Write-Host "Rebuilding .venv because it is missing, broken, or tied to another Python installation..." -ForegroundColor Yellow
    $venvPath = Join-Path $projectRoot ".venv"
    Assert-PathInsideProject -Path $venvPath -ProjectRoot $projectRoot
    Stop-ExistingMiddlewareTask
    Stop-ProjectSupervisorProcesses -ProjectRoot $projectRoot
    Stop-ProjectPythonProcesses -ProjectRoot $projectRoot -VenvPath $venvPath
    Remove-Item -LiteralPath $venvPath -Recurse -Force
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    $venvArgs = @()
    $venvArgs += $python.Prefix
    $venvArgs += @("-m", "venv", ".venv")
    & $python.Command @venvArgs
}

if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment python not found: $pythonExe"
}

Write-Host "Installing dependencies..."
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r requirements.txt
& $pythonExe -m pip install -e .

if ($InstallSqlServerDeps) {
    Write-Host "Installing SQL Server optional dependencies..."
    & $pythonExe -m pip install pyodbc
}

Write-Host ""
Write-Host "Installation completed." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "1) Edit $Config and set API keys / URLs."
Write-Host "2) Start gateway:    .\.venv\Scripts\python.exe scripts\run_gateway.py --config $Config"
Write-Host "3) Start worker:     .\.venv\Scripts\python.exe scripts\run_worker.py --config $Config"
Write-Host "4) Optional webhook: .\.venv\Scripts\python.exe scripts\run_webhook_dispatch.py --config $Config"
