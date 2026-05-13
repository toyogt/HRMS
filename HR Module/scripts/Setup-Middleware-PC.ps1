<#
.SYNOPSIS
  One-shot setup for an HRMS middleware PC.

.DESCRIPTION
  - Clones the repo from GitHub (or pulls the latest if already cloned).
  - Runs INSTALL_ONE_CLICK to create the venv, install Python deps, and register
    the supervisor scheduled task.
  - Downloads the SBXPC SDK zip from the provided URL (Google Drive direct or
    any HTTPS URL) and extracts it into HR Module/sdk_extracted/.
  - Restarts the supervisor and runs a health + device test-connection check.

.PARAMETER SdkPath
  Local path to the SBXPC SDK zip on disk (e.g. a USB, a network share, or
  the file copied next to this script). Preferred over -SdkUrl when both are
  given. The path can be a .zip OR an already-extracted folder that
  contains "20211204-SBXPC-1\bin\SBXPCDLL64.dll".

.PARAMETER SdkUrl
  HTTPS URL to the SBXPC SDK zip (sdk_BIN_ONLY.zip).
  Accepts both Google Drive share links and direct download links.
  Used only when -SdkPath is not provided.

.PARAMETER InstallPath
  Root folder where the repo will live. Default: C:\HRMS_Middleware.

.PARAMETER Branch
  Git branch to track. Default: develop.

.PARAMETER ApiKey
  API key used to call /api/v1/health and /api/machine/test-connection.
  Default: dev-middleware-key.

.PARAMETER EnableCloudflareTunnel
  Pass to also install + start a Cloudflare quick tunnel.

.EXAMPLE
  # Local zip (no internet for the SDK):
  PS> .\Setup-Middleware-PC.ps1 -SdkPath "D:\sdk_BIN_ONLY.zip" -EnableCloudflareTunnel

.EXAMPLE
  # Google Drive URL:
  PS> .\Setup-Middleware-PC.ps1 -SdkUrl "https://drive.google.com/file/d/<FILE_ID>/view?usp=sharing"
#>
param(
  [string]$SdkPath,
  [string]$SdkUrl,

  [string]$InstallPath = "C:\HRMS_Middleware",
  [string]$RepoUrl     = "https://github.com/toyogt/HRMS.git",
  [string]$Branch      = "develop",
  [string]$ApiKey      = "dev-middleware-key",
  [switch]$EnableCloudflareTunnel
)

if (-not $SdkPath -and -not $SdkUrl) {
  throw "You must provide either -SdkPath (local zip/folder) or -SdkUrl (download URL)."
}

$ErrorActionPreference = "Stop"

function Write-Step($n, $msg) {
  Write-Host ""
  Write-Host ("[{0}] {1}" -f $n, $msg) -ForegroundColor Cyan
  Write-Host ("-" * 70)
}

function Resolve-DownloadUrl([string]$url) {
  if ($url -match "drive\.google\.com/file/d/([^/]+)") {
    return "https://drive.google.com/uc?export=download&id=$($Matches[1])"
  }
  if ($url -match "drive\.google\.com/open\?id=([^&]+)") {
    return "https://drive.google.com/uc?export=download&id=$($Matches[1])"
  }
  return $url
}

function Get-FileFromUrl([string]$url, [string]$outPath) {
  $download = Resolve-DownloadUrl $url
  Write-Host "  downloading: $download"
  Invoke-WebRequest -Uri $download -OutFile $outPath -UseBasicParsing

  $size = (Get-Item $outPath).Length
  if ($size -lt 200KB) {
    $head = Get-Content -LiteralPath $outPath -TotalCount 1 -ErrorAction SilentlyContinue
    if ($head -match "<html|<!DOCTYPE") {
      throw "Downloaded file looks like HTML (Google Drive virus-scan page or 'access denied'). Make sure the share link is set to 'Anyone with the link can view'."
    }
  }
  Write-Host ("  size: {0:N2} MB" -f ($size / 1MB))
}


