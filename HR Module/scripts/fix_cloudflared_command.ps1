param(
    [switch]$PersistProfile
)

$ErrorActionPreference = "Stop"

$candidates = @(
    "$env:ProgramFiles\cloudflared\cloudflared.exe",
    "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
)

$exe = $null
foreach ($path in $candidates) {
    if (Test-Path $path) {
        $exe = (Resolve-Path $path).Path
        break
    }
}

if (-not $exe) {
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
            $exe = $match.FullName
            break
        }
    }
}

if (-not $exe) {
    throw "cloudflared.exe not found. Install with: winget install --id Cloudflare.cloudflared -e"
}

$dir = Split-Path -Parent $exe

if (($env:Path -split ';') -notcontains $dir) {
    $env:Path = ($env:Path.TrimEnd(';') + ';' + $dir).Trim(';')
}

Set-Alias -Name cloudflared -Value $exe -Scope Global
Write-Host "cloudflared is now available in this shell via alias." -ForegroundColor Green
Write-Host "Resolved path: $exe"

if ($PersistProfile) {
    if (-not (Test-Path $PROFILE)) {
        New-Item -ItemType File -Path $PROFILE -Force | Out-Null
    }

    $line = "Set-Alias -Name cloudflared -Value '$exe' -Scope Global"
    $content = Get-Content -Path $PROFILE -Raw -ErrorAction SilentlyContinue
    if ($content -notmatch [Regex]::Escape($line)) {
        Add-Content -Path $PROFILE -Value "`n$line"
        Write-Host "Added cloudflared alias to profile: $PROFILE" -ForegroundColor Green
    } else {
        Write-Host "Profile already contains cloudflared alias." -ForegroundColor Yellow
    }
}

& $exe --version
