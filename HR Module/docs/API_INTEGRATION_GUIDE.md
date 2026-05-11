# HRMS Middleware API Integration Guide

This guide is for frontend, backend, and deployment engineers integrating a web app with the local HRMS middleware through Cloudflare Tunnel.

The app runs locally on the PC that can reach the biometric machine. Cloudflare exposes that local API to the internet so a static website or backend server can call it.

For complete first-time Windows setup on a new laptop/PC, see [FRESH_WINDOWS_SETUP_GUIDE.md](FRESH_WINDOWS_SETUP_GUIDE.md).

## 1. Base URL and Port

Local base URL:

```text
http://127.0.0.1:9100
```

Cloudflare public base URL:

```text
https://<your-cloudflare-hostname>
```

Until a permanent hostname is configured, Cloudflare quick tunnel returns a temporary `trycloudflare.com` URL.

## 2. Cloudflare Tunnel Commands

Temporary quick tunnel:

```powershell
cloudflared tunnel --url http://127.0.0.1:9100
```

Permanent tunnel using a Cloudflare token:

```powershell
cloudflared tunnel run --token "YOUR_CLOUDFLARE_TUNNEL_TOKEN"
```

One-time installer that starts the middleware forever and starts a quick tunnel:

```powershell
.\RUN_FOREVER_ONCE.cmd -EnableCloudflareTunnel
```

One-time installer with a permanent Cloudflare token:

```powershell
.\RUN_FOREVER_ONCE.cmd -EnableCloudflareTunnel -CloudflareToken "YOUR_CLOUDFLARE_TUNNEL_TOKEN"
```

Check status:

```powershell
.\scripts\status.ps1
```

Quick tunnel public URL is written in:

```powershell
Get-Content .\var\logs\cloudflared.log -Tail 50
```

## 3. Browser and Static Website Notes

Because the future web app may be a static website, browser requests need CORS. The middleware now includes CORS support.

Current config allows all origins:

```yaml
cors_allowed_origins:
  - "*"
```

When the final website domain is known, restrict it:

```yaml
cors_allowed_origins:
  - "https://your-static-site.example.com"
```

Do not expose production credentials in static frontend code unless that is acceptable for your threat model. A safer production pattern is:

1. Static frontend calls your backend.
2. Your backend stores API secrets.
3. Your backend calls the middleware through Cloudflare.

Direct browser calls are possible, but anyone with access to the built static app can inspect browser-side tokens.

## 3A. Web HRMS Configuration Flow

The web HRMS should treat this middleware as the gateway between HRMS and physical biometric machines.

Recommended HRMS settings entities:

1. `HRMSGatewayURL`
```json
{
  "base_url": "https://your-cloudflare-or-local-url",
  "middleware_api_key": "dev-middleware-key",
  "auth_type": "x-api-key",
  "health_path": "/api/v1/health",
  "request_timeout_ms": 15000,
  "priority": 1,
  "is_active": true
}
```

2. `HRMSDevice`
```json
{
  "device_id": "DEV-LIVE-01",
  "display_name": "Main Gate Reader",
  "ip_address": "192.168.1.19",
  "port": 5005,
  "machine_number": 1,
  "machine_password": "0",
  "branch": "HQ",
  "timezone": "Asia/Kolkata",
  "is_active": true
}
```

When the web HRMS saves a device, it should call:

```http
POST {base_url}/api/v1/devices
x-api-key: {middleware_api_key}
Content-Type: application/json
```

Payload:

```json
{
  "device_id": "DEV-LIVE-01",
  "device_name": "Main Gate Reader",
  "site_id": "HQ",
  "ip": "192.168.1.19",
  "port": 5005,
  "machine_number": 1,
  "timezone": "Asia/Kolkata",
  "is_active": true,
  "sdk_protocol": "sbxpc_tcp",
  "machine_password": "0"
}
```

After that, employee sync calls should send only `device_id` instead of raw IP/port/password every time.

Create employee and sync to machine:

```http
POST {base_url}/api/v1/employees
x-api-key: {middleware_api_key}
Content-Type: application/json
```

```json
{
  "employee_code": "EMP001",
  "employee_name": "Test Employee",
  "card_no": "1001",
  "department": "IT",
  "designation": "Staff",
  "branch_name": "HQ",
  "machine": {
    "sync_to_machine": true,
    "device_id": "DEV-LIVE-01",
    "user_id": 1001,
    "user_name": "Test Employee",
    "card_no": "1001",
    "enable": true,
    "e_machine_number": 1,
    "backup_number": 0
  }
}
```

The middleware resolves `device_id` to saved `ip`, `port`, `machine_number`, and `machine_password`.

## 4. Authentication

### Middleware and Machine APIs

The following APIs accept either `x-api-key` or Bearer auth:

- `/api/v1/*`
- `/api/machine/*`

Header option 1:

```http
x-api-key: dev-middleware-key
```

Header option 2:

```http
Authorization: Bearer dev-middleware-token
```

Production values are configured in `configs/prod.yaml`:

```yaml
middleware_api_key: "replace-in-secret-store"
middleware_bearer_token: "replace-in-secret-store"
```

### Agent APIs

Agent APIs require both headers:

```http
x-api-key: dev-agent-key
Authorization: Bearer dev-agent-jwt
```

Agent endpoints:

- `/api/v1/agent/heartbeat`
- `/api/v1/agent/attendance/batch`
- `/api/v1/agent/commands/claim`
- `/api/v1/agent/commands/{command_id}/result`
- `/api/v1/agent/device-status`

