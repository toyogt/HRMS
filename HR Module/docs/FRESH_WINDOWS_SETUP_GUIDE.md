# HRMS Middleware Fresh Windows Setup Guide

This guide is for setting up the middleware on a brand-new Windows laptop/PC from scratch.

For the simplest Windows 10 forever install, use [WINDOWS10_FOREVER_INSTALL_GUIDE.md](WINDOWS10_FOREVER_INSTALL_GUIDE.md).

## 1) Install Required Software

Install these first:

1. Python 3.11+ (check **Add Python to PATH** during install)
2. Git for Windows
3. Microsoft Visual C++ Redistributable (latest x64)

Verify in PowerShell:

```powershell
python --version
git --version
```

## 2) Download the Project

```powershell
cd "<folder where you want to keep the project>"
git clone <YOUR_REPO_URL> "20211204-SBXPC-1"
cd "20211204-SBXPC-1\HR Module"
```

## 3) Run One-Time Setup (Recommended)

Run PowerShell as **Administrator**, then:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\RUN_FOREVER_ONCE.cmd -EnableCloudflareTunnel
```

What this does:
- Creates/uses `.venv`
- Rebuilds `.venv` automatically if it was copied from another PC or points to Microsoft Store Python
- Installs Python dependencies
- Starts gateway/worker (and optional webhook dispatcher if configured)
- Creates scheduled task: `HRMS-Middleware-Supervisor`
- Starts cloudflared quick tunnel (if enabled)

## 4) Configure Port and Keys

Edit [`configs/dev.yaml`](/c:/Users/USER/Downloads/20211204-SBXPC-1/HR%20Module/configs/dev.yaml):

- `api_port`: middleware port (example `9100` or `9001`)
- `middleware_api_key`
- `middleware_bearer_token`
- `agent_api_key` and `agent_secret`
- `cors_allowed_origins`

If you change port, restart the supervisor task or rerun the start command.

## 5) Check App Health

Use these checks:

```powershell
.\scripts\status.ps1 -Port 9100
```

```powershell
curl.exe http://127.0.0.1:9100/health
curl.exe http://127.0.0.1:9100/api/v1/health
```

Expected: HTTP `200 OK`.

## 6) Get Cloudflare Public URL

Quick tunnel URL is logged here:

```text
var\logs\cloudflared.log
var\logs\cloudflared.err.log
```

Read latest URL:

```powershell
Get-Content .\var\logs\cloudflared.log -Tail 80
```

Look for a `https://*.trycloudflare.com` URL.

## 7) Verify Auto-Start After Reboot

Open `taskschd.msc` and check:

- Task name: `HRMS-Middleware-Supervisor`
- Status: `Running` (after startup)
- Trigger: At startup or at logon (as configured)

From terminal:

```powershell
schtasks /Query /TN "HRMS-Middleware-Supervisor" /V /FO LIST
```

## 8) Manual Start (Without Forever Script)

If you want to run directly:

```powershell
.\.venv\Scripts\python.exe scripts\run_gateway.py --config configs\dev.yaml
```

New terminal:

```powershell
.\.venv\Scripts\python.exe scripts\run_worker.py --config configs\dev.yaml
```

Optional third terminal:

```powershell
.\.venv\Scripts\python.exe scripts\run_webhook_dispatch.py --config configs\dev.yaml
```

Optional tunnel terminal:

```powershell
cloudflared tunnel --url http://127.0.0.1:9100
```

## 9) If `cloudflared` Command Is Not Found

Run helper:

```powershell
.\scripts\fix_cloudflared_command.ps1
```

Or start tunnel via helper:

```powershell
.\scripts\start_cloudflare_tunnel.ps1 -LocalPort 9100
```

## 10) Common Troubleshooting

1. Health returns `404`:
- Use `/health` or `/api/v1/health` (not `/v1/health`).

2. Port not listening:
- Check `api_port` in config and rerun gateway.
- Check port:
```powershell
netstat -ano | findstr :9100
```

3. Tunnel URL opens but API fails:
- Verify local health first.
- Verify middleware auth headers (`x-api-key` or `Authorization: Bearer ...`).

4. Task exists but not running:
- Start manually in Task Scheduler.
- Check logs in `var\logs\`.

---

If you want production-grade setup next, use a named Cloudflare tunnel token and restrict CORS to your final web app domain.
