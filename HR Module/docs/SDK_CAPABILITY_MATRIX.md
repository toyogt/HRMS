# SDK Capability Matrix (SBXPC)

Last updated: 2026-05-07

## 1. Purpose

This document explains:

1. What is included in the `sdk_extracted/20211204-SBXPC-1` package.
2. Which product features can be built using this SDK.
3. Which capabilities are already implemented in this repo.
4. How to discover exactly what your specific machine model supports.

This is an engineering map, not just vendor marketing.

## 2. Evidence Sources Used

This matrix is derived from real files in this repo:

1. SDK C API surface: `sdk_extracted/20211204-SBXPC-1/bin/SBXPCDLL_API.h`
2. Extracted API index: `docs/sdk_inventory/api_functions.txt`
3. Extracted XML request names: `docs/sdk_inventory/request_names.txt`
4. Extracted XML tags: `docs/sdk_inventory/xml_tags.txt`
5. Current Python SDK wrapper: `src/attendance_relay/machine_sdk.py`
6. Current API endpoints: `src/attendance_relay/ingress_app.py`
7. Current machine orchestration: `src/attendance_relay/machine_admin.py`

## 3. What the SDK Package Includes

### 3.1 Top-level package anatomy

The package contains about 1,948 files and about 232.8 MB total (local inspection snapshot).

| Path | Approx size | Purpose |
|---|---:|---|
| `sdk_extracted/20211204-SBXPC-1/bin` | 28.96 MB | Runtime binaries, headers, install batch, libs |
| `sdk_extracted/20211204-SBXPC-1/doc` | 2.05 MB | Vendor reference manual |
| `sdk_extracted/20211204-SBXPC-1/samples` | 200.31 MB | Multi-language sample projects |
| `sdk_extracted/20211204-SBXPC-1/SBXPC` | 0.10 MB | VC++ ActiveX source project |

### 3.2 Runtime layers inside `bin`

| Layer | Key files | Purpose | Needed by this repo |
|---|---|---|---|
| Native DLL API | `SBXPCDLL.dll`, `SBXPCDLL64.dll`, `SBXPCDLL_API.h` | Core machine communication and control functions | Yes |
| COM/ActiveX layer | `SBXPC.ocx`, `_install_sbxpc.bat` | COM registration and OCX usage (`regsvr32 SBXPC.ocx`) | No for current Python flow |
| Java bridge | `x86/SBXPCJavaProxy.dll`, `x64/SBXPCJavaProxy.dll` | JNI proxy for Java sample apps | No for current Python flow |
| Supporting libs | `SBPCCOMM*.dll`, `GEN_FONT*.dll`, etc. | Dependencies used by core operations and sample stacks | Usually yes for runtime compatibility |

### 3.3 Multi-language sample coverage

The sample tree includes C#, VB.NET, Java, Delphi, VB6 implementations. It is useful as behavior reference for tags, request names, and error handling patterns.

## 4. Current App Coverage (What is already built)

### 4.1 Direct machine API endpoints already implemented

From `src/attendance_relay/ingress_app.py`:

1. `POST /api/machine/test-connection`
2. `POST /api/machine/xml/execute`
3. `POST /api/machine/employees/sync`
4. `PUT /api/machine/employees/{employee_code}`
5. `POST /api/machine/employees/{employee_code}/read`
6. `DELETE /api/machine/employees/{employee_code}`
7. `POST /api/machine/employees/{employee_code}/enable`
8. `POST /api/machine/employees/{employee_code}/disable`

### 4.2 SDK functions currently bound in Python wrapper

`src/attendance_relay/machine_sdk.py` currently binds these core functions:

1. `_DotNET`
2. `_ConnectTcpip`, `_Disconnect`
3. `_EnableDevice`, `_EnableUser`
4. `_SetUserName1`, `_GetUserName1`
5. `_ReadAllUserID`, `_GetAllUserID`
6. `_DeleteEnrollData`
7. `_GetDeviceTime`
8. `_GeneralOperationXML`
9. `_XML_Add*` and `_XML_Parse*` helpers
10. `_GetLastError`