## 5. Error Format

Most business errors return:

```json
{
  "error": "message explaining what failed"
}
```

Common status codes:

- `200`: success
- `201`: created
- `202`: command/event accepted for async processing
- `400`: invalid business input, missing machine IP, invalid master type, invalid card number
- `401`: missing or invalid auth
- `404`: row not found
- `422`: JSON schema validation error from FastAPI/Pydantic
- `502`: biometric machine SDK/connectivity failure

Example validation error:

```json
{
  "detail": [
    {
      "type": "greater_than_equal",
      "loc": ["body", "machine_port"],
      "msg": "Input should be greater than or equal to 1",
      "input": 0
    }
  ]
}
```

## 6. Machine Connection Resolution

Machine APIs resolve connection details in this priority order:

1. Explicit request fields: `machine_ip`, `machine_port`, `machine_password`, `machine_number`
2. Saved device registry via `device_id`
3. Config fallback: `machine_sync_ip`, `machine_sync_port`, etc.

Recommended web-app style:

```json
{
  "device_id": "FACTORY_T501_01"
}
```

Direct diagnostic style:

```json
{
  "machine_ip": "192.168.29.98",
  "machine_port": 5005,
  "machine_password": 0,
  "machine_number": 1
}
```

Edge cases solved:

- If `device_id` is inactive, API returns `400`.
- If `device_id` does not exist, API returns `400`.
- If no IP can be resolved, API returns `400`.
- If machine SDK fails to connect or execute, API returns `502`.
- Device passwords stored as text are validated as numeric before machine use.

## 7. Health APIs

### GET `/health`

Simple local service health endpoint. No auth.

Response:

```json
{
  "status": "ok",
  "env": "dev",
  "db_dialect": "sqlite"
}
```

### GET `/api/v1/health`

Middleware health and row counts. No auth currently.

Response:

```json
{
  "status": "ok",
  "env": "dev",
  "db_dialect": "sqlite",
  "counts": {
    "devices": 1,
    "commands": 0,
    "attendance_events": 10
  }
}

```

Use case: deployment checks, load balancer checks, Cloudflare tunnel smoke test.

## 8. Device Registry APIs

Device registry stores biometric machine connection details. Web apps should create devices once and later call machine APIs using only `device_id`.

Auth: middleware auth.

### POST `/api/v1/devices`

