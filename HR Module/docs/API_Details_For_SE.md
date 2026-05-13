# HRMS Middleware — API Details for the Software Engineer Agent

**Audience:** The K95 ERP web-app's software-engineer AI agent that will call the
`hrms_middleware` HTTP API directly from the web app (same LAN as the biometric
machine, or via Cloudflare Tunnel).

**Authoritative sources used to build this document:**

- `HR Module/docs/TECHNICAL_SPECIFICATION_API.md` (companion spec)
- `HR Module/docs/API_INTEGRATION_GUIDE.md` (deployment/integration guide)
- `HR Module/src/attendance_relay/middleware_models.py` (Pydantic request schemas — ground truth)
- `HR Module/src/attendance_relay/db.py` (SQL DDL — ground truth)
- `HR Module/src/attendance_relay/ingress_app.py` (HTTP routes and status codes)
- `HR Module/src/attendance_relay/machine_sync.py` (derivation rules for `user_id` / `card_no` / `user_name`)
- `HR Module/src/attendance_relay/machine_admin.py` (machine resolution + per-employee machine operations)
- `HR Module/src/attendance_relay/master_data.py` (`normalize_employee_code`)

Anywhere the prose in the older docs disagrees with the code, this document
follows the code.

---

## 0. Quick orientation

### 0.1 Tech stack
- Python 3.11+, FastAPI, Uvicorn, SQLAlchemy, Pydantic v2.
- SQLite for dev, MSSQL (via ODBC) for stage/prod. DDL lives in `db.py`.
- Biometric I/O via vendor SBXPC SDK DLL on Windows.

### 0.2 Base URLs
| Environment | URL |
|---|---|
| Local (LAN, same subnet as machine) | `http://127.0.0.1:9100` |
| Public (Cloudflare Tunnel) | `https://<your-cloudflare-hostname>` |

### 0.3 Authentication (applies to every entity below)

For middleware/machine APIs (`/api/v1/**` and `/api/machine/**`), send **one** of:

```http
x-api-key: <middleware_api_key>
```
or
```http
Authorization: Bearer <middleware_bearer_token>
```

Agent-only APIs (`/api/v1/agent/**`) require **both** `x-api-key: <agent_api_key>`
**and** `Authorization: Bearer <agent_jwt_token>`. The web app does **not** use these.

Unauthorized requests return:
```json
{ "error": "invalid middleware api key" }
```
with HTTP `401`.

### 0.4 Standard error shape
```json
{ "error": "<human-readable reason>" }
```
Validation errors from Pydantic return the FastAPI `422` shape:
```json
{ "detail": [ { "type": "...", "loc": ["body","..."], "msg": "...", "input": ... } ] }
```

| HTTP | Meaning in this API |
|---|---|
| 200 | Read/update success |
| 201 | Resource created/upserted |
| 202 | Command queued for async agent execution |
| 400 | Business validation failure (bad master type, missing IP, non-numeric card, etc.) |
| 401 | Missing/invalid auth |
| 404 | Resource not found |
| 422 | Pydantic schema validation failure |
| 502 | Biometric SDK / machine connectivity failure |