Write-Step 1 "Pre-flight checks"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "git is not on PATH. Install Git for Windows first: https://git-scm.com/download/win"
}
Write-Host "  git: OK"

if (-not (Test-Path $InstallPath)) {
  New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
}
Write-Host "  install path: $InstallPath"


Write-Step 2 "Clone or update the repository"

$Repo    = Join-Path $InstallPath "HRMS"
$Project = Join-Path $Repo "HR Module"

if (-not (Test-Path (Join-Path $Repo ".git"))) {
  Write-Host "  cloning $RepoUrl ..."
  Push-Location $InstallPath
  git clone -b $Branch $RepoUrl HRMS
  Pop-Location
} else {
  Write-Host "  repo exists -> pulling latest"
  Push-Location $Repo
  git fetch origin
  git checkout $Branch
  git pull --ff-only origin $Branch
  Pop-Location
}

Write-Host "  branch: $(Push-Location $Repo; git branch --show-current; Pop-Location)"


Write-Step 3 "Run INSTALL_ONE_CLICK (Python + venv + scheduled task)"

$installer = Join-Path $Project "INSTALL_ONE_CLICK.cmd"
if (-not (Test-Path $installer)) {
  throw "Cannot find $installer. Did the clone succeed?"
}

$installArgs = @()
if ($EnableCloudflareTunnel) { $installArgs += "-EnableCloudflareTunnel" }

Push-Location $Project
& $installer @installArgs
Pop-Location


Write-Step 4 "Obtain SBXPC SDK"

$targetDll = Join-Path $Project "sdk_extracted\20211204-SBXPC-1\bin\SBXPCDLL64.dll"
$sdkRoot   = Join-Path $Project "sdk_extracted"

$useLocal = $false
$localZip = $null

if ($SdkPath) {
  if (-not (Test-Path $SdkPath)) {
    throw "-SdkPath '$SdkPath' does not exist."
  }
  $useLocal = $true
  $item = Get-Item $SdkPath
  if ($item.PSIsContainer) {
    # already-extracted folder
    Write-Host "  using local folder: $($item.FullName)"
    $sourceDll = Get-ChildItem $item.FullName -Recurse -Filter "SBXPCDLL64.dll" -ErrorAction SilentlyContinue |
                 Select-Object -First 1
    if (-not $sourceDll) {
      throw "Folder '$SdkPath' does not contain SBXPCDLL64.dll anywhere inside it."
    }
    if (Test-Path $sdkRoot) {
      Write-Host "  removing stale $sdkRoot"
      Remove-Item -Recurse -Force $sdkRoot
    }
    $destBin = Join-Path $sdkRoot "20211204-SBXPC-1\bin"
    New-Item -ItemType Directory -Path $destBin -Force | Out-Null
    $binSource = Split-Path $sourceDll.FullName -Parent
    Copy-Item "$binSource\*" $destBin -Recurse -Force
    Write-Host "  copied $binSource -> $destBin"
  } else {
    Write-Host "  using local zip: $($item.FullName)"
    $localZip = $item.FullName
  }
} else {
  Write-Host "  downloading from URL..."
  $localZip = Join-Path $env:TEMP "sdk_BIN_ONLY.zip"
  if (Test-Path $localZip) { Remove-Item $localZip -Force }
  Get-FileFromUrl -url $SdkUrl -outPath $localZip
}

if ($localZip) {
  if (Test-Path $sdkRoot) {
    Write-Host "  removing stale $sdkRoot"
    Remove-Item -Recurse -Force $sdkRoot
  }
  Expand-Archive -Path $localZip -DestinationPath $Project -Force
  if (-not $useLocal) { Remove-Item $localZip -Force }
}


Write-Step 5 "Verify SDK landed at expected path"