Creates or updates a device by `device_id`.

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "device_name": "Factory Gate",
  "site_id": "PLANT-A",
  "ip": "192.168.29.98",
  "port": 5005,
  "machine_number": 1,
  "timezone": "Asia/Kolkata",
  "is_active": true,
  "sdk_protocol": "sbxpc_tcp",
  "machine_password": "0"
}
```

Response `201`:

```json
{
  "device_id": "FACTORY_T501_01",
  "device_name": "Factory Gate",
  "site_id": "PLANT-A",
  "ip": "192.168.29.98",
  "port": 5005,
  "machine_number": 1,
  "timezone": "Asia/Kolkata",
  "is_active": true,
  "sdk_protocol": "sbxpc_tcp",
  "machine_password": "0",
  "created_at": "2026-05-09 10:00:00",
  "updated_at": "2026-05-09 10:00:00"
}
```

Edge cases:

- `device_id` required.
- `ip` required.
- `port` must be `1..65535`.
- `machine_number` must be `>= 1`. Most machines use `1`.
- `machine_password` must be numeric text.

### GET `/api/v1/devices`

Lists all devices.

Response:

```json
{
  "rows": [
    {
      "device_id": "FACTORY_T501_01",
      "device_name": "Factory Gate",
      "ip": "192.168.29.98",
      "port": 5005,
      "machine_number": 1,
      "is_active": true
    }
  ]
}
```

### PATCH `/api/v1/devices/{device_id}`

Updates partial fields.

Request:

```json
{
  "ip": "192.168.29.120",
  "machine_number": 1,
  "is_active": true
}
```

Response: patched device row.

## 9. Employee Master APIs

These APIs manage cloud-side employee master records. They do not automatically update a biometric machine unless the create request includes a `machine.sync_to_machine` object.

Auth: middleware auth.

### POST `/api/v1/employees`

Create/update an employee.

Request:

```json
{
  "employee_code": "E1001",
  "employee_name": "Test User",
  "father_name": "",
  "card_no": "9001001",
  "proximity_card_no": "",
  "email_id": "test@example.com",
  "phone_no": "9876543210",
  "department": "IT",
  "designation": "Engineer",
  "branch_name": "Mumbai",
  "office_time_policy": "GENERAL",
  "date_of_birth": "1995-01-01",
  "date_of_join": "2026-05-09",
  "shift_start_date": "2026-05-09",
  "shift_code": "DAY",
  "weekly_off": "Sunday",
  "company_name": "Example Pvt Ltd"
}
```

Response `201`:

```json
{
  "summary": {
    "inserted": 1,
    "updated": 0,
    "skipped": 0
  },
  "employee": {
    "employee_code": "E1001",
    "employee_name": "Test User",
    "card_no": "9001001",
    "department": "IT"
  },
  "machine_sync": {
    "requested": false,
    "success": null
  }
}
```

Create and push to machine in one call:

```json
{
  "employee_code": "E1001",
  "employee_name": "Test User",
  "card_no": "9001001",
  "department": "IT",
  "machine": {
    "sync_to_machine": true,
    "device_id": "FACTORY_T501_01",
    "user_id": 1001,
    "user_name": "Test User",
    "card_no": "9001001",
    "enable": true
  }
}
```

Machine sync success response includes:

```json
{
  "machine_sync": {
    "requested": true,
    "success": true,
    "result": {
      "employee_code": "E1001",
      "device_id": "FACTORY_T501_01",
      "user_id": 1001,
      "user_name": "Test User",
      "card_no": 9001001,
      "created_on_machine": true,
      "user_info_applied": true
    }
  }
}
```

Edge cases:

- `employee_code` is required.
- Machine user ID must be numeric. If `employee_code` cannot map to a numeric user ID, pass `machine.user_id`.
- `card_no` must be a positive integer when pushed to machine.
- Machine sync failures return `400` for bad input or `502` for SDK/device failures, while still returning the employee create context.

### GET `/api/v1/employees`

Query params:

- `employee_code`
- `department`
- `limit`, default `500`, max `5000`

Response:

```json
{
  "loaded": 1,
  "filters": {
    "employee_code": null,
    "department": "IT",
    "limit": 500
  },
  "rows": [
    {
      "employee_code": "E1001",
      "employee_name": "Test User"
    }
  ]
}
```

### GET `/api/v1/employees/{employee_code}`

Returns one employee or `404`.

### PATCH `/api/v1/employees/{employee_code}`

Partial update.

Request:

```json
{
  "designation": "Senior Engineer",
  "phone_no": "9999999999"
}
```

### DELETE `/api/v1/employees/{employee_code}`

Deletes only middleware employee master data. It does not delete the employee from a biometric machine. Use machine delete APIs for that.

Response:

```json
{
  "deleted": true,
  "employee_code": "E1001"
}
```

## 10. Master Data APIs

Supported master types:

- `departments`
- `designations`
- `office_time_policies`
- `companies`
- `branches`
- `shift_codes`

Auth: middleware auth.

### GET `/api/v1/master/types`

Response:

```json
{
  "rows": ["departments", "designations", "office_time_policies", "companies", "branches", "shift_codes"]
}
```

### POST `/api/v1/master/{master_type}`

Request:

```json
{
  "code": "D001",
  "name": "Operations",
  "description": "Factory operations team",
  "is_active": true
}
```

Response:

```json
{
  "master_type": "departments",
  "row": {
    "code": "D001",
    "name": "Operations",
    "description": "Factory operations team",
    "is_active": true,
    "action": "created"
  }
}
```

Other routes:

- `GET /api/v1/master/{master_type}?is_active=true&limit=500`
- `GET /api/v1/master/{master_type}/{code}`
- `PATCH /api/v1/master/{master_type}/{code}`
- `DELETE /api/v1/master/{master_type}/{code}`

Edge cases:

- Unsupported `master_type` returns `400`.
- Missing row returns `404`.
- Empty patch body returns `400`.

## 11. Attendance APIs

### GET `/api/v1/attendance`

Lists attendance events stored in middleware.

Auth: middleware auth.

Query params:

- `device_id`
- `employee_code`
- `from_utc`
- `to_utc`
- `limit`, default `500`, max `5000`

Response:

```json
{
  "loaded": 1,
  "rows": [
    {
      "event_id": "evt-001",
      "device_id": "FACTORY_T501_01",
      "employee_code": "E1001",
      "timestamp_local": "2026-05-09 09:30:00",
      "timestamp_utc": "2026-05-09T04:00:00Z",
      "timezone": "Asia/Kolkata",
      "source": "pull_sdk"
    }
  ]
}
```

Edge cases solved:

- Duplicate attendance events can be deduped using `event_id` or `idempotency_key`.
- Local timestamps can be converted to UTC using the submitted timezone.
- Query limit is capped to prevent huge responses.

### GET `/api/attendances`

Legacy dashboard-oriented attendance list with filters:

- `employee_code`
- `device_sn`
- `limit`

## 12. Command Queue APIs

Use these when the web app wants to queue work for an agent instead of directly calling the machine SDK.

Auth: middleware auth.

### POST `/api/v1/commands`

Request:

```json
{
  "request_id": "req-001",
  "device_id": "FACTORY_T501_01",
  "command_type": "employee.enable",
  "payload": {
    "employee_code": "E1001"
  },
  "priority": 100
}
```

Response `202`:

```json
{
  "command_id": "cmd-uuid",
  "request_id": "req-001",
  "device_id": "FACTORY_T501_01",
  "command_type": "employee.enable",
  "status": "QUEUED",
  "priority": 100,
  "payload": {
    "employee_code": "E1001"
  }
}
```

Other routes:

- `GET /api/v1/commands?device_id=FACTORY_T501_01&status=QUEUED&limit=100`
- `GET /api/v1/commands/{command_id}`

Device-scoped shortcuts:

- `POST /api/v1/devices/{device_id}/test-connection`
- `POST /api/v1/devices/{device_id}/sync-time`
- `POST /api/v1/devices/{device_id}/sync-employees`
- `POST /api/v1/devices/{device_id}/xml/execute`
- `POST /api/v1/devices/{device_id}/employees/{employee_code}/enable`
- `POST /api/v1/devices/{device_id}/employees/{employee_code}/disable`
- `DELETE /api/v1/devices/{device_id}/employees/{employee_code}`

Shortcut request body:

```json
{
  "request_id": "req-002",
  "payload": {
    "all_slots": true
  },
  "priority": 50
}
```

Edge cases:

- `request_id` should be unique from the caller side.
- Priority must be `1..1000`.
- Agent result failures move commands through retry/dead-letter status handling.

## 13. Agent APIs

Use these if a separate agent process pulls commands and pushes attendance batches.

Auth: agent `x-api-key` plus agent Bearer token.

### POST `/api/v1/agent/heartbeat`

Request:

```json
{
  "agent_id": "AGENT_PLANT_A",
  "site_id": "PLANT-A",
  "version": "1.0.0",
  "host_name": "PC-FACTORY-01",
  "local_ip": "192.168.29.10",
  "details": {
    "os": "Windows"
  }
}
```

### POST `/api/v1/agent/attendance/batch`

Request:

```json
{
  "agent_id": "AGENT_PLANT_A",
  "events": [
    {
      "event_id": "evt-001",
      "employee_code": "E1001",
      "machine_user_id": "1001",
      "device_id": "FACTORY_T501_01",
      "device_ip": "192.168.29.98",
      "timestamp_local": "2026-05-09 09:30:00",
      "timestamp_utc": "2026-05-09T04:00:00Z",
      "timezone": "Asia/Kolkata",
      "verification_mode": "fingerprint",
      "source": "pull_sdk",
      "raw_payload": {},
      "idempotency_key": "FACTORY_T501_01:1001:2026-05-09T04:00:00Z"
    }
  ]
}
```

Response:

```json
{
  "inserted": 1,
  "deduped": 0,
  "invalid": 0
}
```

### POST `/api/v1/agent/commands/claim`

Request:

```json
{
  "agent_id": "AGENT_PLANT_A",
  "device_ids": ["FACTORY_T501_01"],
  "limit": 10
}
```

Response:

```json
{
  "loaded": 1,
  "rows": [
    {
      "command_id": "cmd-uuid",
      "command_type": "employee.enable",
      "payload": {
        "employee_code": "E1001"
      }
    }
  ]
}
```

### POST `/api/v1/agent/commands/{command_id}/result`

Request:

```json
{
  "agent_id": "AGENT_PLANT_A",
  "success": true,
  "error_code": null,
  "error_message": null,
  "result_payload": {
    "applied": true
  }
}
```

## 14. Webhook APIs

Auth: middleware auth.

### POST `/api/v1/webhooks/subscriptions`

Request:

```json
{
  "subscription_id": "sub-001",
  "event_type": "attendance.created",
  "target_url": "https://your-hrms.example.com/webhook/attendance",
  "is_active": true
}
```

### GET `/api/v1/webhooks/subscriptions`

Lists subscriptions.

### GET `/api/v1/webhooks/deliveries`

Query params:

- `status`
- `limit`

### POST `/api/v1/webhooks/events/{event_type}`

Manually enqueue an event.

Request:

```json
{
  "event_id": "evt-custom-001",
  "payload": {
    "employee_code": "E1001"
  }
}
```

### POST `/api/v1/webhooks/dispatch`

Dispatches due webhook deliveries now.

Request:

```json
{
  "limit": 50
}
```

### POST `/api/v1/webhooks/retry/{delivery_id}`

Forces retry of one delivery.

Edge cases solved:

- Webhook retries follow `1m -> 5m -> 15m -> 60m`, then dead-letter.
- Manual retry can revive a failed delivery.
- HMAC secret is configured by `webhook_hmac_secret` for delivery signing logic.

## 15. Direct Machine APIs

These APIs call the biometric SDK immediately from the middleware PC. They are useful for admin screens, diagnostics, and direct HRMS actions.

Auth: middleware auth.

Common request fields:

```json
{
  "device_id": "FACTORY_T501_01",
  "machine_ip": "192.168.29.98",
  "machine_port": 5005,
  "machine_password": 0,
  "machine_number": 1,
  "sdk_dll_path": "sdk_extracted/20211204-SBXPC-1/bin/SBXPCDLL64.dll"
}
```

Use `device_id` when possible. Use raw connection fields only for diagnostics or when the device is not yet saved.

### POST `/api/machine/test-connection`

Request:

```json
{
  "device_id": "FACTORY_T501_01"
}
```

Response:

```json
{
  "connected": true,
  "device_id": "FACTORY_T501_01",
  "source": "device",
  "machine_ip": "192.168.29.98",
  "machine_port": 5005,
  "machine_number": 1,
  "device_time": "2026-05-09 10:30:00"
}
```

### POST `/api/machine/device/details`

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "include_user_count": true
}
```