### 0.5 Entity index (everything the web app interacts with)
1. [Employee Master Record](#1-employee-master-record) — cloud-side employee
2. [Employee Machine Sync Block](#2-employee-machine-sync-block) — inline provisioning sub-object
3. [Device Configuration](#3-device-configuration) — biometric machine profile
4. [Command Job](#4-command-job) — async queue item (enable/disable/delete on device)
5. [Attendance Event](#5-attendance-event) — punch record
6. [Master Data Record](#6-master-data-record) — departments, designations, etc.
7. [Webhook Subscription](#7-webhook-subscription) — outbound notifications
8. [Agent Node](#8-agent-node) — read-only visibility (informational)

---

## 1. Employee Master Record

### 1.1 Purpose & Role
The cloud-side employee record stored by the middleware. Every employee the K95
ERP wants to provision on a biometric machine must exist here first. Provisioning
to the device is an **optional** secondary action triggered by the `machine`
sub-object on create, by dedicated per-device endpoints, or by an async command.

Persisted in the `employee_master` SQL table.

### 1.2 Full JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "EmployeeMasterRecord",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "employee_code": {
      "type": "string",
      "description": "Primary key. Unique across the middleware.",
      "minLength": 1,
      "maxLength": 50
    },
    "employee_code_normalized": {
      "type": "string",
      "description": "Server-derived. Numeric form if employee_code matches /^[Ee][0-9]+$/ or pure digits; otherwise upper-cased original.",
      "minLength": 1
    },
    "employee_name":      { "type": ["string","null"], "maxLength": 255 },
    "father_name":        { "type": ["string","null"], "maxLength": 255 },
    "card_no":            { "type": ["string","null"], "maxLength": 50, "description": "Primary RFID/credential. Must be numeric (parseable as unsigned 64-bit) when pushed to the machine." },
    "proximity_card_no":  { "type": ["string","null"], "maxLength": 50, "description": "Secondary/backup card; same numeric rule as card_no when used." },
    "email_id":           { "type": ["string","null"], "format": "email", "maxLength": 255 },
    "phone_no":           { "type": ["string","null"], "maxLength": 20 },
    "department":         { "type": ["string","null"], "maxLength": 100, "description": "References department_master.code (not enforced as FK)." },
    "designation":        { "type": ["string","null"], "maxLength": 100, "description": "References designation_master.code." },
    "branch_name":        { "type": ["string","null"], "maxLength": 100, "description": "References branch_master.code." },
    "office_time_policy": { "type": ["string","null"], "maxLength": 100, "description": "References office_time_policy_master.code." },
    "date_of_birth":      { "type": ["string","null"], "format": "date", "description": "YYYY-MM-DD." },
    "date_of_join":       { "type": ["string","null"], "format": "date" },
    "shift_start_date":   { "type": ["string","null"], "format": "date" },
    "shift_code":         { "type": ["string","null"], "maxLength": 100, "description": "References shift_code_master.code." },
    "weekly_off":         { "type": ["string","null"], "maxLength": 50, "description": "e.g. 'Sunday', 'Saturday'." },
    "company_name":       { "type": ["string","null"], "maxLength": 100, "description": "References company_master.code." },
    "created_at":         { "type": "string", "format": "date-time", "description": "Server-assigned." },
    "updated_at":         { "type": "string", "format": "date-time", "description": "Server-assigned." }
  },
  "required": ["employee_code"]
}
```

**Create/upsert request body** (extra fields beyond the schema above: only
`employee_code` is strictly required; every other field defaults to `""`. The
optional `machine` sub-object triggers same-call provisioning — see §2):

```json
{
  "employee_code": "E001",
  "employee_name": "John Doe",
  "card_no": "12345678",
  "department": "IT",
  "designation": "Engineer",
  "branch_name": "Delhi",
  "machine": { "sync_to_machine": false }
}
```

**Create response — `POST /api/v1/employees` → `201 Created`:**

```json
{
  "summary": { "inserted": 1, "updated": 0, "skipped": 0 },
  "employee": { "employee_code": "E001", "employee_name": "John Doe", "card_no": "12345678", "department": "IT", "designation": "Engineer", "employee_code_normalized": "1", "created_at": "2026-05-12T10:30:00Z", "updated_at": "2026-05-12T10:30:00Z" },
  "machine_sync": { "requested": false, "success": null }
}
```

When `machine.sync_to_machine: true`, the response also carries the inline sync
outcome — see §2.

**Endpoints touching this entity:**

| Method | Path | Status | Body shape |
|---|---|---|---|
| POST  | `/api/v1/employees` | 201 | `EmployeeCreateRequest` (above) — upsert by `employee_code` |
| GET   | `/api/v1/employees?employee_code=&department=&limit=` | 200 | none (query params) |
| GET   | `/api/v1/employees/{employee_code}` | 200 / 404 | none |
| PATCH | `/api/v1/employees/{employee_code}` | 200 / 404 | partial; any non-null fields update |
| DELETE| `/api/v1/employees/{employee_code}` | 200 / 404 | none. Deletes middleware row only — does **not** remove the user from the machine. |

### 1.3 Key Identifiers
- **Primary key:** `employee_code` (TEXT). Uniqueness is enforced by SQL
  `PRIMARY KEY` on `employee_master.employee_code`.
- **Secondary lookup key:** `employee_code_normalized` (indexed) — used for
  matching when the K95 ERP sends `"E001"` against a machine that knows the user
  as `1`.

### 1.4 Relationships
- 1 employee ↔ N **attendance_events** (joined by `employee_code`).
- 1 employee ↔ N **device** rows via the per-device queue endpoints — note this
  is a **logical/operational** link only; there is no employee-to-device
  association table in the schema. The link is realized at provisioning time
  (Command Job, §4) and at punch time (Attendance Event, §5).
- `department`, `designation`, `branch_name`, `office_time_policy`,
  `shift_code`, `company_name` are soft references to the corresponding
  **Master Data Record** tables (§6). Not enforced by FK; an unknown value is
  accepted but flagged by lint screens in the dashboard.

### 1.5 K95 ERP → Middleware Mapping

| K95 ERP Field (Our App) | Middleware Field (Target) | Transformation / Derivation Rules |
|---|---|---|
| `employee.id` | _(not used)_ | Internal numeric PK in ERP. Middleware does **not** consume it. |
| `employee.employee_code` | `employee_code` | Direct, trimmed. **Primary unique identifier.** |
| `employee.full_name` | `employee_name` | Direct. |
| `employee.father_name` | `father_name` | Direct, optional. |
| `employee.rfid_card_id` | `card_no` | Cast to string. Must parse as unsigned ≤ `(2^64)-1` if/when pushed to machine; otherwise machine sync falls back to `user_id`. |
| `employee.alternate_card_id` | `proximity_card_no` | Same numeric rule as `card_no`. |
| `employee.email` | `email_id` | Direct. |
| `employee.mobile` | `phone_no` | Direct. |
| `employee.dept_code` | `department` | Direct; expected to match `department_master.code`. |
| `employee.job_title` | `designation` | Direct; expected to match `designation_master.code`. |
| `employee.location` | `branch_name` | Direct; expected to match `branch_master.code`. |
| `employee.shift_policy` | `office_time_policy` | Direct; expected to match `office_time_policy_master.code`. |
| `employee.dob` | `date_of_birth` | Format as `YYYY-MM-DD`. |
| `employee.date_of_joining` | `date_of_join` | Format as `YYYY-MM-DD`. |
| `employee.shift_assignment_date` | `shift_start_date` | Format as `YYYY-MM-DD`. |
| `employee.shift_code` | `shift_code` | Direct; expected to match `shift_code_master.code`. |
| `employee.weekly_holiday` | `weekly_off` | Direct (e.g. `"Sunday"`). |
| `employee.company` | `company_name` | Direct; expected to match `company_master.code`. |

Server-derived (do **not** send): `employee_code_normalized`, `created_at`,
`updated_at`.

#### `employee_code_normalized` derivation (server-side, from `master_data.normalize_employee_code`)

```
raw = trim(employee_code)
if raw matches /^[Ee]([0-9]+)$/   →  str(int($1))      // "E001" → "1"
elif raw matches /^[0-9]+$/        →  str(int(raw))     // "0001" → "1"
else                               →  raw.upper()       // "EMP-A1" → "EMP-A1"
```

This drives the auto-derivation of machine `user_id` for the `E0001`-style ERP
codes the K95 system uses today.

### 1.6 Data Integrity & Validation Rules
- `employee_code` is **required and non-empty** (`400 employee_code is required`
  when missing).
- All other fields default to empty string at the API layer (Pydantic), then
  stored as `NULL` where the column allows null.
- **Upsert semantics:** `POST /api/v1/employees` always inserts or updates by
  `employee_code` — safe to retry.
- **PATCH semantics:** Only non-null fields in the body are applied; the
  remainder of the row is preserved. Empty PATCH body returns `400`.
- **DELETE semantics:** Returns `404` if `employee_code` does not exist.
  **Not idempotent** at the HTTP level.
- Card-number range is server-enforced when actually pushed to the machine,
  not on initial create — invalid card values just demote machine sync, they
  do not block ERP-side persistence.

### 1.7 Known Issues & Considerations
- **Non-numeric `employee_code` cannot auto-map to a machine `user_id`.** The
  middleware will raise `400` (`employee_code cannot map to numeric machine
  user_id`) the first time you try to push that employee to a device unless
  you also send `machine.user_id` explicitly. See §2.5.
- `employee_code` is `TEXT` and is _case-sensitive_ in SQLite but
  case-insensitive in MSSQL by default. Treat it as case-sensitive on the
  client and uppercase before send to be portable.
- Deleting an `employee_master` row does **not** delete the corresponding user
  from any biometric device. Use the per-device delete (§4) for that.
- Master-data fields (`department`, `designation`, …) are not FK-enforced; a
  typo persists silently.

---

## 2. Employee Machine Sync Block

### 2.1 Purpose & Role
A sub-object of the employee create request (`EmployeeMachineCreateRequest` in
`middleware_models.py`) that says "while you're creating/updating this employee,
also push them to a biometric machine right now". When `sync_to_machine: true`,
the middleware performs a synchronous SDK call to the device and returns the
result in the `machine_sync` block of the response. This is the **primary path**
for the web app to provision an employee end-to-end in one call.

### 2.2 Full JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "EmployeeMachineSyncBlock",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "sync_to_machine":  { "type": "boolean", "default": false, "description": "Master switch. Must be true to trigger any machine I/O." },
    "device_id":        { "type": ["string","null"], "description": "Preferred target. Resolved against the devices table for IP/port/password." },
    "machine_ip":       { "type": ["string","null"], "format": "ipv4", "description": "Direct override. Used when device_id is not provided." },
    "machine_port":     { "type": ["integer","null"], "minimum": 1, "maximum": 65535, "default": 5005 },
    "machine_password": { "type": ["integer","null"], "description": "Numeric in this sub-object (unlike DeviceUpsert where it is a string)." },
    "machine_number":   { "type": ["integer","null"], "minimum": 1, "default": 1, "description": "SBXPC SDK machine number. 1 for single-device setups." },
    "sdk_dll_path":     { "type": ["string","null"], "description": "Override path to SBXPCDLL64.dll; defaults to settings.machine_sdk_dll_path." },
    "user_id":          { "type": ["integer","null"], "minimum": 0, "maximum": 2147483647, "description": "Explicit machine user id. Wins over derived value." },
    "user_name":        { "type": ["string","null"], "description": "Explicit name on machine. Wins over derived value." },
    "card_no":          { "type": ["string","null"], "description": "Numeric string. Wins over the employee row's card_no/proximity_card_no." },
    "timezone1":        { "type": ["integer","null"] },
    "timezone2":        { "type": ["integer","null"] },
    "group_no":         { "type": ["integer","null"] },
    "enable":           { "type": ["boolean","null"], "description": "If set, the user is enabled/disabled on the device immediately after creation/update." },
    "e_machine_number": { "type": "integer", "minimum": 1, "default": 1 },
    "backup_number":    { "type": "integer", "minimum": 0, "default": 0 }
  },
  "required": ["sync_to_machine"]
}
```

### 2.3 Connection Resolution (where the IP/port comes from)

When `sync_to_machine: true`, the middleware resolves the target machine in this
strict priority order (from `machine_admin.resolve_machine_connection`):

1. **Explicit values:** any of `machine_ip`, `machine_port`, `machine_password`,
   `machine_number` provided in the body win for that field.
2. **`device_id` lookup:** unset fields are filled from the `devices` row.
   Inactive device → `400`. Missing device → `400`.
3. **Config fallback:** any still-unset field falls back to `machine_sync_*`
   settings in `configs/{env}.yaml`.

If no IP can be resolved at the end of this chain → `400 "machine ip required"`.

### 2.4 Derivation Rules (the critical bit for K95 ERP integration)

| Field on device | Source priority | Validation |
|---|---|---|
| `user_id` (int) | 1. body `machine.user_id` → 2. `employee_code_normalized` (parsed as unsigned ≤ `2_147_483_647`) → 3. `employee_code` (same parse). Fails with `400` if none yield a non-negative signed-32-bit integer. | Must be ≤ `2_147_483_647` (signed `long` max). |
| `card_no` (int) | 1. body `machine.card_no` → 2. employee row `card_no` → 3. employee row `proximity_card_no` → 4. **fallback = `user_id`** (so the machine always has _some_ credential, even if card data is missing). | Must parse as unsigned ≤ `(2^64)-1`. Non-numeric strings are ignored, fall through to next priority. |
| `user_name` (str) | 1. body `machine.user_name` → 2. employee row `employee_name` → 3. employee row `employee_code` → 4. literal `"UNKNOWN"`. | None. Trimmed only. |

#### Worked examples

```
ERP sends: employee_code="E0001", card_no="12345678", no explicit machine.user_id
→ employee_code_normalized = "1"
→ user_id = 1                    (rule 2)
→ card_no = 12345678             (rule 2)
→ user_name = employee_name      (rule 2)

ERP sends: employee_code="EMP-A1", card_no="" (empty)
→ employee_code_normalized = "EMP-A1"
→ user_id cannot parse → 400 "employee_code cannot map to numeric machine user_id"
→ FIX: include machine.user_id explicitly, e.g. ERP-managed mapping → 101

ERP sends: employee_code="E0001", card_no="ABC123" (invalid)
→ user_id = 1
→ card_no = fallback to user_id = 1   (rule 4, because "ABC123" cannot parse)
→ Machine still gets a record; punch will identify as user_id=1
```

### 2.5 Response shape

On success, the parent employee POST returns:

```json
{
  "summary": { "inserted": 1, "updated": 0, "skipped": 0 },
  "employee": { "...": "..." },
  "machine_sync": {
    "requested": true,
    "success": true,
    "result": {
      "employee_code": "E001",
      "device_id": "DEVICE001",
      "source": "device",
      "machine_ip": "192.168.1.100",
      "machine_port": 5005,
      "machine_number": 1,
      "user_id": 1,
      "user_name": "John Doe",
      "card_no": 12345678,
      "created_on_machine": true,
      "user_info_applied": true
    }
  }
}
```

On machine sync failure, the employee is **still saved** in the middleware DB
and the response carries `machine_sync.success: false` with an `error` field;
HTTP status is `400` for input-shape failures and `502` for SDK/connectivity
failures.

### 2.6 Validation Rules
- `sync_to_machine` is required (typed `bool`).
- `machine_port` must be `1..65535`.
- `user_id` must be `0..2_147_483_647`.
- `machine_number` and `e_machine_number` must be `≥ 1`; `backup_number` `≥ 0`.
- `machine_password` here is `int` (the body shape inherits the legacy SDK
  contract). The **devices** table stores it as numeric text — see §3.

### 2.7 Known Issues & Considerations
- The same field name `machine_password` is `int` in this sub-object but
  `string ^[0-9]*$` in `DeviceUpsertRequest` (§3). Pick one in the web-app DTO
  layer and convert at the boundary.
- Same field name `card_no` exists both on the top-level employee record
  (string) and inside the `machine` block (string, but converted to int).
  Sending both is allowed; the `machine.card_no` takes priority for the device.
- The middleware **does not** persist `enable` state on the ERP side — if the
  K95 ERP later wants to know whether the user is enabled on a specific
  device, it must call `/api/machine/employees/{employee_code}/read` or use
  the per-device enable/disable command queue (§4).

---

## 3. Device Configuration

### 3.1 Purpose & Role
A registered biometric machine. Stored in the `devices` SQL table. Once a
device is registered with `device_id`, every other API call can refer to it by
`device_id` alone instead of sending IP/port/password each time.

This is the entity behind the K95 ERP's `HRMSDevice` settings record.

### 3.2 Full JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DeviceConfiguration",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "device_id": {
      "type": "string",
      "description": "Primary key. Caller-supplied, stable identifier (e.g. 'DELHI-F1-M1', 'FACTORY_T501_01').",
      "minLength": 1,
      "maxLength": 50
    },
    "device_name":   { "type": ["string","null"], "maxLength": 255 },
    "site_id":       { "type": ["string","null"], "maxLength": 50, "description": "Logical grouping; not enforced as FK." },
    "ip":            { "type": "string", "format": "ipv4", "description": "Required. Reachable from the middleware host on the LAN." },
    "port":          { "type": "integer", "minimum": 1, "maximum": 65535, "default": 5005 },
    "machine_number":{ "type": "integer", "minimum": 1, "default": 1, "description": "SBXPC SDK machine number. Almost always 1." },
    "timezone":      { "type": "string", "default": "Asia/Kolkata", "description": "IANA TZ name." },
    "is_active":     { "type": "boolean", "default": true },
    "sdk_protocol":  { "type": "string", "enum": ["sbxpc_tcp"], "default": "sbxpc_tcp" },
    "machine_password": { "type": ["string","null"], "pattern": "^[0-9]*$", "default": "", "description": "Numeric text. '0' is the common default. Empty = no password." },
    "created_at":    { "type": "string", "format": "date-time" },
    "updated_at":    { "type": "string", "format": "date-time" },
    "last_seen_at":  { "type": ["string","null"], "format": "date-time" },
    "last_sync_at":  { "type": ["string","null"], "format": "date-time" }
  },
  "required": ["device_id", "ip"]
}
```

**Endpoints:**

| Method | Path | Status | Body |
|---|---|---|---|
| POST  | `/api/v1/devices` | 201 | `DeviceUpsertRequest` — upsert by `device_id`. |
| GET   | `/api/v1/devices` | 200 | none. Returns `{ "rows": [...] }`. |
| PATCH | `/api/v1/devices/{device_id}` | 200 / 404 | `DevicePatchRequest` — partial. |

### 3.3 Key Identifiers
- **Primary key:** `device_id` (TEXT). Uniqueness enforced by SQL.
- The pair `(ip, port)` is **not** unique; multiple `device_id`s with the same
  IP are allowed and have been observed in multi-tenant setups.

### 3.4 Relationships
- 1 device ↔ N **command_jobs** (queue items addressed by `device_id`).
- 1 device ↔ N **attendance_events** (events tagged with `device_id`).
- 0..1 device ↔ **agent_nodes** (an agent process reports on a `site_id` and
  optionally claims commands for multiple `device_id`s).

### 3.5 K95 ERP → Middleware Mapping (`HRMSDevice` / equivalent)

| K95 ERP Field (Our App) | Middleware Field (Target) | Transformation / Derivation Rules |
|---|---|---|
| `HRMSDevice.device_id` | `device_id` | Direct. Treat as opaque string; never reuse a retired `device_id`. |
| `HRMSDevice.display_name` | `device_name` | Direct. |
| `HRMSDevice.branch` | `site_id` | Direct. |
| `HRMSDevice.ip_address` | `ip` | Direct, IPv4 only. |
| `HRMSDevice.port` | `port` | Direct, integer. Default 5005. |
| `HRMSDevice.machine_number` | `machine_number` | Direct, integer ≥ 1. Default 1. |
| `HRMSDevice.machine_password` | `machine_password` | **Stringify as digits.** Must match `^[0-9]*$`. Use `"0"` if your ERP stores integer 0. |
| `HRMSDevice.timezone` | `timezone` | Direct, IANA TZ name. Default `Asia/Kolkata`. |
| `HRMSDevice.is_active` | `is_active` | Direct boolean. Setting to `false` causes the connection resolver (§2.3) to reject `device_id` lookups with `400`. |
| _(implicit)_ | `sdk_protocol` | Always `"sbxpc_tcp"` for the current SDK. Enum-locked. |
| `HRMSGatewayURL.base_url` | _(not stored)_ | Stored in the ERP only; identifies which middleware instance owns this device. |
| `HRMSGatewayURL.middleware_api_key` | `x-api-key` header | Used on every call to the middleware. **Never include in the body.** |

Server-derived (do **not** send): `created_at`, `updated_at`, `last_seen_at`,
`last_sync_at`.

### 3.6 Data Integrity & Validation Rules
- `device_id` required, non-empty.
- `ip` required (`400 ip is required` otherwise).
- `port`: `1..65535`. Out-of-range → `422`.
- `machine_number`: `≥ 1`.
- `sdk_protocol`: currently fixed to `"sbxpc_tcp"`.
- `machine_password`: empty string allowed; otherwise must be all digits.
  Validated as numeric again on every machine call before being passed to the
  SDK (it expects an int).
- **Upsert by `device_id`** — safe to retry; second POST with same `device_id`
  updates the row in place and bumps `updated_at`.

### 3.7 Known Issues & Considerations
- `machine_password` is **string in the device record but int when handed to
  the SDK**. The middleware does the conversion on the fly. If the device row
  has a non-numeric password, machine operations fail with `400` before any
  SDK call is attempted.
- `last_seen_at` is updated only by the (optional) agent's heartbeat — if you
  are running in direct-call mode (no agent), this column remains `NULL`.
  Don't depend on it for liveness detection in the web app; instead call
  `POST /api/machine/test-connection` with `{"device_id": "..."}`.
- The schema accepts `is_active=false`, but the connection resolver (§2.3)
  rejects inactive devices with `400`. The web app should soft-list inactive
  devices but disable provisioning UI for them.

---

## 4. Command Job

### 4.1 Purpose & Role
An async work item the middleware enqueues for an **agent** to execute against
a specific device. The web app uses this entity when it does **not** want to
block on an SDK call (e.g., enable/disable an employee on a device that may be
temporarily offline). For most enable/disable/delete flows, the per-device
shortcuts return a Command Job in `PENDING` state and the web app polls
`GET /api/v1/commands/{command_id}` for the outcome.

Persisted in `command_jobs` (current state) + `command_history` (audit trail).

### 4.2 Full JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "CommandJob",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "command_id":  { "type": "string", "description": "Server-assigned UUID. Primary key." },
    "request_id":  { "type": "string", "description": "Caller-supplied idempotency token. Globally unique. Reusing the same request_id returns the existing command instead of creating a duplicate." },
    "device_id":   { "type": "string", "description": "Target biometric machine." },
    "command_type":{ "type": "string", "enum": ["employee.enable","employee.disable","employee.delete","sync.time","sync.employees","test.connection","xml.execute"], "description": "Action the agent must perform. The web app produces only the first three via the per-employee endpoints." },
    "payload":     { "type": "object", "additionalProperties": true, "description": "Free-form. For employee.* commands the middleware automatically injects { 'employee_code': '...' }." },
    "status":      { "type": "string", "enum": ["PENDING","CLAIMED","RETRY","SUCCESS","FAILED","DEAD"], "description": "Lifecycle state. See §4.4." },
    "priority":    { "type": "integer", "minimum": 1, "maximum": 1000, "default": 100, "description": "Lower number = claimed sooner (queue is ORDER BY priority ASC, created_at ASC). 1 is most urgent; 1000 is least." },
    "retry_count": { "type": "integer", "minimum": 0 },
    "next_attempt_at": { "type": "string", "format": "date-time" },
    "claimed_at":  { "type": ["string","null"], "format": "date-time" },
    "claimed_by":  { "type": ["string","null"], "description": "agent_id of the claimer." },
    "completed_at":{ "type": ["string","null"], "format": "date-time" },
    "error_code":  { "type": ["string","null"] },
    "last_error":  { "type": ["string","null"] },
    "created_at":  { "type": "string", "format": "date-time" },
    "updated_at":  { "type": "string", "format": "date-time" }
  },
  "required": ["command_id","request_id","device_id","command_type","status","priority"]
}
```

**Web-app-facing endpoints (the only ones you should call):**

| Method | Path | Status | Body | What it enqueues |
|---|---|---|---|---|
| POST   | `/api/v1/devices/{device_id}/employees/{employee_code}/enable`  | 202 | `DeviceScopedCommandRequest` | `command_type="employee.enable"` |
| POST   | `/api/v1/devices/{device_id}/employees/{employee_code}/disable` | 202 | `DeviceScopedCommandRequest` | `command_type="employee.disable"` |
| DELETE | `/api/v1/devices/{device_id}/employees/{employee_code}`         | 202 | `DeviceScopedCommandRequest` | `command_type="employee.delete"` |
| GET    | `/api/v1/commands/{command_id}` | 200 / 404 | — | Poll status. |
| GET    | `/api/v1/commands?device_id=&status=&limit=` | 200 | — | List for diagnostics. |

`DeviceScopedCommandRequest` body:
```json
{ "request_id": "REQ-20260512-0001", "payload": {}, "priority": 100 }
```
Only `request_id` is required.

**Enable example — request:**
```http
POST /api/v1/devices/DEVICE001/employees/E001/enable
x-api-key: <middleware_api_key>
Content-Type: application/json

{ "request_id": "REQ-20260512-0001", "priority": 100 }
```
**Response `202 Accepted`:**
```json
{
  "command_id": "cmd_8c1f3a...",
  "request_id": "REQ-20260512-0001",
  "device_id": "DEVICE001",
  "command_type": "employee.enable",
  "payload": { "employee_code": "E001" },
  "status": "PENDING",
  "priority": 100,
  "retry_count": 0,
  "next_attempt_at": "2026-05-12T10:30:00Z",
  "claimed_at": null,
  "claimed_by": null,
  "completed_at": null,
  "error_code": null,
  "last_error": null,
  "created_at": "2026-05-12T10:30:00Z",
  "updated_at": "2026-05-12T10:30:00Z"
}
```

**Polling for completion:**
```http
GET /api/v1/commands/cmd_8c1f3a...
```
Successful completion (note: status moves to `SUCCESS`, **not** `COMPLETED`):
```json
{
  "command_id": "cmd_8c1f3a...",
  "status": "SUCCESS",
  "completed_at": "2026-05-12T10:31:02Z",
  "claimed_at": "2026-05-12T10:30:30Z",
  "claimed_by": "AGENT_PLANT_A",
  "error_code": null,
  "last_error": null
}
```

### 4.3 Key Identifiers
- **Primary key:** `command_id` (server-generated UUID, opaque).
- **Idempotency key:** `request_id` — declared `UNIQUE` in SQL. Re-submitting
  a POST with the same `request_id` returns the **existing** command record
  instead of creating a duplicate. Use this aggressively from the web app to
  survive retries.

### 4.4 Lifecycle / State Machine

```
                ┌─────────┐
        POST →  │ PENDING │
                └────┬────┘
                     │ agent claim
                     ▼
                ┌─────────┐
                │ CLAIMED │
                └────┬────┘
                     │ agent reports result
            ┌────────┼────────┐
            ▼        ▼        ▼
        ┌───────┐ ┌───────┐ ┌───────┐
        │SUCCESS│ │FAILED │ │ RETRY │  (transient error, exponential backoff)
        └───────┘ └───────┘ └──┬────┘
                                │ retry budget exhausted
                                ▼
                            ┌───────┐
                            │  DEAD │
                            └───────┘
```

- **PENDING:** queued, not yet claimed. The queue is ordered
  `ORDER BY priority ASC, created_at ASC` — lower `priority` number is claimed
  first.
- **CLAIMED:** picked up by `claimed_by` agent at `claimed_at`. If the agent
  crashes mid-flight, a sweeper returns the row to `PENDING`/`RETRY` after a
  visibility timeout.
- **SUCCESS:** terminal. `completed_at` is set. `payload` and result details
  are queryable via `GET /api/v1/commands/{command_id}` and
  `command_history`.
- **FAILED:** terminal but with `error_code` / `last_error` populated.
- **RETRY:** transient failure; next attempt scheduled at `next_attempt_at`.
- **DEAD:** retry budget exhausted; nothing else will happen automatically.
  Manual recovery is via re-submitting with a fresh `request_id`.

### 4.5 Relationships
- `device_id` → **Device Configuration** (§3). FK-like; existence is not
  enforced by SQL but the agent will fail the command if the device row is
  missing.
- `payload.employee_code` → **Employee Master Record** (§1) for `employee.*`
  command types. Injected automatically by the per-device endpoints.
- Each state transition writes one row to `command_history` (audit).

### 4.6 K95 ERP → Middleware Mapping
Commands are produced from ERP user actions rather than from an ERP entity:

| K95 ERP Action / Field | Middleware Field | Transformation |
|---|---|---|
| "Enable user on device" button | `command_type` | Always `"employee.enable"`. |
| "Disable user on device" button | `command_type` | Always `"employee.disable"`. |
| "Remove user from device" button | `command_type` | Always `"employee.delete"`. |
| Selected `device.device_id` | `device_id` (path param) | Direct. |
| Selected `employee.employee_code` | `employee_code` (path param, then injected into `payload`) | Direct. |
| Caller-generated idempotency token | `request_id` | Use a UUIDv4 or a deterministic `"REQ-{date}-{seq}"`. |
| User-selected urgency | `priority` | Map your UI (e.g., "Now"=1, "Normal"=100, "Background"=500). |

### 4.7 Data Integrity & Validation Rules
- `request_id` **must be globally unique**. Conflicts return the existing row
  (idempotent) rather than `400`.
- `priority`: `1..1000`. Out-of-range → `422`.
- `command_type` must be one of the recognized values; unrecognized values are
  enqueued anyway but the agent will mark them `FAILED` with `error_code =
  "UNSUPPORTED_COMMAND_TYPE"`.
- The per-device path-style endpoints (`/enable`, `/disable`, `delete`)
  automatically inject `employee_code` into the payload; do not duplicate it.

### 4.8 Known Issues & Considerations
- The TECHNICAL_SPECIFICATION_API.md document states "Higher priority = more
  urgent." The **code disagrees**: the queue is `ORDER BY priority ASC`, so
  **lower priority wins**. Follow the code: `1` = most urgent, `1000` = least.
- The integration guide examples sometimes show `"status": "QUEUED"` for a
  newly created command. The actual DB default and API response is `"PENDING"`.
  Treat `"QUEUED"` as legacy/aliased; check for `"PENDING"`.
- Completion status is `"SUCCESS"` (not `"COMPLETED"`). The integration guide
  example for `GET /api/v1/commands/{id}` shows `"COMPLETED"` in places — the
  code uses `"SUCCESS"`. Match on **both** to be safe if you must support old
  middleware versions.
- The `payload` for `employee.delete` includes the same `employee_code` field
  as `employee.enable`/`disable` — there is no "soft delete on device" option;
  the agent calls `DeleteEnrollData` for all slots.
- An agent must be running for these commands to make progress. With no agent,
  `command_jobs` rows stay `PENDING` indefinitely. If the web app needs
  synchronous behavior, prefer the inline `machine.sync_to_machine: true` path
  on `POST /api/v1/employees` (§2) or the direct `/api/machine/employees/*`
  endpoints, which execute on the middleware host itself.

---

## 5. Attendance Event

### 5.1 Purpose & Role
A single biometric punch record captured by the middleware. The web app
typically only **reads** this entity (to render attendance lists and dashboards);
the production path that **writes** it is either machine-pushed
(`/machine/realtime_glog`) or agent-batched (`/api/v1/agent/attendance/batch`).

Persisted in `attendance_events` with a `UNIQUE` index on `idempotency_key`.

### 5.2 Full JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AttendanceEvent",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "event_id":         { "type": "string", "description": "Primary key. Server-generated if not supplied." },
    "idempotency_key":  { "type": "string", "description": "UNIQUE. Suggested pattern: '{device_id}:{machine_user_id}:{timestamp_utc}'." },
    "agent_id":         { "type": ["string","null"] },
    "device_id":        { "type": "string" },
    "device_ip":        { "type": ["string","null"], "format": "ipv4" },
    "employee_code":    { "type": "string", "description": "Resolved by the middleware via employee_master.employee_code_normalized when the device only knows the user_id." },
    "machine_user_id":  { "type": ["string","null"], "description": "The numeric user_id the device emitted; stored as string for portability." },
    "timestamp_local":  { "type": "string", "description": "Wall-clock at the device, ISO-like 'YYYY-MM-DD HH:MM:SS'." },
    "timestamp_utc":    { "type": "string", "format": "date-time" },
    "timezone":         { "type": "string", "description": "IANA TZ used to convert local→UTC." },
    "verification_mode":{ "type": ["string","null"], "description": "e.g. 'fingerprint','card','password'." },
    "source":           { "type": "string", "enum": ["pull_sdk","push_realtime","manual","backfill"] },
    "raw_payload":      { "type": ["object","null"], "description": "Vendor blob, opaque to the web app." },
    "created_at":       { "type": "string", "format": "date-time" },
    "synced_at":        { "type": ["string","null"], "format": "date-time", "description": "Set when this event was forwarded to the outbound consumer." }
  },
  "required": ["event_id","idempotency_key","device_id","employee_code","timestamp_local","timestamp_utc","timezone","source"]
}
```

### 5.3 Endpoints relevant to the web app

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/attendance?device_id=&employee_code=&from_utc=&to_utc=&limit=` | middleware | Filtered list. `limit` defaults to 500, max 5000. |
| GET | `/api/attendances?employee_code=&device_sn=&limit=` | middleware | Legacy dashboard list. Use only for backwards compatibility. |