This means your app already supports both:

1. Fixed workflows (sync/read/update/delete/toggle users).
2. Extensible XML request execution (high leverage path).

### 4.3 Middleware command queue support (agent-driven path)

The middleware layer also exposes queue-based commands such as:

1. `/api/v1/devices/{device_id}/test-connection`
2. `/api/v1/devices/{device_id}/sync-time`
3. `/api/v1/devices/{device_id}/sync-employees`
4. `/api/v1/devices/{device_id}/xml/execute`
5. `/api/v1/devices/{device_id}/employees/{employee_code}/enable|disable|delete`

These are orchestration endpoints that require an executing agent path.

## 5. Full SDK Capability Map (What you can build)

The SDK surface is broad: around 99 C-exported functions and around 92 XML request names in your inventory snapshot.

| Capability domain | SDK evidence | Features you can build | Repo status |
|---|---|---|---|
| Connectivity/session | `_ConnectTcpip`, `_ConnectSerial`, `_Disconnect`, `_GetLastError` | Health checks, failover strategy, connection diagnostics | Partial (TCP path implemented) |
| Device identity + metadata | `_GetDeviceInfo`, `_GetDeviceModel`, `_GetSerialNumber`, `GetDeviceDetails` | Device inventory, model-aware policy, diagnostics page | Partial (basic connection/time) |
| Time control | `_GetDeviceTime`, `_SetDeviceTime`, `_SetDeviceTime1` | Clock drift detection, auto time-sync jobs | Partial (queue path exists, direct read exists) |
| User profile management | `_SetUserName1`, `_GetUserName1`, `SetUserInfo`, `GetUserInfo`, `SetUserName`, `GetUserName` | Employee push/update/read, reconciliation | Implemented for key flows |
| User enable/disable | `_EnableUser`, `EnableUser` | Access suspension/reactivation workflows | Implemented |
| Enrollment/credential management | `_SetEnrollData*`, `_GetEnrollData*`, `SetEnrollDataFP/PWD/CARD`, `GetEnrollDataFP/PWD/CARD`, `DeleteEnrollData*` | Finger/card/password lifecycle, credential cleanup | Partial (delete + XML extensibility available) |
| Attendance log retrieval | `_ReadAllGLogData*`, `_GetAllGLogData*`, `_ReadGLogWithPos*`, `_GetGeneralLogData*`, `GetGLogPosInfo` | Historical attendance pull, cursor-based sync, backfill | Not yet exposed as dedicated REST in current app |
| Super/admin logs | `_ReadAllSLogData`, `_GetAllSLogData`, `_ReadSuperLogData`, `_GetSuperLogData` | Audit trails for admin/config actions | Not yet exposed |
| Event capture | `_StartEventCapture`, `_StopEventCapture` | Near-real-time event stream daemon | Not yet implemented in Python path |
| Door + access control | `_GetDoorStatus`, `_SetDoorStatus`, `OpenDoor`, `SetDoorParam`, `ReadAccessSetting`, `WriteAccessSetting`, `SetUnlockgroup` | Door remote control, access schedule automation | Not yet exposed as dedicated REST |
| Network/config | `Get/SetCommParam`, `Get/SetCommSetting`, `Get/SetDnsSettings`, `Get/SetWiFiSetting`, `Get/SetEthernetSetting`, `Get/SetLogServerSetting` | Remote network config management UI, fleet configuration | Not yet exposed; possible via XML execute |
| Timezone/schedule policy | `Get/SetTimezone`, `Get/SetUserPeriod`, `Get/SetUserHolidays`, `Get/SetUserBalanceTime`, `Get/SetTrStrings` | Shift policy push, holiday roster sync, schedule governance | Not yet exposed; possible via XML execute |
| Media/QR | `Get/SetUserPhotoData`, `EnrollFaceByPhoto`, `GetUserStringForQrCode`, `VerifyDeviceQrCode`, `ClearPhoto` | Face/photo sync, QR identity workflows | Not yet exposed; possible via XML execute |
| Maintenance actions | `_EmptyGeneralLogData`, `_EmptySuperLogData`, `_EmptyEnrollData`, `_ClearKeeperData`, `_PowerOffDevice` | Cleanup jobs, controlled reset flows | Not yet exposed |
| XML extensibility bus | `_GeneralOperationXML` + `_XML_Add*`, `_XML_Parse*` + request name catalog | Fast capability rollout without recompiling low-level wrapper | Implemented (`/api/machine/xml/execute`) |