Response includes serial number, device model, backup number, firmware version, capability map, optional user count, and warnings for fields the firmware cannot provide.

### POST `/api/machine/time/read`

Request:

```json
{
  "device_id": "FACTORY_T501_01"
}
```

Response:

```json
{
  "machine": {
    "device_id": "FACTORY_T501_01",
    "source": "device"
  },
  "device_time": "2026-05-09 10:30:00"
}
```

### POST `/api/machine/time/set`

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "device_time": "2026-05-09 10:30:00"
}
```

If `device_time` is omitted, middleware uses the current PC time.

### POST `/api/machine/logs/general/read`

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "limit": 200
}
```

Response:

```json
{
  "loaded": 2,
  "rows": [
    {
      "machine_user_id": "1001",
      "timestamp": "2026-05-09 09:30:00"
    }
  ]
}
```

### POST `/api/machine/capabilities/probe`

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "include_log_read_test": true,
  "log_read_limit": 1
}
```

Use case: detect which SDK functions work for a specific firmware/model.

### POST `/api/machine/xml/execute`

Low-level XML passthrough for SDK operations not wrapped by a typed endpoint.

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "request_name": "GetDeviceInfo",
  "msg_type": "request",
  "include_machine_id": true,
  "fields": [
    {
      "tag": "SomeTag",
      "value": "SomeValue",
      "value_type": "string"
    }
  ],
  "parse_fields": [
    {
      "tag": "Result",
      "value_type": "string"
    }
  ],
  "return_request_xml": false,
  "return_response_xml": true
}
```