The web app should **not** write events directly. If the K95 ERP needs to
backfill, do it via the agent batch endpoint, which is auth-scoped to agents
and writes through the dedup pipeline.

### 5.4 Key Identifiers & Dedup
- **Primary key:** `event_id`.
- **Dedup key:** `idempotency_key` (UNIQUE). Resubmits with the same key are
  silently dropped — this is how the system survives machine-side replays.

### 5.5 Relationships
- `device_id` → Device Configuration (§3).
- `employee_code` → Employee Master Record (§1). Resolution happens by the
  middleware mapping `machine_user_id` → `employee_master` via
  `employee_code_normalized`.

### 5.6 K95 ERP → Middleware Mapping
The K95 ERP **does not write** attendance events. It reads them and forwards
to its own time-and-attendance pipeline. Suggested ERP-side shape:

| Middleware Field | K95 ERP Attendance Field | Notes |
|---|---|---|
| `event_id` | `attendance.external_id` | Dedup on this. |
| `employee_code` | `attendance.employee_code` | Direct. |
| `device_id` | `attendance.source_device_id` | Direct. |
| `timestamp_utc` | `attendance.punch_utc` | Use UTC for storage. |
| `timestamp_local` + `timezone` | `attendance.punch_local`, `attendance.punch_tz` | Optional, for display. |
| `verification_mode` | `attendance.mode` | Optional. |

