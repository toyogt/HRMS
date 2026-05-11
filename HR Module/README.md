# Attendance Integration Relay

Version `1.0.0` reliable biometric attendance ingestion and outbox relay service with:

- Realtime machine ingestion endpoint (`request_code: realtime_glog`)
- Built-in attendance dashboard (`/dashboard`)
- Payload decode + mapping to outbound schema
- SQL outbox pattern with deterministic dedup hash
- HTTPS + POST only outbound delivery with API key header
- Employee master-data import from CSV for enriched outbound payloads
- Exponential retry with jitter and max retry cap
- Direct listener mode for fast machine payload inspection
- CSV-driven machine simulator and end-to-end test runner

## Current Features

- Device registry APIs with editable IP/port/protocol (`/api/v1/devices`)
- Employee profile CRUD APIs with list/read/update/delete (`/api/v1/employees`)
- Agent heartbeat + attendance batch ingestion APIs (`/api/v1/agent/*`)
- Command queue APIs for HRMS-to-machine operations (`/api/v1/commands*`)
- Webhook subscriptions, dispatch, retry, and dead-letter handling (`/api/v1/webhooks/*`)
- Direct machine APIs for sync/update/enable/disable (`/api/machine/*`)
- Machine employee creation now creates a missing card enrollment record before applying name/card policy
- Built-in attendance dashboard (`/dashboard`) and health endpoints
- Local Windows supervisor scripts for auto-restart and boot-start

## Project Structure

- `src/attendance_relay/`: app code
- `sql/`: SQL Server migration + trigger + operations scripts
- `configs/`: dev/stage/prod YAML templates
- `scripts/`: runnable entry scripts
- `tests/`: unit tests
- `RUNBOOK.md`: deployment and troubleshooting guide

## One-File Install (Recommended)

Run this single file on the target local PC:

```powershell
powershell -ExecutionPolicy Bypass -File .\INSTALL_ONE_CLICK.ps1 -Config configs/dev.yaml
```

Or just double-click:

```text
INSTALL_ONE_CLICK.cmd
```

This will:

- Install missing system prerequisites automatically:
  - Python 3.11
  - Microsoft Visual C++ Runtime (x64)
  - ODBC Driver 18 for SQL Server (auto when config uses `mssql+pyodbc`)
- Create virtual environment
- Install all dependencies
- Install package in editable mode
- Open firewall for port `9100` (when elevated)
- Register auto-start task on boot (when elevated)
- Start middleware stack now (gateway + worker + webhook dispatch loop)

Optional flags:

```powershell
# Force SQL Server prerequisites even on dev config
powershell -ExecutionPolicy Bypass -File .\INSTALL_ONE_CLICK.ps1 -Config configs/dev.yaml -InstallSqlServerPrereqs

# Skip prereq installer (if machine is already prepared)
powershell -ExecutionPolicy Bypass -File .\INSTALL_ONE_CLICK.ps1 -Config configs/dev.yaml -SkipPrereqInstall

# Install and keep the app running forever, including a Cloudflare quick tunnel
powershell -ExecutionPolicy Bypass -File .\INSTALL_ONE_CLICK.ps1 -Config configs/dev.yaml -EnableCloudflareTunnel

# Same, but with a permanent Cloudflare named tunnel token from the Cloudflare dashboard
powershell -ExecutionPolicy Bypass -File .\INSTALL_ONE_CLICK.ps1 -Config configs/dev.yaml -EnableCloudflareTunnel -CloudflareToken "<TOKEN>"
```

Status check:

```powershell
.\scripts\status.ps1
```

The boot task runs `scripts/run_stack_forever.ps1`, which restarts the gateway, worker, webhook dispatcher, and optional Cloudflare tunnel if they close. Logs are written to `var\logs\`.

## Quick Start

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
```

## Install On Local LAN PC (Windows)

Use this when your PC is on the same network as the biometric machine.

```powershell
git clone <YOUR_REPO_URL>
cd <YOUR_REPO_FOLDER>
.\scripts\install_local_pc.ps1 -Config configs/dev.yaml
.\scripts\start_local_gateway.ps1 -Config configs/dev.yaml -OpenFirewall
```

Start worker in another terminal:

```powershell
.\.venv\Scripts\python.exe scripts/run_worker.py --config configs/dev.yaml
```

Run ingestion API:

```bash
python scripts/run_ingress.py --config configs/dev.yaml

# Open dashboard:
# http://127.0.0.1:9100/dashboard
```

Run middleware gateway API (ingress + machine control):

```bash
python scripts/run_gateway.py --config configs/dev.yaml
```

Run relay worker:

```bash
python scripts/run_worker.py --config configs/dev.yaml
```

Run fast direct listener (no SQL dependency):

```bash
python scripts/run_direct_listener.py --config configs/dev.yaml
```

Import employee master CSV:

```bash
python scripts/import_master_csv.py --config configs/dev.yaml --csv "c:/Users/DELL/Downloads/TotalEmployee.csv"
```

Push HR employee master data to attendance machine (SDK):

```bash
# Optional dry run (no device call)
python scripts/push_machine_users.py --config configs/dev.yaml --machine-ip 192.168.1.224 --dry-run

# Real sync to machine
python scripts/push_machine_users.py --config configs/dev.yaml --machine-ip 192.168.1.224
```

Machine control APIs (for HRMS -> machine from same-network PC):

