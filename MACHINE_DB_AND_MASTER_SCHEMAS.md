# Machine + Database Schemas (SDK-Derived)

Last generated: 2026-05-08

## 1) Scope and Source of Truth

This document contains:

1. Local middleware database schemas (live SQLite introspection from `attendance.db`)
2. Machine-side data schemas derived from SDK exports and XML request inventory

Sources used:

- `docs/sdk_inventory/api_functions.txt`
- `docs/sdk_inventory/request_names.txt`
- `docs/sdk_inventory/xml_tags.txt`
- `src/attendance_relay/db.py`
- Live `attendance.db` table introspection

Important limitation:

- SBXPC SDK does **not** expose a full relational "database schema dump" of the machine.
- So machine schemas below are the **operation-level record schemas** (function/XML payload schemas), which is the practical schema contract available from SDK.


## 2) Local Middleware Database Schemas

## 2.1 `tbl_realtime_glog`

- `id` INTEGER PK
- `employee_code` TEXT NOT NULL
- `log_datetime` TEXT NOT NULL
- `log_time` TEXT NOT NULL
- `downloaded_at` TEXT NOT NULL
- `device_sn` TEXT NOT NULL
- `raw_user_id` TEXT NOT NULL
- `raw_io_time` TEXT NOT NULL
- `source_ip` TEXT NULL
- `raw_preview` TEXT NULL
- `created_at` TEXT NOT NULL

## 2.2 `attendance_outbox`

- `id` INTEGER PK
- `event_hash` TEXT NOT NULL UNIQUE
- `employee_code` TEXT NOT NULL
- `log_datetime` TEXT NOT NULL
- `log_time` TEXT NOT NULL
- `downloaded_at` TEXT NOT NULL
- `device_sn` TEXT NOT NULL
- `status` TEXT NOT NULL
- `attempt_count` INTEGER NOT NULL
- `max_retries` INTEGER NOT NULL
- `next_attempt_at` TEXT NOT NULL
- `processing_started_at` TEXT NULL
- `lease_until` TEXT NULL
- `sent_at` TEXT NULL
- `last_error` TEXT NULL
- `response_code` INTEGER NULL
- `response_body` TEXT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

## 2.3 `employee_master`

- `employee_code` TEXT PK
- `employee_code_normalized` TEXT NOT NULL
- `employee_name` TEXT NULL
- `father_name` TEXT NULL
- `card_no` TEXT NULL
- `proximity_card_no` TEXT NULL
- `email_id` TEXT NULL
- `phone_no` TEXT NULL
- `department` TEXT NULL
- `designation` TEXT NULL
- `branch_name` TEXT NULL
- `office_time_policy` TEXT NULL
- `date_of_birth` TEXT NULL
- `date_of_join` TEXT NULL
- `shift_start_date` TEXT NULL
- `shift_code` TEXT NULL
- `weekly_off` TEXT NULL
- `company_name` TEXT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

## 2.4 Master Tables

These six share the same schema shape:

- `code` TEXT PK
- `name` TEXT NOT NULL
- `description` TEXT NULL
- `is_active` INTEGER NOT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

Tables:

1. `department_master`
2. `designation_master`
3. `office_time_policy_master`
4. `company_master`
5. `branch_master`
6. `shift_code_master`

## 2.5 `devices`

- `device_id` TEXT PK
- `device_name` TEXT NULL
- `site_id` TEXT NULL
- `ip` TEXT NOT NULL
- `port` INTEGER NOT NULL
- `timezone` TEXT NOT NULL
- `is_active` INTEGER NOT NULL
- `sdk_protocol` TEXT NOT NULL
- `machine_password` TEXT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL
- `last_seen_at` TEXT NULL
- `last_sync_at` TEXT NULL

## 2.6 `agent_nodes`

- `agent_id` TEXT PK
- `site_id` TEXT NULL
- `version` TEXT NULL
- `host_name` TEXT NULL
- `local_ip` TEXT NULL
- `status` TEXT NOT NULL
- `last_seen_at` TEXT NOT NULL
- `details_json` TEXT NULL

## 2.7 `attendance_events`

- `event_id` TEXT PK
- `idempotency_key` TEXT NOT NULL UNIQUE
- `agent_id` TEXT NULL
- `device_id` TEXT NOT NULL
- `device_ip` TEXT NULL
- `employee_code` TEXT NOT NULL
- `machine_user_id` TEXT NULL
- `timestamp_local` TEXT NOT NULL
- `timestamp_utc` TEXT NOT NULL
- `timezone` TEXT NOT NULL
- `verification_mode` TEXT NULL
- `source` TEXT NOT NULL
- `raw_payload` TEXT NULL
- `created_at` TEXT NOT NULL
- `synced_at` TEXT NULL

