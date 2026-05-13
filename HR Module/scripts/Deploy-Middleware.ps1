<#
.SYNOPSIS
  Incremental update for an already-set-up HRMS middleware PC.

.DESCRIPTION
  - git pull the latest code on `develop`.
  - Re-install Python deps if requirements.txt changed.
  - Re-download + extract the SBXPC SDK only if SBXPCDLL64.dll is missing.
  - Restart the supervisor, run /health, run /api/machine/test-connection.

.PARAMETER SdkPath
  Optional. Local path (zip or extracted folder) to recover the SDK from when
  it is missing. Takes precedence over -SdkUrl.

.PARAMETER SdkUrl
  Optional. URL to fetch the SDK from when it is missing and no -SdkPath was
  given. If both are omitted and the SDK is missing, this script just warns.

.PARAMETER InstallPath
  Root folder of the repo. Default: C:\HRMS_Middleware.

.PARAMETER Branch
  Git branch to track. Default: develop.

.EXAMPLE
  PS> .\Deploy-Middleware.ps1
  PS> .\Deploy-Middleware.ps1 -SdkPath "D:\sdk_BIN_ONLY.zip"
  PS> .\Deploy-Middleware.ps1 -SdkUrl  "https://drive.google.com/file/d/<FILE_ID>/view"
#>
param(
  [string]$SdkPath,
  [string]$SdkUrl,
  [string]$InstallPath = "C:\HRMS_Middleware",
  [string]$Branch      = "develop",
  [string]$ApiKey      = "dev-middleware-key"
)

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


$Repo    = Join-Path $InstallPath "HRMS"
$Project = Join-Path $Repo "HR Module"

if (-not (Test-Path (Join-Path $Repo ".git"))) {
  throw "Repo not found at $Repo. Run Setup-Middleware-PC.ps1 first."
}


Write-Step 1 "Stop middleware"

Stop-ScheduledTask -TaskName "HRMS-Middleware-Supervisor" -ErrorAction SilentlyContinue
Get-Process -Name pythonw,python -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -and $_.Path -like "*HRMS*" } |
  Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "  stopped"


Write-Step 2 "git pull"

Push-Location $Repo
$beforeReq = if (Test-Path (Join-Path $Project "requirements.txt")) {
  (Get-FileHash (Join-Path $Project "requirements.txt") -Algorithm SHA1).Hash
} else { "" }

git fetch origin
git checkout $Branch
git pull --ff-only origin $Branch

$afterReq = if (Test-Path (Join-Path $Project "requirements.txt")) {
  (Get-FileHash (Join-Path $Project "requirements.txt") -Algorithm SHA1).Hash
} else { "" }
Pop-Location

git -C $Repo log -1 --pretty=format:"  HEAD = %h %s (%an, %ar)"
Write-Host ""


Write-Step 3 "Update Python deps if requirements.txt changed"

if ($beforeReq -ne $afterReq) {
  Write-Host "  requirements.txt changed, reinstalling..."
  $py = Join-Path $Project ".venv\Scripts\python.exe"
  if (Test-Path $py) {
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet -r (Join-Path $Project "requirements.txt")
  } else {
    Write-Host "  .venv not found -- run Setup-Middleware-PC.ps1 first." -ForegroundColor Red
    exit 1
  }
} else {
  Write-Host "  no changes"
}


Write-Step 4 "Ensure SDK present"

$targetDll = Join-Path $Project "sdk_extracted\20211204-SBXPC-1\bin\SBXPCDLL64.dll"
$sdkRoot   = Join-Path $Project "sdk_extracted"

if (Test-Path $targetDll) {
  Write-Host "  SDK already in place ($targetDll)" -ForegroundColor Green
} elseif ($SdkPath) {
  if (-not (Test-Path $SdkPath)) { throw "-SdkPath '$SdkPath' does not exist." }
  $item = Get-Item $SdkPath
  if ($item.PSIsContainer) {
    $source = Get-ChildItem $item.FullName -Recurse -Filter "SBXPCDLL64.dll" -ErrorAction SilentlyContinue |
              Select-Object -First 1
    if (-not $source) { throw "Folder '$SdkPath' has no SBXPCDLL64.dll." }
    $destBin = Join-Path $sdkRoot "20211204-SBXPC-1\bin"
    New-Item -ItemType Directory -Path $destBin -Force | Out-Null
    Copy-Item (Join-Path (Split-Path $source.FullName -Parent) "*") $destBin -Recurse -Force
  } else {
    Expand-Archive -Path $item.FullName -DestinationPath $Project -Force
  }
  if (-not (Test-Path $targetDll)) { throw "Placed SDK but SBXPCDLL64.dll is not at $targetDll." }
  Write-Host "  installed from local: $targetDll" -ForegroundColor Green
} elseif ($SdkUrl) {
  Write-Host "  SDK missing -- downloading..."
  $sdkZip   = Join-Path $env:TEMP "sdk_BIN_ONLY.zip"
  if (Test-Path $sdkZip) { Remove-Item $sdkZip -Force }
  $download = Resolve-DownloadUrl $SdkUrl
  Invoke-WebRequest -Uri $download -OutFile $sdkZip -UseBasicParsing

  if ((Get-Item $sdkZip).Length -lt 200KB) {
    $head = Get-Content -LiteralPath $sdkZip -TotalCount 1
    if ($head -match "<html|<!DOCTYPE") {
      throw "Download was a Google Drive HTML page. Check share permissions."
    }
  }
  Expand-Archive -Path $sdkZip -DestinationPath $Project -Force
  Remove-Item $sdkZip -Force
  if (-not (Test-Path $targetDll)) { throw "Extract done but SBXPCDLL64.dll missing at $targetDll." }
  Write-Host "  extracted OK -> $targetDll" -ForegroundColor Green
} else {
  Write-Host "  SDK is missing and no -SdkPath / -SdkUrl provided." -ForegroundColor Yellow
  Write-Host "  Re-run with one of:"
  Write-Host "    .\Deploy-Middleware.ps1 -SdkPath 'D:\sdk_BIN_ONLY.zip'"
  Write-Host "    .\Deploy-Middleware.ps1 -SdkUrl  'https://drive.google.com/file/d/<id>/view'"
}


Write-Step 5 "Restart middleware"

Start-ScheduledTask -TaskName "HRMS-Middleware-Supervisor"

$ok = $false
for ($i = 1; $i -le 20; $i++) {
  try {
    $resp = Invoke-RestMethod http://127.0.0.1:9100/health -TimeoutSec 2
    Write-Host ("  ready after {0}s: {1}" -f ($i*2), ($resp | ConvertTo-Json -Compress)) -ForegroundColor Green
    $ok = $true; break
  } catch { Start-Sleep -Seconds 2 }
}
if (-not $ok) {
  Write-Host "  /health did not respond after 40s; check var/logs/gateway.err.log." -ForegroundColor Red
  exit 1
}


Write-Step 6 "Sanity check: device test-connection"

$bodyFile = Join-Path $env:TEMP "tc.json"
Set-Content -LiteralPath $bodyFile -Value '{"device_id":"DEV-LIVE-01"}' -Encoding ascii -NoNewline

$tc = curl.exe -s --max-time 15 `
        -X POST `
        -H "x-api-key: $ApiKey" `
        -H "Content-Type: application/json" `
        --data-binary "@$bodyFile" `
        "http://127.0.0.1:9100/api/machine/test-connection"
Write-Host "  $tc"

Write-Host ""
Write-Host "Deploy complete." -ForegroundColor Green
