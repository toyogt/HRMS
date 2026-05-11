param(
    [int]$LocalPort = 0,
    [string]$Config = "configs/dev.yaml",
    [string]$CloudflareToken = "",
    [switch]$PersistUserPath
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

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

function Resolve-Cloudflared {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $candidates = @(
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
    )
    foreach ($path in $candidates) {
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

    throw "cloudflared.exe not found. Install it with: winget install --id Cloudflare.cloudflared -e"
}

$effectiveLocalPort = if ($LocalPort -gt 0) { $LocalPort } else { Get-ConfiguredIngressPort -ConfigPath $Config }

$cloudflaredExe = Resolve-Cloudflared
$cloudflaredDir = Split-Path -Parent $cloudflaredExe

# Always fix PATH in the current shell so this terminal can run `cloudflared`.
if (($env:Path -split ';') -notcontains $cloudflaredDir) {
    $env:Path = ($env:Path.TrimEnd(';') + ';' + $cloudflaredDir).Trim(';')
}

if ($PersistUserPath) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($userPath -split ';') -notcontains $cloudflaredDir) {
        [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(';') + ';' + $cloudflaredDir).Trim(';'), "User")
        Write-Host "Updated user PATH with $cloudflaredDir"
        Write-Host "Open a new terminal to use `cloudflared` globally."
    }
}

Write-Host "Using cloudflared: $cloudflaredExe"

if ($CloudflareToken) {
    & $cloudflaredExe tunnel run --token $CloudflareToken
} else {
    & $cloudflaredExe tunnel --url "http://127.0.0.1:$effectiveLocalPort"
}