Response:

```json
{
  "executed": true,
  "request_name": "GetDeviceInfo",
  "parsed": {
    "Result": "OK"
  },
  "parsed_binary": {},
  "response_xml": "<xml>...</xml>"
}
```

Edge cases:

- Invalid base64 in binary fields returns `400`.
- Parse fields that cannot be read return `null`.
- SDK failure returns `502`.

## 16. Machine Employee APIs

### POST `/api/machine/employees/sync`

Bulk sync employee master rows to machine.

Dry run request:

```json
{
  "device_id": "FACTORY_T501_01",
  "dry_run": true,
  "limit": 2000
}
```

Dry run response:

```json
{
  "dry_run": true,
  "rows": 2,
  "machine": {
    "device_id": "FACTORY_T501_01",
    "source": "device"
  },
  "preview": [
    {
      "employee_code": "E1001",
      "employee_name": "Test User",
      "resolved_user_id": 1001,
      "resolved_card_no": 9001001,
      "resolved_user_name": "Test User"
    }
  ]
}
```

Real sync request:

```json
{
  "device_id": "FACTORY_T501_01",
  "dry_run": false,
  "employee_code": "E1001",
  "timezone1": 1,
  "timezone2": 0,
  "group_no": 1
}
```

### POST `/api/machine/employees/read-all`

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "include_user_names": true
}
```

Response:

```json
{
  "total": 2,
  "active": 1,
  "inactive": 1,
  "rows": [
    {
      "user_id": 1001,
      "enabled": true,
      "user_name": "Test User"
    }
  ]
}
```

### PUT `/api/machine/employees/{employee_code}`

Update one employee on machine.

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "user_id": 1001,
  "user_name": "Test User",
  "card_no": "9001001",
  "timezone1": 1,
  "timezone2": 0,
  "group_no": 1,
  "enable": true
}
```

Response includes:

```json
{
  "employee_code": "E1001",
  "user_id": 1001,
  "user_name": "Test User",
  "card_no": 9001001,
  "existed_before": true,
  "created_on_machine": false,
  "user_info_applied": true,
  "user_info_error": null
}
```

### POST `/api/machine/employees/{employee_code}/read`

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "user_id": 1001,
  "include_user_name": true
}
```

Response:

```json
{
  "employee_code": "E1001",
  "user_id": 1001,
  "exists_on_machine": true,
  "user_name": "Test User",
  "machine_user_slots": 1,
  "effective_enabled": true,
  "machine_user_count": 50
}
```

### POST `/api/machine/employees/{employee_code}/enable`

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "user_id": 1001,
  "all_slots": true
}
```

Response includes:

```json
{
  "employee_code": "E1001",
  "user_id": 1001,
  "enabled": true,
  "all_slots": true,
  "operation_applied": true,
  "warning": null,
  "effective_enabled_after": true
}
```

### POST `/api/machine/employees/{employee_code}/disable`

Same body as enable. Response has `"enabled": false`.

### DELETE `/api/machine/employees/{employee_code}`

Request:

```json
{
  "device_id": "FACTORY_T501_01",
  "user_id": 1001,
  "all_slots": true
}
```

Response:

```json
{
  "employee_code": "E1001",
  "user_id": 1001,
  "deleted": true,
  "all_slots": true,
  "exists_on_machine_after": false,
  "remaining_slots": []
}
```

Machine employee edge cases solved:

- If employee is not in middleware and no `user_id` is passed, API returns `400`.
- If employee code is non-numeric, pass `user_id` explicitly.
- `all_slots=true` handles devices that store multiple credential slots per user.
- Enable/disable response includes `operation_applied` and `warning` because some firmware reports success but does not actually change state.
- Delete response includes `remaining_slots` so the caller can detect partial deletion.

## 17. Machine Push From Browser Example

```js
const baseUrl = "https://your-cloudflare-hostname";
const token = "dev-middleware-token";

const response = await fetch(`${baseUrl}/api/machine/employees/E1001/read`, {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${token}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    device_id: "FACTORY_T501_01",
    user_id: 1001,
    include_user_name: true
  })
});

if (!response.ok) {
  const error = await response.json();
  throw new Error(error.error || `HTTP ${response.status}`);
}

const body = await response.json();
console.log(body);
```

## 18. Deployment Checklist

1. Set app port to `9100` in config.
2. Install and start forever mode:

```powershell
.\RUN_FOREVER_ONCE.cmd -EnableCloudflareTunnel -CloudflareToken "YOUR_TOKEN"
```

3. Replace all dev secrets in `configs/prod.yaml`.
4. Restrict `cors_allowed_origins` when the static website URL is known.
5. Register device rows using `/api/v1/devices`.
6. Test local health:

```powershell
Invoke-WebRequest http://127.0.0.1:9100/health
```

7. Test Cloudflare health:

```powershell
Invoke-WebRequest https://your-cloudflare-hostname/health
```

8. Test authenticated request:

```powershell
curl.exe -X GET "https://your-cloudflare-hostname/api/v1/devices" ^
  -H "Authorization: Bearer YOUR_MIDDLEWARE_TOKEN"
```

## 19. Recommended Integration Flow

For a public web app:

1. Deployment engineer installs middleware on the PC near the biometric machine.
2. Deployment engineer exposes `http://127.0.0.1:9100` through Cloudflare.
3. Backend engineer stores middleware token/API key securely.
4. Backend engineer creates device registry rows.
5. Frontend engineer calls backend APIs, or directly calls Cloudflare API if secrets in browser are acceptable.
6. Frontend uses `/api/v1/devices`, `/api/v1/employees`, `/api/v1/master/*`, and selected `/api/machine/*` actions.
7. Backend/admin screens handle `400`, `401`, `404`, `422`, and `502` distinctly.

## 20. Current Public Surface Summary

Safe for general UI integration with auth:

- `/api/v1/devices`
- `/api/v1/employees`
- `/api/v1/master/*`
- `/api/v1/attendance`
- `/api/v1/commands`
- `/api/v1/webhooks/*`
- `/api/machine/*`

Internal/agent-only:

- `/api/v1/agent/*`
- `/machine/realtime_glog`

Dashboard/UI:

- `/dashboard`
- `/dashboard/employees`
- `/dashboard/admin`

## 21. FAQ for Engineers and Non-Engineers

This section answers common integration questions in two styles:

- Engineer mode: precise, implementation-focused answer.
- Plain-language mode: same answer for non-technical stakeholders.

### Q1) What is this middleware's main role?

Engineer mode:
It is the integration boundary between biometric devices and HRMS. It handles ingestion (`/machine/realtime_glog` or agent batch), normalization, deduplication, persistence, command orchestration, machine SDK operations, webhook dispatch, and outbound delivery.

Plain-language mode:
It is a translator and coordinator. It receives attendance from machines, keeps data clean and safe, and gives your HRMS one stable API to work with.

### Q2) What stack is used?

Engineer mode:
Python + FastAPI + Uvicorn + SQLAlchemy + YAML config. Dev commonly uses SQLite; stage/prod can use SQL Server via ODBC. Machine control uses vendor SDK DLL on Windows.

Plain-language mode:
It is a Python web service running on a local Windows PC near biometric devices, with a local database and optional Cloudflare tunnel.

### Q3) How does data come from machine into middleware?

Engineer mode:
Three supported patterns:
1. Push ingestion: machine POSTs to `/machine/realtime_glog`.
2. Pull/agent ingestion: collector sends `/api/v1/agent/attendance/batch`.
3. SDK read calls: `/api/machine/logs/general/read` returns logs on demand (diagnostic/read path).

Plain-language mode:
Either the machine sends punches directly, or another component reads punches and uploads them to middleware.

### Q4) How does middleware send data to HRMS?

Engineer mode:
Two patterns:
1. HRMS pulls/query/controls via middleware APIs (`/api/v1/*`, `/api/machine/*`).
2. Middleware worker pushes outbound attendance to configured `outbound_url`.

Plain-language mode:
HRMS can ask middleware for data, and middleware can also push attendance to HRMS automatically.

### Q5) Which health URL should we probe?

Engineer mode:
Use:
- `/health`
- `/api/v1/health`
Do not use `/v1/health` (not implemented, returns 404).

Plain-language mode:
Use `/health` or `/api/v1/health`. If you call `/v1/health`, you will see "not found".

### Q6) How are machine IP/port saved?

Engineer mode:
Stored in `devices` table (`device_id`, `ip`, `port`, `machine_number`, `machine_password`, etc.). Managed by `/api/v1/devices` create/list/patch. Connection resolver priority is:
1) explicit request values
2) `device_id` row
3) config fallback (`machine_sync_*`)

Plain-language mode:
Each machine is saved as a "device profile". APIs then use the device ID instead of repeatedly sending raw IP and port.

### Q7) Can the app auto-learn machine info?

Engineer mode:
Yes, ingress-based auto-registration is enabled by `auto_register_device_from_ingress: true`. When a punch arrives, middleware can register/update device metadata using `device_sn` and source IP.

Plain-language mode:
If a machine sends a punch first, middleware can automatically remember that machine.

### Q8) Which auth is required?

Engineer mode:
For `/api/v1/*` and `/api/machine/*`: `x-api-key` or Bearer middleware token.
For `/api/v1/agent/*`: both agent API key and agent JWT/Bearer token.

Plain-language mode:
Most APIs need a middleware key/token. Agent APIs need separate agent credentials.

### Q9) Standard request/response format?

Engineer mode:
Request content type is typically `application/json`. Responses are JSON except certain machine-ingress acknowledgments. Validation errors return FastAPI 422 schema error objects.

Plain-language mode:
Usually you send JSON and receive JSON.

### Q10) Standard error format and status codes?

Engineer mode:
Common business error shape: `{ "error": "<message>" }`.
Codes: 200/201/202 success variants, 400 invalid request, 401 auth failure, 404 not found, 422 validation, 502 machine SDK/connectivity error.

Plain-language mode:
Errors tell you what failed and use normal HTTP codes. 404 means wrong path/id, 401 means wrong credentials, 502 usually means machine/device communication issue.

### Q11) Where are logs stored?

Engineer mode:
Primary runtime logs are under `var/logs/`:
- `gateway.out.log`, `gateway.err.log`
- `worker.out.log`, `worker.err.log`
- `cloudflared.log`, `cloudflared.err.log`
Direct-listener capture file: `var/direct_listener/punches.jsonl`.

Plain-language mode:
All troubleshooting files are in the `var` folder, mostly `var/logs`.

### Q12) How fast is sync and does it retry?