## 2.8 `command_jobs`

- `command_id` TEXT PK
- `request_id` TEXT NOT NULL UNIQUE
- `device_id` TEXT NOT NULL
- `command_type` TEXT NOT NULL
- `payload_json` TEXT NOT NULL
- `status` TEXT NOT NULL
- `priority` INTEGER NOT NULL
- `retry_count` INTEGER NOT NULL
- `next_attempt_at` TEXT NOT NULL
- `claimed_at` TEXT NULL
- `claimed_by` TEXT NULL
- `completed_at` TEXT NULL
- `error_code` TEXT NULL
- `last_error` TEXT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

## 2.9 `command_history`

- `id` INTEGER PK
- `command_id` TEXT NOT NULL
- `attempt_no` INTEGER NOT NULL
- `agent_id` TEXT NOT NULL
- `status` TEXT NOT NULL
- `error_code` TEXT NULL
- `error_message` TEXT NULL
- `result_json` TEXT NULL
- `started_at` TEXT NOT NULL
- `finished_at` TEXT NOT NULL

## 2.10 `webhook_subscriptions`

- `subscription_id` TEXT PK
- `event_type` TEXT NOT NULL
- `target_url` TEXT NOT NULL
- `is_active` INTEGER NOT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

## 2.11 `webhook_deliveries`

- `delivery_id` TEXT PK
- `subscription_id` TEXT NOT NULL
- `event_type` TEXT NOT NULL
- `event_id` TEXT NOT NULL
- `target_url` TEXT NOT NULL
- `payload_json` TEXT NOT NULL
- `status` TEXT NOT NULL
- `attempt_no` INTEGER NOT NULL
- `next_attempt_at` TEXT NOT NULL
- `last_status_code` INTEGER NULL
- `last_error` TEXT NULL
- `last_response` TEXT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

## 2.12 `dead_letter_events`

- `id` INTEGER PK
- `entity_type` TEXT NOT NULL
- `entity_id` TEXT NOT NULL
- `reason` TEXT NOT NULL
- `payload_json` TEXT NULL
- `created_at` TEXT NOT NULL


## 3) Machine-Side Schemas (From SDK)

## 3.1 Core Connection Schema

Confirmed from wrapper/API:

```json
{
  "device_id": "string|null",
  "machine_ip": "string|null",
  "machine_port": "int|null",
  "machine_password": "int|null",
  "machine_number": "int|null",
  "sdk_dll_path": "string|null"
}
```

## 3.2 Machine User Slot Record Schema

Confirmed by `_ReadAllUserID` + `_GetAllUserID`:

```json
{
  "user_id": "int",
  "e_machine_number": "int",
  "backup_number": "int",
  "machine_privilege": "int",
  "enabled": "bool"
}
```

## 3.3 User Profile Schema

Confirmed by XML request names `GetUserInfo` / `SetUserInfo` and tags:

```json
{
  "UserID": "int",
  "EnrollNumber": "int|string",
  "Privilege": "int",
  "Enable": "bool",
  "GroupNo": "int",
  "Timezone1": "int",
  "Timezone2": "int",
  "Timezone3": "int (model-dependent)",
  "CardNo_Low": "uint32 string/int",
  "CardNo_High": "uint32 string/int"
}
```

## 3.4 Credential Schemas

Evidence:

- API functions: `_GetEnrollData*`, `_SetEnrollData*`, `_DeleteEnrollData*`
- XML requests: `GetEnrollDataCARD/FP/PWD`, `SetEnrollDataCARD/FP/PWD`, `DeleteEnrollData*`

Canonical structure:

```json
{
  "UserID|EnrollNumber": "int|string",
  "Backup|BackupNumber": "int",
  "Privilege": "int",
  "Template|Password|CardNum": "binary|string|int (type-dependent)"
}
```

## 3.5 User Photo Schema

Evidence:

- XML requests: `GetUserPhotoData`, `SetUserPhotoData`, `ClearPhoto`
- Tags: `PhotoData`, `PhotoSize`, `PhotoType`, `PhotoPos`, `Photo`

```json
{
  "UserID": "int",
  "PhotoType": "int",
  "PhotoSize": "int",
  "PhotoData": "binary/base64",
  "PhotoPos": "int (optional)"
}
```