### 5.7 Validation & Known Issues
- Events with an unknown `machine_user_id` are still recorded with
  `employee_code = machine_user_id` and a marker in `raw_payload` — the K95
  ERP must handle "unresolved" attendance gracefully.
- Reading is **eventually consistent** with the punch; if you're listing
  attendance the moment after a punch, expect 1–3 s latency in push mode and
  up to one agent poll cycle in pull mode.

---

## 6. Master Data Record

### 6.1 Purpose & Role
Lookup tables that constrain the values of `department`, `designation`,
`office_time_policy`, `company_name`, `branch_name`, `shift_code` on the
Employee Master Record. These exist primarily for the dashboard and for
**soft** validation; they are **not** FK-enforced on `employee_master`.

The K95 ERP can use these to populate dropdowns or to validate before sending
employee POSTs.

### 6.2 Full JSON Schema (one schema, applied per `master_type`)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "MasterDataRecord",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "code":        { "type": "string", "minLength": 1, "description": "Primary key within its master_type." },
    "name":        { "type": "string", "minLength": 1 },
    "description": { "type": ["string","null"] },
    "is_active":   { "type": "boolean", "default": true },
    "created_at":  { "type": "string", "format": "date-time" },
    "updated_at":  { "type": "string", "format": "date-time" }
  },
  "required": ["code","name"]
}
```

Supported `master_type` values (enum-locked server-side):
- `departments` → `department_master`
- `designations` → `designation_master`
- `office_time_policies` → `office_time_policy_master`
- `companies` → `company_master`
- `branches` → `branch_master`
- `shift_codes` → `shift_code_master`

### 6.3 Endpoints

| Method | Path | Status |
|---|---|---|
| GET    | `/api/v1/master/types` | 200 |
| GET    | `/api/v1/master/{master_type}?is_active=&limit=` | 200 |
| GET    | `/api/v1/master/{master_type}/{code}` | 200 / 404 |
| POST   | `/api/v1/master/{master_type}` | 201 / 200 (`action: "updated"`) |
| PATCH  | `/api/v1/master/{master_type}/{code}` | 200 / 400 / 404 |
| DELETE | `/api/v1/master/{master_type}/{code}` | 200 / 404 |

Unsupported `master_type` → `400`.

### 6.4 K95 ERP → Middleware Mapping

| K95 ERP Field | Middleware Field | master_type |
|---|---|---|
| `department.code` | `code` | `departments` |
| `department.name` | `name` | `departments` |
| `designation.code` | `code` | `designations` |
| `branch.code` | `code` | `branches` |
| `shift.code` | `code` | `shift_codes` |
| `company.code` | `code` | `companies` |
| `office_policy.code` | `code` | `office_time_policies` |

### 6.5 Known Issues
- `is_active=false` rows are returned by default GET unless you filter
  `?is_active=true`. The web app should pass the filter when populating
  dropdowns.
- `code` is **case-sensitive** in SQLite. Use a consistent case (uppercase
  recommended) across ERP and middleware.

---

## 7. Webhook Subscription

### 7.1 Purpose & Role
Allows the K95 ERP to receive outbound POSTs from the middleware for events of
interest (e.g., attendance recorded, employee provisioned). The web app
typically configures these once at install time and rarely touches them
afterwards.

Persisted in `webhook_subscriptions`; deliveries persisted in
`webhook_deliveries` with retry/dead-letter logic.

### 7.2 Full JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "WebhookSubscription",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "subscription_id": { "type": ["string","null"], "description": "Caller-supplied. Server generates one if omitted." },
    "event_type":      { "type": "string", "description": "Suggested values: 'attendance.created', 'employee.provisioned', 'employee.enabled', 'employee.disabled', 'employee.deleted'." },
    "target_url":      { "type": "string", "format": "uri" },
    "is_active":       { "type": "boolean", "default": true },
    "created_at":      { "type": "string", "format": "date-time" },
    "updated_at":      { "type": "string", "format": "date-time" }
  },
  "required": ["event_type","target_url"]
}
```