Engineer mode:
Push-ingest is near real-time. Outbound dispatch depends on polling/backoff settings (`outbox_poll_seconds`, retry with jitter, max retries). Command/webhook flows also include retry/dead-letter logic.

Plain-language mode:
Data usually arrives quickly; if a send fails, middleware retries automatically.

### Q13) Are there API rate limits?

Engineer mode:
No explicit rate-limiting module is configured by default in this service. Capacity depends on machine, host resources, and DB backend.

Plain-language mode:
There is no hard per-minute cap in code today, but practical limits still exist.

### Q14) Environment model (dev/stage/prod)?

Engineer mode:
Configuration is environment-based via YAML (`configs/dev.yaml`, `configs/stage.yaml`, `configs/prod.yaml`) and `--config` startup argument.

Plain-language mode:
Same app, different settings files for development, testing, and production.

### Q15) Quick probe checklist for support teams

Engineer mode:
1. `./scripts/status.ps1`
2. `GET /health`
3. `GET /api/v1/health`
4. Confirm auth header on protected calls.
5. Inspect `var/logs/*.err.log`.

Plain-language mode:
Run status script, test health URL, then check log files if anything fails.

## 22. API Operation Contracts (Accepted JSON)

This section is a quick contract map for request inputs by operation.

Notes:
- GET endpoints usually do not accept JSON body; they use query parameters.
- Protected endpoints require auth headers as described in Section 4.
- Where an endpoint has many optional fields, the most common payload is shown.

### 22.1 GET Endpoints (Query Inputs)

1. `GET /health`
Query: none

2. `GET /api/v1/health`
Query: none

3. `GET /api/attendances`
Query:
```json
{
  "employee_code": "optional",
  "device_sn": "optional",
  "limit": 200
}
```

4. `GET /api/v1/devices`
Query: none

5. `GET /api/v1/employees`
Query:
```json
{
  "employee_code": "optional",
  "department": "optional",
  "limit": 500
}
```

6. `GET /api/v1/employees/{employee_code}`
Query: none

7. `GET /api/v1/master/types`
Query: none

8. `GET /api/v1/master/{master_type}`
Query:
```json
{
  "is_active": true,
  "limit": 500
}
```

9. `GET /api/v1/master/{master_type}/{code}`
Query: none

10. `GET /api/v1/attendance`
Query:
```json
{
  "device_id": "optional",
  "employee_code": "optional",
  "from_utc": "optional",
  "to_utc": "optional",
  "limit": 500
}
```

11. `GET /api/v1/commands`
Query:
```json
{
  "device_id": "optional",
  "status": "optional",
  "limit": 100
}
```

12. `GET /api/v1/commands/{command_id}`
Query: none

13. `GET /api/v1/webhooks/subscriptions`
Query: none

14. `GET /api/v1/webhooks/deliveries`
Query:
```json
{
  "status": "optional",
  "limit": 100
}
```

### 22.2 POST Endpoints (JSON Body Inputs)

1. `POST /api/v1/devices`
```json
{
  "device_id": "FACTORY_T501_01",
  "device_name": "Factory Gate",
  "site_id": "PLANT-A",
  "ip": "192.168.29.98",
  "port": 5005,
  "machine_number": 1,
  "timezone": "Asia/Kolkata",
  "is_active": true,
  "sdk_protocol": "sbxpc_tcp",
  "machine_password": "0"
}
```

2. `POST /api/v1/devices/{device_id}/test-connection`
3. `POST /api/v1/devices/{device_id}/sync-time`
4. `POST /api/v1/devices/{device_id}/sync-employees`
5. `POST /api/v1/devices/{device_id}/xml/execute`
6. `POST /api/v1/devices/{device_id}/employees/{employee_code}/enable`
7. `POST /api/v1/devices/{device_id}/employees/{employee_code}/disable`
```json
{
  "request_id": "req-001",
  "payload": {},
  "priority": 100
}
```

8. `POST /api/v1/employees`
```json
{
  "employee_code": "E1001",
  "employee_name": "Test User",
  "card_no": "9001001",
  "department": "IT",
  "designation": "Engineer",
  "machine": {
    "sync_to_machine": false
  }
}
```

9. `POST /api/v1/master/{master_type}`
```json
{
  "code": "D001",
  "name": "Operations",
  "description": "Optional",
  "is_active": true
}
```

10. `POST /api/v1/commands`
```json
{
  "request_id": "req-001",
  "device_id": "FACTORY_T501_01",
  "command_type": "employee.enable",
  "payload": {
    "employee_code": "E1001"
  },
  "priority": 100
}
```

11. `POST /api/v1/webhooks/subscriptions`
```json
{
  "subscription_id": "optional",
  "event_type": "attendance.created",
  "target_url": "https://example.com/webhook",
  "is_active": true
}
```

12. `POST /api/v1/webhooks/dispatch`
```json
{
  "limit": 50
}
```

13. `POST /api/v1/webhooks/events/{event_type}`
```json
{
  "event_id": "optional",
  "payload": {}
}
```

14. `POST /api/v1/webhooks/retry/{delivery_id}`
Body: none

15. `POST /api/v1/agent/heartbeat`
```json
{
  "agent_id": "AGENT_PLANT_A",
  "site_id": "PLANT-A",
  "version": "1.0.0",
  "host_name": "PC-01",
  "local_ip": "192.168.29.10",
  "details": {}
}
```

