# Attendance Relay - Feature and API Specification

## 1) Scope

This document describes:

1. Current app features
2. Complete API surface
3. Data flow and command flow between HRMS and machine middleware
4. Device admin behavior (IP/port/password management)
5. Multi-PC gateway URL failover strategy for HRMS integration


## 2) High-Level Architecture

The middleware has two logical planes:

1. `Cloud/Data plane` (`/api/v1/*`)
   - Employee master CRUD
   - Master data CRUD (departments, designations, etc.)
   - Device registry CRUD
   - Command queue APIs for agent-driven workflows

2. `Machine control plane` (`/api/machine/*`)
   - Direct SDK calls to biometric machine
   - Read/push/update/delete/enable/disable machine users
   - XML passthrough execution


## 3) Authentication

- `/api/v1/*` APIs require:
  - Header: `x-api-key: <middleware_api_key>`
- `/api/machine/*` currently do not require this header in route guard logic.
  - Recommended for production: add guard and network ACL.


## 4) Machine Connection Resolution (Important)

Machine endpoints support connection values in priority order:

1. Explicit request fields (`machine_ip`, `machine_port`, etc.)
2. `device_id` lookup from saved device registry (`/api/v1/devices`)
3. App settings fallback (`machine_sync_ip`, `machine_sync_port`, ...)

This allows HRMS to pass only:

```json
{ "device_id": "DEV-LIVE-01" }
```

and middleware resolves machine IP/port/password automatically.


## 5) Device Admin Features

### UI

- Page: `/dashboard/admin`
- Save endpoint: `POST /dashboard/admin/devices/save`
- Supports creating/updating:
  - `device_id`
  - `device_name`
  - `site_id`
  - `ip`
  - `port`
  - `timezone`
  - `machine_password`
  - `is_active`

### API

- `POST /api/v1/devices` (upsert create/update by `device_id`)
- `GET /api/v1/devices`
- `PATCH /api/v1/devices/{device_id}`

### Validation

- `port` must be `1..65535`
- `machine_password` must be numeric text if provided


## 6) API Catalog

## 6.1 Health and Utility

- `GET /health`
- `GET /api/v1/health`
- `GET /api/attendances`
- `GET /api/v1/attendance`


## 6.2 Employee Cloud CRUD

- `POST /api/v1/employees`
- `GET /api/v1/employees`
- `GET /api/v1/employees/{employee_code}`
- `PATCH /api/v1/employees/{employee_code}`
- `DELETE /api/v1/employees/{employee_code}`

Employee create payload fields:

- `employee_code`
- `employee_name`
- `father_name`
- `card_no`
- `proximity_card_no`
- `email_id`
- `phone_no`
- `department`
- `designation`
- `branch_name`
- `office_time_policy`
- `date_of_birth`
- `date_of_join`
- `shift_start_date`
- `shift_code`
- `weekly_off`
- `company_name`
- optional `machine` object for direct machine sync


## 6.3 Master CRUD

Master types:

- `departments`
- `designations`
- `office_time_policies`
- `companies`
- `branches`
- `shift_codes`

Routes:

- `GET /api/v1/master/types`
- `POST /api/v1/master/{master_type}`
- `GET /api/v1/master/{master_type}`
- `GET /api/v1/master/{master_type}/{code}`
- `PATCH /api/v1/master/{master_type}/{code}`
- `DELETE /api/v1/master/{master_type}/{code}`

Create body:

```json
{
  "code": "D001",
  "name": "Operations",
  "description": "Optional",
  "is_active": true
}
```

Patch body:

```json
{
  "name": "Operations Updated",
  "description": "Updated",
  "is_active": false
}
```


## 6.4 Direct Machine APIs (SDK-backed)

- `POST /api/machine/test-connection`
- `POST /api/machine/xml/execute`
- `POST /api/machine/employees/sync`
- `POST /api/machine/employees/read-all`
- `PUT /api/machine/employees/{employee_code}`
- `POST /api/machine/employees/{employee_code}/read`
- `DELETE /api/machine/employees/{employee_code}`
- `POST /api/machine/employees/{employee_code}/enable`
- `POST /api/machine/employees/{employee_code}/disable`

Common connection fields (all optional):

- `device_id`
- `machine_ip`
- `machine_port`
- `machine_password`
- `machine_number`
- `sdk_dll_path`

Recommended request style:

```json
{
  "device_id": "DEV-LIVE-01"
}
```


## 6.5 Device-Scoped Command Queue APIs

For agent-based async execution:

- `POST /api/v1/devices/{device_id}/test-connection`
- `POST /api/v1/devices/{device_id}/sync-time`
- `POST /api/v1/devices/{device_id}/sync-employees`
- `POST /api/v1/devices/{device_id}/xml/execute`
- `POST /api/v1/devices/{device_id}/employees/{employee_code}/enable`
- `POST /api/v1/devices/{device_id}/employees/{employee_code}/disable`
- `DELETE /api/v1/devices/{device_id}/employees/{employee_code}`


## 7) CRUD + Machine Operation Matrix

1. Employee cloud CRUD: yes
2. Master CRUD (all six): yes
3. Device CRUD/edit: yes
4. Machine read employee: yes
5. Machine read all employees: yes
6. Machine push/update employee: yes
7. Machine delete employee: yes
8. Machine enable/disable employee: yes (firmware-dependent reliability)
9. Photo upload/read (XML): yes through XML/general operation endpoint path


## 8) Known Behavior and Constraints

1. `employee_code` normalization:
   - `000230` and `230` map to same normalized numeric machine user ID behavior.
2. Some firmware/models may return SDK success for enable/disable but not apply change.
   - Middleware exposes post-read state (`operation_applied`, `effective_enabled_after`, `warning`) for transparency.
3. Machine business attributes like department/designation/company are cloud-side master data;
   machine SDK stores user-centric fields (name/card/timezone/group/etc.).


## 9) HRMS Integration Pattern (Recommended)

1. HRMS keeps multiple middleware URLs (multiple PC deployments):
   - Example:
     - `http://pc-1:8000`
     - `http://pc-2:8000`
     - `http://pc-3:8000`
2. Use one active URL at a time.
3. If request fails (timeout/network/5xx), retry next healthy URL automatically.
4. Keep device configs in middleware via `/api/v1/devices`.
5. All machine operations from HRMS should send `device_id`, not raw IP.


## 10) Example Flows

### A) Add new branch + assign employee

1. `POST /api/v1/master/branches`
2. `PATCH /api/v1/employees/{employee_code}` with `branch_name`

### B) Enable employee on machine

1. `POST /api/machine/employees/{employee_code}/enable`
2. Body:

```json
{
  "device_id": "DEV-LIVE-01",
  "all_slots": true
}
```

3. Validate response:
   - `operation_applied`
   - `effective_enabled_after`
   - `warning`


## 11) Suggested Next Enhancements

1. Row-level edit/delete controls in `/dashboard/admin` table
2. Role-based auth on admin dashboard and `/api/machine/*`
3. URL failover health-state APIs for centralized monitoring
4. Device-level machine diagnostics panel (latency, last success, recent failures)