```bash
# Test SDK connection
curl -X POST http://127.0.0.1:9100/api/machine/test-connection -H "Content-Type: application/json" -d "{}"

# Dry-run employee sync preview
curl -X POST http://127.0.0.1:9100/api/machine/employees/sync -H "Content-Type: application/json" -d "{\"dry_run\":true}"

# Real employee sync
curl -X POST http://127.0.0.1:9100/api/machine/employees/sync -H "Content-Type: application/json" -d "{\"machine_ip\":\"192.168.29.98\"}"

# Read all users currently present on the biometric machine
curl -X POST http://127.0.0.1:9100/api/machine/employees/read-all -H "Content-Type: application/json" -d "{\"machine_ip\":\"192.168.29.98\",\"include_user_names\":true}"

# Update one employee on machine
curl -X PUT http://127.0.0.1:9100/api/machine/employees/E1001 -H "Content-Type: application/json" -d "{\"user_name\":\"Test User\",\"enable\":true}"

# Disable/enable one employee punch
curl -X POST http://127.0.0.1:9100/api/machine/employees/E1001/disable -H "Content-Type: application/json" -d "{}"
curl -X POST http://127.0.0.1:9100/api/machine/employees/E1001/enable -H "Content-Type: application/json" -d "{}"
```

HRMS middleware APIs (`/api/v1`) for cloud + agent workflow:

```bash
# Middleware headers
# x-api-key: <middleware_api_key>
#
# Agent headers
# x-api-key: <agent_api_key>
# Authorization: Bearer <agent_jwt_token>

# Register/patch device
curl -X POST http://127.0.0.1:9100/api/v1/devices -H "x-api-key: dev-middleware-key" -H "Content-Type: application/json" -d "{\"device_id\":\"FACTORY_T501_01\",\"ip\":\"192.168.29.98\",\"port\":5005,\"sdk_protocol\":\"sbxpc_tcp\"}"
curl -X PATCH http://127.0.0.1:9100/api/v1/devices/FACTORY_T501_01 -H "x-api-key: dev-middleware-key" -H "Content-Type: application/json" -d "{\"ip\":\"192.168.29.120\"}"

# Create/list/read/update employee profiles
curl -X POST http://127.0.0.1:9100/api/v1/employees -H "x-api-key: dev-middleware-key" -H "Content-Type: application/json" -d "{\"employee_code\":\"E1001\",\"employee_name\":\"Test User\",\"card_no\":\"9001001\",\"department\":\"IT\"}"
curl -X GET http://127.0.0.1:9100/api/v1/employees -H "x-api-key: dev-middleware-key"
curl -X GET http://127.0.0.1:9100/api/v1/employees/E1001 -H "x-api-key: dev-middleware-key"
curl -X PATCH http://127.0.0.1:9100/api/v1/employees/E1001 -H "x-api-key: dev-middleware-key" -H "Content-Type: application/json" -d "{\"designation\":\"Engineer\"}"

# Queue command from HRMS
curl -X POST http://127.0.0.1:9100/api/v1/commands -H "x-api-key: dev-middleware-key" -H "Content-Type: application/json" -d "{\"request_id\":\"req-001\",\"device_id\":\"FACTORY_T501_01\",\"command_type\":\"employee.enable\",\"payload\":{\"employee_code\":\"EMP001\"}}"

# Agent claims commands
curl -X POST http://127.0.0.1:9100/api/v1/agent/commands/claim -H "x-api-key: dev-agent-key" -H "Authorization: Bearer dev-agent-jwt" -H "Content-Type: application/json" -d "{\"agent_id\":\"AGENT_PLANT_A\",\"device_ids\":[\"FACTORY_T501_01\"],\"limit\":10}"

# Agent pushes attendance batch
curl -X POST http://127.0.0.1:9100/api/v1/agent/attendance/batch -H "x-api-key: dev-agent-key" -H "Authorization: Bearer dev-agent-jwt" -H "Content-Type: application/json" -d "{\"agent_id\":\"AGENT_PLANT_A\",\"events\":[{\"employee_code\":\"EMP001\",\"device_id\":\"FACTORY_T501_01\",\"timestamp_local\":\"2026-05-05 09:30:00\",\"timezone\":\"Asia/Kolkata\"}]}"

# Webhook subscription + manual dispatch
curl -X POST http://127.0.0.1:9100/api/v1/webhooks/subscriptions -H "x-api-key: dev-middleware-key" -H "Content-Type: application/json" -d "{\"event_type\":\"attendance.created\",\"target_url\":\"https://example.com/hrms-webhook\"}"
curl -X POST http://127.0.0.1:9100/api/v1/webhooks/dispatch -H "x-api-key: dev-middleware-key" -H "Content-Type: application/json" -d "{\"limit\":50}"
```

Run local agent mock (heartbeat + claim + optional success callback):

```bash
python scripts/run_agent_mock.py --base-url http://127.0.0.1:9100 --agent-id AGENT_PLANT_A --device-ids FACTORY_T501_01 --api-key dev-agent-key --jwt-token dev-agent-jwt --mock-execute
```

Disable autostart later (optional):

```powershell
.\scripts\remove_autostart.ps1
```

Notes:

- SDK DLL defaults to `sdk_extracted/20211204-SBXPC-1/bin/SBXPCDLL64.dll`.
- Default network settings from SDK sample are `port=5005`, `password=0`, `machine_number=1`.
- `employee_code` must be numeric (or normalize to numeric) for machine user ID sync.
- If `card_no` is missing, the sync uses employee user ID as card fallback.

Simulate machine punches from `TotalEmployee.csv`:

```bash
python scripts/simulate_machine_posts.py --url http://127.0.0.1:8010/machine/realtime_glog --csv TotalEmployee.csv --count 10
```

Run automated E2E:

```bash
python scripts/run_e2e.py --events 10 --duplicates 2
```
