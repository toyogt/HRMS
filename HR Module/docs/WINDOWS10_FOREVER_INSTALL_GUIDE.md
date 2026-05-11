# Windows 10 Forever Install Guide

Use this guide when installing the HRMS middleware on another Windows 10 PC.

## Goal

After setup:

- The API runs on the configured port, usually `9100`.
- The app starts automatically after PC restart.
- If gateway/worker/cloudflared exits, the supervisor restarts it.
- Cloudflare Tunnel exposes the local API to the internet if enabled.
- Logs are stored under `var\logs`.

## Recommended Folder

Put the project in a stable local folder, for example:

```text
C:\HRMS-Middleware
```

Avoid running forever from temporary folders, network drives, or removable USB drives.

## One-Click Windows 10 Install

Right-click **Command Prompt** and select **Run as administrator**.

Then run:

```cmd
cd /d "C:\HRMS-Middleware"
INSTALL_WINDOWS10_FOREVER.cmd
```

This default command enables a Cloudflare quick tunnel.

To install without Cloudflare:

```cmd
INSTALL_WINDOWS10_FOREVER.cmd -NoCloudflareTunnel
```

To use a permanent Cloudflare tunnel token:

```cmd
INSTALL_WINDOWS10_FOREVER.cmd -CloudflareToken "YOUR_CLOUDFLARE_TUNNEL_TOKEN"
```

## What The Installer Does

1. Relaunches as Administrator if needed.
2. Installs/checks prerequisites with `winget`.
3. Uses stable Python 3.11+ from the current PC.
4. Rebuilds `.venv` if it was copied from another PC or uses Microsoft Store `WindowsApps` Python.
5. Installs Python packages.
6. Opens Windows Firewall for the configured middleware port.
7. Creates/updates Scheduled Task `HRMS-Middleware-Supervisor`.
8. Starts gateway, worker, webhook dispatcher loop, and optional Cloudflare tunnel.
9. Runs health checks.
10. Writes installer logs to `var\logs\windows10_install_forever.log`.

## Check If It Is Working

Run:

```cmd
CHECK_WINDOWS10_APP.cmd
```

Manual checks:

```cmd
curl.exe http://127.0.0.1:9100/health
curl.exe http://127.0.0.1:9100/docs
```

Open Task Scheduler:

```text
taskschd.msc
```

Look for:

```text
HRMS-Middleware-Supervisor
```

The app usually does not appear in `services.msc` because it runs as a Scheduled Task, not a Windows Service.

## Important Config Values

Edit `configs\dev.yaml` before final install if needed:

```yaml
ingress_port: 9100
middleware_api_key: "dev-middleware-key"
middleware_bearer_token: "dev-middleware-token"
machine_sync_port: 5005
machine_sync_password: 0
machine_sync_machine_number: 1
```

For production, replace dev API keys and restrict CORS.

## Cloudflare URL

Quick tunnel URL is shown by:

```cmd
CHECK_WINDOWS10_APP.cmd
```

It is also stored in:

```text
var\logs\cloudflared.log
var\logs\cloudflared.err.log
```

Quick tunnel URLs can change after restart. Use a permanent Cloudflare named tunnel for production.

## Troubleshooting

If health fails:

```cmd
CHECK_WINDOWS10_APP.cmd
```

Then inspect:

```text
var\logs\gateway.err.log
var\logs\worker.err.log
var\logs\cloudflared.err.log
var\logs\windows10_install_forever.log
```

If the app does not start after reboot, rerun the installer as Administrator:

```cmd
INSTALL_WINDOWS10_FOREVER.cmd
```