if (Test-Path $targetDll) {
  $info = Get-Item $targetDll
  Write-Host ("  OK -> SBXPCDLL64.dll ({0:N2} MB)" -f ($info.Length / 1MB)) -ForegroundColor Green
} else {
  # Try to recover: maybe the zip has a different top-level folder
  $found = Get-ChildItem $sdkRoot -Recurse -Filter "SBXPCDLL64.dll" -ErrorAction SilentlyContinue |
           Select-Object -First 1
  if ($found) {
    Write-Host "  SBXPCDLL64.dll found at unexpected path: $($found.FullName)" -ForegroundColor Yellow
    $destBin = Join-Path $sdkRoot "20211204-SBXPC-1\bin"
    New-Item -ItemType Directory -Path $destBin -Force | Out-Null
    Copy-Item (Split-Path $found.FullName -Parent) $destBin -Recurse -Force
    if (Test-Path $targetDll) {
      Write-Host "  recovered -> $targetDll" -ForegroundColor Green
    } else {
      throw "Could not place SBXPCDLL64.dll at $targetDll."
    }
  } else {
    throw "SBXPCDLL64.dll not found in $sdkRoot. The zip/folder layout is wrong."
  }
}


Write-Step 6 "Restart the middleware"

Stop-ScheduledTask -TaskName "HRMS-Middleware-Supervisor" -ErrorAction SilentlyContinue
Get-Process -Name pythonw,python -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -and $_.Path -like "*HRMS*" } |
  Stop-Process -Force -ErrorAction SilentlyContinue

Start-ScheduledTask -TaskName "HRMS-Middleware-Supervisor"

Write-Host "  waiting for /health to come up..."
$ok = $false
for ($i = 1; $i -le 20; $i++) {
  try {
    $resp = Invoke-RestMethod http://127.0.0.1:9100/health -TimeoutSec 2
    Write-Host ("  ready after {0}s: {1}" -f ($i*2), ($resp | ConvertTo-Json -Compress)) -ForegroundColor Green
    $ok = $true; break
  } catch { Start-Sleep -Seconds 2 }
}
if (-not $ok) {
  Write-Host "  /health did not respond after 40s." -ForegroundColor Red
  Write-Host "  Check var/logs/gateway.err.log on this PC."
  exit 1
}


Write-Step 7 "Verify SDK + device reachability"

$body = '{"device_id":"DEV-LIVE-01"}'
$bodyFile = Join-Path $env:TEMP "tc.json"
Set-Content -LiteralPath $bodyFile -Value $body -Encoding ascii -NoNewline

$tc = curl.exe -s --max-time 15 `
        -X POST `
        -H "x-api-key: $ApiKey" `
        -H "Content-Type: application/json" `
        --data-binary "@$bodyFile" `
        "http://127.0.0.1:9100/api/machine/test-connection"
Write-Host "  test-connection response: $tc"

if ($tc -match '"connected"\s*:\s*true') {
  Write-Host ""
  Write-Host "==================================================" -ForegroundColor Green
  Write-Host "  Setup complete. Middleware + SDK + device OK." -ForegroundColor Green
  Write-Host "==================================================" -ForegroundColor Green
} elseif ($tc -match "SDK DLL not found") {
  Write-Host ""
  Write-Host "SDK extracted to wrong path. Investigate $($Project)\sdk_extracted\." -ForegroundColor Red
} elseif ($tc -match "Connection refused|timed out|timeout") {
  Write-Host ""
  Write-Host "SDK loaded, but device not reachable on LAN." -ForegroundColor Yellow
  Write-Host "Check: ping 192.168.29.44 from this PC."
} else {
  Write-Host ""
  Write-Host "Middleware up, but test-connection returned an unexpected result." -ForegroundColor Yellow
  Write-Host "Inspect the response above."
}

Write-Host ""
Write-Host "Cloudflare tunnel log (if enabled):"
$cf = Join-Path $Project "var\logs\cloudflared.log"
if (Test-Path $cf) {
  Get-Content $cf -Tail 12
} else {
  Write-Host "  (cloudflared.log not present)"
}