### 7.3 Endpoints

| Method | Path | Body |
|---|---|---|
| POST | `/api/v1/webhooks/subscriptions` | `WebhookSubscriptionRequest` |
| GET  | `/api/v1/webhooks/subscriptions` | — |
| GET  | `/api/v1/webhooks/deliveries?status=&limit=` | — |
| POST | `/api/v1/webhooks/events/{event_type}` | `{ "event_id"?: "...", "payload": {...} }` (manual enqueue) |
| POST | `/api/v1/webhooks/dispatch` | `{ "limit": 50 }` (force flush) |
| POST | `/api/v1/webhooks/retry/{delivery_id}` | — |

Retry schedule: `1m → 5m → 15m → 60m`, then `DEAD`.
HMAC signing key is configured by middleware setting `webhook_hmac_secret`.

### 7.4 Known Issues
- `event_type` is a free-form string, not an enum. Standardize on the values
  in §7.2 across ERP and middleware.
- The middleware will retry indefinitely until the consumer responds `2xx` —
  ensure the K95 ERP's webhook handler is idempotent on `event_id`.

---

## 8. Agent Node

### 8.1 Purpose & Role
Represents a long-running agent process (separate from the web app) that
claims commands and pushes attendance batches. The web app **does not write
to** this entity; it is documented here so the SE agent understands what the
`claimed_by` field on Command Jobs refers to.