## 6. Important Architecture Truths

1. The SDK is a platform, not one fixed API contract.
2. Supported features vary by machine model and firmware.
3. A request present in SDK docs can still fail on a given device.
4. Therefore, real capability is discovered by probe and validation, not assumptions.

## 7. How to Discover Exactly What Your Device Supports

Use this repeatable method.

### Step 1: Preflight

1. Verify TCP connectivity to machine IP:port.
2. Verify DLL path exists (`SBXPCDLL64.dll`).
3. Run `POST /api/machine/test-connection` successfully.

### Step 2: Build request probe list

Start with high-value XML requests from `docs/sdk_inventory/request_names.txt`, for example:

1. `GetDeviceDetails`
2. `GetCommSetting`
3. `GetUserInfo`
4. `GetGLogPosInfo`
5. `GetDoorStatusMulti`
6. `GetTimezone`
7. `GetWiFiSetting`

### Step 3: Probe via existing XML execute endpoint

Use `POST /api/machine/xml/execute` with `request_name` and parse fields.

Example payload:

```json
{
  "machine_ip": "192.168.29.224",
  "machine_port": 5005,
  "machine_password": 0,
  "machine_number": 1,
  "sdk_dll_path": "C:/Users/DELL/HR Module/sdk_extracted/20211204-SBXPC-1/bin/SBXPCDLL64.dll",
  "request_name": "GetDeviceDetails",
  "msg_type": "request",
  "include_machine_id": true,
  "fields": [],
  "parse_fields": [
    {"tag": "ErrorCode", "value_type": "int"},
    {"tag": "ErrStr", "value_type": "string"},
    {"tag": "MachineType", "value_type": "string"},
    {"tag": "DeviceID", "value_type": "string"}
  ],
  "return_response_xml": true
}
```

### Step 4: Classify each capability

For each request, classify as:

1. `SUPPORTED`: success and meaningful fields.
2. `UNSUPPORTED`: explicit error or empty unsupported response.
3. `RESTRICTED`: requires privilege/model/config.
4. `UNSTABLE`: intermittent behavior or timeout.

### Step 5: Build your device capability matrix

Create a per-device table:

1. Request name
2. Required input tags
3. Parsed output tags
4. Status (`SUPPORTED/UNSUPPORTED/RESTRICTED/UNSTABLE`)
5. Last test timestamp
6. Notes/error codes

This becomes your source of truth for product planning.

## 8. High-Value Features You Can Build Next

If you want maximum value with minimum SDK risk, build in this order:

1. Attendance log pull API (`ReadAllGLogData` + cursor/position endpoints).
2. Device info API (`GetDeviceDetails`, network/settings read endpoints).
3. Time sync API (`SetDeviceTime` job + drift monitor).
4. Door status and control API (read status first, then controlled actions).
5. Policy sync API (timezone/period/holiday/group).

## 9. Risks and Guardrails

1. Model variance: same request may work on one model and fail on another.
2. Privilege requirements: some operations need admin-level device rights.
3. Single-client contention: vendor tools and your API competing can cause failures.
4. Safety: destructive functions (`Empty*`, deletes) should be admin-gated and audited.
5. Rollout strategy: always test in dry-run/read-only mode before write operations.

## 10. Quick Summary

1. You already have a strong base: direct machine APIs and raw XML execution.
2. The SDK can support a much larger product surface than currently exposed.
3. The right approach is capability probing + matrixing per device model.
4. This file plus `request_names.txt` gives you the roadmap for controlled expansion.

