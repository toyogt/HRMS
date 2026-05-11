# Attendance Relay Runbook

## 1. Overview

This service receives biometric punch events and relays each deduplicated event to a third-party HTTPS API using JSON `POST`.

Delivery guarantees:

- Outbox is source-of-truth for delivery state.
- Dedup uses stable SHA-256 hash over `employee_code|log_datetime|log_time|device_sn`.
- Retry uses exponential backoff + jitter up to `max_retries=5`.
- Stale `PROCESSING` rows are recoverable through lease-based reclaim.

## 2. Prerequisites

- Python 3.11+
- SQL Server (for stage/prod) or SQLite (for local dev)
- `pip install -r requirements.txt`

## 3. Config

Config files:

- `configs/dev.yaml`
- `configs/stage.yaml`
- `configs/prod.yaml`

Sensitive keys must come from environment variable overrides:

- `ATT_RELAY_OUTBOUND_API_KEY`
- `ATT_RELAY_DB_URL`
- `ATT_RELAY_MIDDLEWARE_API_KEY`
- `ATT_RELAY_AGENT_API_KEY`
- `ATT_RELAY_AGENT_JWT_TOKEN`
- `ATT_RELAY_WEBHOOK_HMAC_SECRET`

Example override:

```bash
set ATT_RELAY_OUTBOUND_API_KEY=your-secret-key
set ATT_RELAY_DB_URL=mssql+pyodbc://USER:PASSWORD@SERVER/DBNAME?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no
```

## 4. SQL Deployment (Stage/Prod)

Run scripts in order:

1. `sql/001_outbox_schema.sql`
2. `sql/002_trigger_tbl_realtime_glog_to_outbox.sql`
3. `sql/003_operational_queries.sql` (reference queries, not migration-critical)
4. `sql/004_employee_master_schema.sql`

If `tbl_realtime_glog` column names differ from `user_id`, `io_time`, `dev_id`, update `sql/002_*` mapping accordingly.

## 5. Start Commands

Ingestion API:

```bash
python scripts/run_ingress.py --config configs/stage.yaml
```

Middleware gateway API (ingress + machine control endpoints):

```bash
python scripts/run_gateway.py --config configs/stage.yaml
```

Relay worker:

```bash
python scripts/run_worker.py --config configs/stage.yaml
```

Direct listener (fast test mode, independent of SQL/IIS):

```bash
python scripts/run_direct_listener.py --config configs/dev.yaml
```

Import employee master CSV:

```bash
python scripts/import_master_csv.py --config configs/dev.yaml --csv "c:/Users/DELL/Downloads/TotalEmployee.csv"
```

Push employee master rows to attendance machine (SDK):

```bash
# Optional dry-run preview
python scripts/push_machine_users.py --config configs/dev.yaml --machine-ip 192.168.1.224 --dry-run

# Real sync
python scripts/push_machine_users.py --config configs/dev.yaml --machine-ip 192.168.1.224
```

## 6. Fast Machine Test (High Priority Path)

Start direct listener:

```bash
python scripts/run_direct_listener.py --config configs/dev.yaml
```

Point machine (or simulator) to:

`http://<host>:8010/machine/realtime_glog`

Expected:

- HTTP 200
- Header `response_code: OK`
- Body `response_code=OK`
- JSONL records at `var/direct_listener/punches.jsonl`

Simulate 10 events:

```bash
python scripts/simulate_machine_posts.py --url http://127.0.0.1:8010/machine/realtime_glog --csv TotalEmployee.csv --count 10
```

## 7. Full End-to-End Test

Automated local E2E:

```bash
python scripts/run_e2e.py --events 10 --duplicates 2
```

The report includes:

- Sent-to-ingress count
- Receiver accepted count
- Outbox status counts
- Expected non-duplicate sent count
- Pass/fail flag

## 8. Verification Queries

Outbox status totals:

```sql
SELECT status, COUNT(*) AS total
FROM dbo.attendance_outbox
GROUP BY status;
```

Due/stuck rows:

```sql
SELECT TOP (100) *
FROM dbo.attendance_outbox
WHERE status IN ('PENDING', 'PROCESSING')
ORDER BY next_attempt_at, id;
```

Failed events:

```sql
SELECT TOP (100)
  id, employee_code, log_datetime, device_sn,
  attempt_count, max_retries, last_error, updated_at
FROM dbo.attendance_outbox
WHERE status = 'FAILED'
ORDER BY updated_at DESC;
```

## 9. Troubleshooting

`decode error` from ingestion:

- Capture payload in direct listener mode.
- Confirm incoming fields contain `user_id`, `io_time`, `dev_id`.
- Validate `io_time` format: `YYYYMMDDhhmmss`.

Rows stuck in `PROCESSING`:

- Confirm worker is running and lease timeout values are sane.
- Use `sql/003_operational_queries.sql` stale recovery statement.

No outbound sends:

- Confirm `outbound_url` is HTTPS.
- Confirm `outbound_api_key` exists.
- Check worker health file at `var/worker/health.json`.

High failure rate:

- Check destination API response body/status.
- Confirm header name (`x-api-key` by default) matches receiver expectation.
- Increase timeout and backoff settings if needed.

## 10. Health Endpoints and Files

- Ingestion health: `GET /health`
- Attendance dashboard: `GET /dashboard`
- Attendance JSON API: `GET /api/attendances`
- Middleware health: `GET /api/v1/health`
- Device registry: `POST/GET/PATCH /api/v1/devices`
- Command queue: `POST /api/v1/commands`, `GET /api/v1/commands`
- Agent heartbeat: `POST /api/v1/agent/heartbeat`
- Agent attendance ingest: `POST /api/v1/agent/attendance/batch`
- Agent command claim/result: `POST /api/v1/agent/commands/claim`, `POST /api/v1/agent/commands/{command_id}/result`
- Webhook subscriptions: `POST/GET /api/v1/webhooks/subscriptions`
- Webhook dispatcher: `POST /api/v1/webhooks/dispatch`
- Machine connection test: `POST /api/machine/test-connection`
- Machine sync (HRMS -> machine): `POST /api/machine/employees/sync`
- Machine employee update: `PUT /api/machine/employees/{employee_code}`
- Machine employee enable: `POST /api/machine/employees/{employee_code}/enable`
- Machine employee disable: `POST /api/machine/employees/{employee_code}/disable`
- Direct listener health: `GET /health`
- Worker runtime health file: `var/worker/health.json`

## 11. Machine Sync Notes

- SDK DLL default path: `sdk_extracted/20211204-SBXPC-1/bin/SBXPCDLL64.dll`
- Default connection values from SDK sample:
  - `machine_sync_port=5005`
  - `machine_sync_password=0`
  - `machine_sync_machine_number=1`
- `employee_code` must resolve to numeric user ID for machine sync.
- `card_no` / `proximity_card_no` are used when present; otherwise user ID is used as card fallback.