16. `POST /api/v1/agent/attendance/batch`
```json
{
  "agent_id": "AGENT_PLANT_A",
  "events": [
    {
      "event_id": "optional",
      "employee_code": "E1001",
      "machine_user_id": "1001",
      "device_id": "FACTORY_T501_01",
      "device_ip": "192.168.29.98",
      "timestamp_local": "2026-05-09 09:30:00",
      "timestamp_utc": "optional",
      "timezone": "Asia/Kolkata",
      "verification_mode": "fingerprint",
      "source": "pull_sdk",
      "raw_payload": {},
      "idempotency_key": "optional"
    }
  ]
}
```

17. `POST /api/v1/agent/commands/claim`
```json
{
  "agent_id": "AGENT_PLANT_A",
  "device_ids": [
    "FACTORY_T501_01"
  ],
  "limit": 10
}
```

18. `POST /api/v1/agent/commands/{command_id}/result`
```json
{
  "agent_id": "AGENT_PLANT_A",
  "success": true,
  "error_code": "optional",
  "error_message": "optional",
  "result_payload": {}
}
```

19. `POST /api/v1/agent/device-status`
```json
{
  "device_id": "FACTORY_T501_01",
  "device_name": "Factory Gate",
  "site_id": "PLANT-A",
  "ip": "192.168.29.98",
  "port": 5005,
  "machine_number": 1,
  "timezone": "Asia/Kolkata",
  "is_active": true,
  "sdk_protocol": "sbxpc_tcp",
  "machine_password": "0"
}
```

20. `POST /api/machine/test-connection`
21. `POST /api/machine/device/details`
22. `POST /api/machine/time/read`
23. `POST /api/machine/time/set`
24. `POST /api/machine/logs/general/read`
25. `POST /api/machine/capabilities/probe`
26. `POST /api/machine/xml/execute`
27. `POST /api/machine/employees/sync`
28. `POST /api/machine/employees/read-all`
29. `POST /api/machine/employees/{employee_code}/read`
30. `POST /api/machine/employees/{employee_code}/enable`
31. `POST /api/machine/employees/{employee_code}/disable`
Common machine-connection body (base shape):
```json
{
  "device_id": "optional",
  "machine_ip": "optional",
  "machine_port": 5005,
  "machine_password": 0,
  "machine_number": 1,
  "sdk_dll_path": "optional"
}
```

Endpoint-specific extras:
- `/api/machine/time/set`: `device_time`
- `/api/machine/logs/general/read`: `limit`
- `/api/machine/capabilities/probe`: `include_log_read_test`, `log_read_limit`
- `/api/machine/employees/sync`: `employee_code`, `limit`, `dry_run`, `timezone1`, `timezone2`, `group_no`
- `/api/machine/employees/read-all`: `include_user_names`
- `/api/machine/employees/{employee_code}/read`: `user_id`, `include_user_name`
- `/api/machine/employees/{employee_code}/enable|disable`: `user_id`, `e_machine_number`, `backup_number`, `all_slots`
- `/api/machine/xml/execute`: `request_name`, `msg_type`, `include_machine_id`, `fields`, `binary_fields`, `parse_fields`, `parse_binary_fields`, `return_request_xml`, `return_response_xml`

32. `POST /machine/realtime_glog`
Body is machine raw payload (not regular JSON), with header:
```text
request_code: realtime_glog
```

### 22.3 PUT/PATCH/DELETE Endpoints (JSON Body Inputs)

1. `PUT /api/machine/employees/{employee_code}`
```json
{
  "device_id": "optional",
  "machine_ip": "optional",
  "machine_port": 5005,
  "machine_password": 0,
  "machine_number": 1,
  "sdk_dll_path": "optional",
  "user_id": 1001,
  "user_name": "Test User",
  "card_no": "9001001",
  "timezone1": 1,
  "timezone2": 0,
  "group_no": 1,
  "enable": true,
  "e_machine_number": 1,
  "backup_number": 0
}
```

2. `PATCH /api/v1/devices/{device_id}`
```json
{
  "device_name": "optional",
  "site_id": "optional",
  "ip": "optional",
  "port": 5005,
  "machine_number": 1,
  "timezone": "optional",
  "is_active": true,
  "sdk_protocol": "optional",
  "machine_password": "optional"
}
```

3. `PATCH /api/v1/employees/{employee_code}`
```json
{
  "employee_name": "optional",
  "father_name": "optional",
  "card_no": "optional",
  "proximity_card_no": "optional",
  "email_id": "optional",
  "phone_no": "optional",
  "department": "optional",
  "designation": "optional",
  "branch_name": "optional",
  "office_time_policy": "optional",
  "date_of_birth": "optional",
  "date_of_join": "optional",
  "shift_start_date": "optional",
  "shift_code": "optional",
  "weekly_off": "optional",
  "company_name": "optional"
}
```

4. `PATCH /api/v1/master/{master_type}/{code}`
```json
{
  "name": "optional",
  "description": "optional",
  "is_active": true
}
```

5. `DELETE /api/v1/employees/{employee_code}`
Body: none

6. `DELETE /api/v1/master/{master_type}/{code}`
Body: none

7. `DELETE /api/v1/devices/{device_id}/employees/{employee_code}`
```json
{
  "request_id": "req-001",
  "payload": {},
  "priority": 100
}
```

8. `DELETE /api/machine/employees/{employee_code}`
```json
{
  "device_id": "optional",
  "machine_ip": "optional",
  "machine_port": 5005,
  "machine_password": 0,
  "machine_number": 1,
  "sdk_dll_path": "optional",
  "user_id": 1001,
  "e_machine_number": 1,
  "backup_number": 0,
  "all_slots": false
}
```