Persisted in `agent_nodes`.

### 8.2 Full JSON Schema (read-only from the web app's perspective)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AgentNode",
  "type": "object",
  "properties": {
    "agent_id":     { "type": "string" },
    "site_id":      { "type": ["string","null"] },
    "version":      { "type": ["string","null"] },
    "host_name":    { "type": ["string","null"] },
    "local_ip":     { "type": ["string","null"] },
    "status":       { "type": "string", "enum": ["ONLINE","OFFLINE"], "default": "ONLINE" },
    "last_seen_at": { "type": "string", "format": "date-time" },
    "details_json": { "type": ["string","null"] }
  },
  "required": ["agent_id","status","last_seen_at"]
}
```

### 8.3 Relationships
- `agent_id` → Command Job `claimed_by`.
- `site_id` → Device Configuration `site_id` (logical grouping).

### 8.4 Known Issues
- An agent claiming commands holds an exclusive lease; if a node goes
  offline mid-work, the command rolls back to `PENDING` after the visibility
  timeout. The web app should reflect "claimed for >60 s" as "in progress",
  not "stuck".

---

## 9. Cross-Entity Reference: End-to-End Provisioning Flow

This is the typical sequence the web app should implement.

```
ERP UI: "Add employee + assign to Delhi reader"
        │
        ▼