## 3.6 Attendance General Log Record Schema

Evidence:

- `_ReadAllGLogData`, `_GetAllGLogData`, `_GetAllGLogData_Ext`
- XML related tags: `StartPos`, `EndPos`, `LogCount`

Function-level record shape:

```json
{
  "t_machine_number": "int",
  "enroll_number": "int",
  "e_machine_number": "int",
  "verify_mode": "int",
  "year": "int",
  "month": "int",
  "day": "int",
  "hour": "int",
  "minute": "int",
  "second": "int",
  "glog_ext": "int (ext variant only)"
}
```

## 3.7 Super Log Record Schema

Evidence:

- `_ReadAllSLogData`, `_GetAllSLogData`

```json
{
  "t_machine_number": "int",
  "s_enroll_number": "int",
  "s_machine_number": "int",
  "g_enroll_number": "int",
  "g_machine_number": "int",
  "manipulation": "int",
  "backup_number": "int",
  "year": "int",
  "month": "int",
  "day": "int",
  "hour": "int",
  "minute": "int",
  "second": "int"
}
```

## 3.8 Device Metadata Schema

Evidence:

- `_GetDeviceInfo`, `_GetDeviceModel`, `_GetSerialNumber`
- XML request: `GetDeviceDetails`, `GetDeviceInfoExt`
- Tags: `MachineID`, `MachineType`, `DeviceID`, `ResultCode`, `ErrStr`

```json
{
  "MachineID": "int",
  "DeviceID": "string",
  "MachineType": "string|int",
  "SerialNumber": "string",
  "ResultCode": "int",
  "ErrStr": "string"
}
```

## 3.9 Department Master Schema (Machine Internal)

Evidence:

- `_GetDepartName(dwDepartNumber, dwDepartOrDaigong, ...)`
- `_SetDepartName(dwDepartNumber, dwDepartOrDaigong, lpszDepartName)`

```json
{
  "depart_number": "int",
  "depart_or_daigong": "int",
  "depart_name": "string"
}
```

## 3.10 Company Master Schema (Machine Internal)

Evidence:

- `_GetCompanyName1`, `_SetCompanyName1`

```json
{
  "company_kind": "int",
  "company_name": "string"
}
```

## 3.11 Group/Timezone/Policy Master Schemas

Evidence:

- Requests: `GetGroupName/SetGroupName`, `GetTimezone/SetTimezone`,
  `GetUserPeriod/SetUserPeriod`, `GetUserHolidays/SetUserHolidays`,
  `GetUserBalanceTime/SetUserBalanceTime`
- Tags: `GroupNo`, `Timezone1..3`, `UserTZ`, `HolidaysInDays10`, `BalanceTimeInMinues`

Representative schema:

```json
{
  "GroupNo": "int",
  "Timezone1": "int",
  "Timezone2": "int",
  "Timezone3": "int",
  "UserTZ": "binary|string",
  "HolidaysInDays10": "binary/string",
  "BalanceTimeInMinues": "int"
}
```

## 3.12 Network/Comm Config Schemas

Evidence:

- Requests: `Get/SetCommSetting`, `Get/SetEthernetSetting`,
  `Get/SetWiFiSetting`, `Get/SetDnsSettings`
- Tags: `IP`, `Port`, `Subnet`, `Gateway`, `SSID`, `DnsServer0IP`, `DnsServer1IP`

```json
{
  "IP": "string",
  "Port": "int",
  "Subnet": "string",
  "Gateway": "string",
  "SSID": "string",
  "DnsServer0IP": "string",
  "DnsServer1IP": "string",
  "UseDHCP": "bool/int",
  "CommPwd": "int|string"
}
```

## 3.13 Door/Access Schema

Evidence:

- Requests: `ReadAccessSetting`, `WriteAccessSetting`, `GetDoorParam`, `SetDoorParam`, `OpenDoor`
- Tags: `DoorNo`, `DoorStatus`, `LockReleaseTime`

```json
{
  "DoorNo": "int",
  "DoorStatus": "int|bool",
  "LockReleaseTime": "int",
  "AccessMode": "int (model-dependent)"
}
```


## 4) Practical Note for HRMS Engineering

When integrating, treat machine schema as:

1. Function-level fixed records (e.g., `_GetAllUserID`, log records)
2. XML request schemas (request name + tag set)

Do not assume full SQL-like internal machine tables are enumerable via SDK; they are not directly exposed that way.