1. POST /api/v1/employees                    ── creates Employee Master Record (§1)
   {
     "employee_code":"E0001",
     "employee_name":"John Doe",
     "card_no":"12345678",
     "machine": {                            ── triggers inline machine sync (§2)
       "sync_to_machine": true,
       "device_id": "DELHI-F1-M1",
       "enable": true
     }
   }
        │
        ├─► 201 + machine_sync.success=true  ── done; employee on device
        │
        └─► machine_sync.success=false (502) ── employee saved in ERP only; fall back to async:
                │
                ▼
                POST /api/v1/devices/DELHI-F1-M1/employees/E0001/enable
                                                       ── enqueues Command Job (§4)
                │
                ▼
                Poll GET /api/v1/commands/{command_id}
                until status ∈ {SUCCESS, FAILED, DEAD}

Later: ERP UI: "Suspend employee on device"
        │
        ▼
   POST /api/v1/devices/DELHI-F1-M1/employees/E0001/disable
        │
        ▼
   Poll command_id → SUCCESS

Punches arrive over time:
        │
        ▼
   GET /api/v1/attendance?employee_code=E0001  (§5)
   OR receive Webhook (§7) at the ERP's /webhooks/attendance handler
```

---

## 10. Quick Reference: Validation cheatsheet

| Field | Type | Rule | Where enforced |
|---|---|---|---|
| `employee_code` | string | non-empty | Pydantic + handler |
| `card_no` (machine-bound) | string | parseable as unsigned ≤ `(2^64)-1`; else falls back to `user_id` | `parse_unsigned_integer` |
| `machine.user_id` | integer | `0..2_147_483_647` | Pydantic |
| `device_id` | string | non-empty | Pydantic |
| `ip` | string | non-empty; resolver also rejects when device inactive | handler |
| `port` | integer | `1..65535` | Pydantic |
| `machine_number` | integer | `≥ 1` | Pydantic |
| `e_machine_number` | integer | `≥ 1` | Pydantic |
| `backup_number` | integer | `≥ 0` | Pydantic |
| `machine_password` (device row) | string | `^[0-9]*$` (validated again before SDK call) | handler |
| `machine_password` (employee.machine block) | integer | none, but must fit machine SDK int | Pydantic |
| `priority` (command) | integer | `1..1000`; **lower = more urgent** | Pydantic + queue order |
| `request_id` (command) | string | globally unique; duplicate returns existing | SQL UNIQUE |
| `master_type` | string | enum of 6 values (§6.2) | handler |
| `sdk_protocol` | string | enum `"sbxpc_tcp"` | Pydantic |

---

## 11. Known cross-document inconsistencies (resolved here)

These are minor disagreements between `API_INTEGRATION_GUIDE.md` and
`TECHNICAL_SPECIFICATION_API.md` that this document resolves in favor of the
actual source code:

| Topic | Older docs say | Code says | Use |
|---|---|---|---|
| Command `priority` semantics | "Higher = more urgent" | `ORDER BY priority ASC` → lower = more urgent | **Lower = more urgent.** |
| Newly created command status | `"QUEUED"` in some examples | `'PENDING'` default in `command_jobs` | **`PENDING`.** |
| Command completion status | `"COMPLETED"` in some examples | `"SUCCESS"` in `command_history` and result writes | **`SUCCESS`** (and `FAILED`/`DEAD`). |
| `/api/v1/health` auth | "Required" in technical spec | No auth check in `ingress_app.py` | No auth needed today, but the K95 ERP should still send the API key for forward-compat. |
| `device.machine_password` type | Sometimes string, sometimes int | String at device-row schema (`^[0-9]*$`), int when handed to SDK | **String at the API boundary; convert to int inside the middleware.** |

---

## 12. References (file paths, for the SE agent to grep further)

- Pydantic request models: `HR Module/src/attendance_relay/middleware_models.py`
- SQL DDL: `HR Module/src/attendance_relay/db.py`
- HTTP routes / status codes: `HR Module/src/attendance_relay/ingress_app.py`
- Machine connection resolver + per-employee SDK ops:
  `HR Module/src/attendance_relay/machine_admin.py`
- `user_id` / `card_no` / `user_name` derivation:
  `HR Module/src/attendance_relay/machine_sync.py`
  (`choose_machine_user_id`, `choose_card_number`, `choose_user_name`)
- `employee_code_normalized` derivation:
  `HR Module/src/attendance_relay/master_data.py` (`normalize_employee_code`)
- Command queue lifecycle: `HR Module/src/attendance_relay/middleware_repository.py`
- Companion docs:
  - `HR Module/docs/API_INTEGRATION_GUIDE.md` (deployment + curl examples)
  - `HR Module/docs/TECHNICAL_SPECIFICATION_API.md` (alternate detailed reference)
