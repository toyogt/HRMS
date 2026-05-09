# Machine Setup And Testing Guide (Remote PC + Local App)

This guide explains how to configure the biometric machine and test all available app-to-machine API functions step by step.

## 1. Target Architecture

Use this model:

1. HRMS middleware app runs on a Windows PC (called "remote PC").
2. Biometric machine is on the same LAN as that PC.
3. All machine API tests are executed from that same PC.

Do not run machine connectivity tests from a different network.

## 2. Machine Setup (Must Be Done First)

On the machine network/communication menu:

1. Set `DHCP = OFF`.
2. Set static `IP Address` (example: `192.168.29.224`).
3. Set `Subnet Mask = 255.255.255.0`.
4. Set `Gateway = 192.168.29.1`.
5. Set communication `Port = 5005`.
6. Note communication password/key:
   - if empty/disabled, use `0` in API.
   - if configured, use exact numeric value in API.
7. Save settings and reboot machine.

Important:

1. Ensure no vendor desktop utility is already connected to machine.
2. Keep only one active client connection when testing API writes.

## 3. App Setup On Remote PC

Assume project path: `C:\Users\Kapil\HRMS`

In `configs/dev.yaml`, confirm:

1. `ingress_port: 8080` (or keep `8000`, but use same value everywhere).
2. `machine_sync_ip: "192.168.29.224"`.
3. `machine_sync_port: 5005`.
4. `machine_sync_password: 0` (or actual machine password).
5. `machine_sdk_dll_path: "C:/Users/Kapil/HRMS/sdk_extracted/20211204-SBXPC-1/bin/SBXPCDLL64.dll"`.

## 4. Start Middleware

From PowerShell:

```powershell
cd "C:\Users\Kapil\HRMS"
.\INSTALL_ONE_CLICK.cmd
```

If already installed, start manually:

```powershell
.\.venv\Scripts\python.exe scripts\run_gateway.py --config configs/dev.yaml
```

In a second PowerShell window:

```powershell
curl.exe http://127.0.0.1:8080/health
start http://127.0.0.1:8080/docs
```

If using port `8000`, replace `8080` with `8000` in all commands.

## 5. Preflight Network Checks (Mandatory)

Run on remote PC:

```powershell
arp -d *
ping 192.168.29.224
powershell -Command "Test-NetConnection -ComputerName 192.168.29.224 -Port 5005"
```

Expected:

1. ping replies from machine IP (or ping blocked but TCP still true).
2. `TcpTestSucceeded : True` is required for API machine operations.

## 6. Preflight App Checks

```powershell
cd "C:\Users\Kapil\HRMS"
Test-Path "C:\Users\Kapil\HRMS\sdk_extracted\20211204-SBXPC-1\bin\SBXPCDLL64.dll"
curl.exe http://127.0.0.1:8080/health
```

Expected:

1. DLL path exists (`True`).
2. health returns JSON.

## 7. Reusable Test Variables

```powershell
$BASE="http://127.0.0.1:8080"
$MW="dev-middleware-key"
$MIP="192.168.29.224"
$MPORT=5005
$MPASS=0
$MNO=1
$DLL="C:\Users\Kapil\HRMS\sdk_extracted\20211204-SBXPC-1\bin\SBXPCDLL64.dll"
$CODE="KV230A"
$UID=230
```

## 8. Test Method A - Machine Handshake

```powershell
$connBody=@{
  machine_ip=$MIP
  machine_port=$MPORT
  machine_password=$MPASS
  machine_number=$MNO
  sdk_dll_path=$DLL
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri "$BASE/api/machine/test-connection" -ContentType "application/json" -Body $connBody
```

Expected:

1. `connected = true`
2. machine details and `device_time` in response.

## 9. Test Method B - Create Employee In App + Push To Machine (One Call)

```powershell
$createBody=@{
  employee_code=$CODE
  employee_name="Kunal Verma-Test"
  card_no="230"
  phone_no="9876543210"
  department="OPERATIONS"
  designation="SUPERVISOR"
  machine=@{
    sync_to_machine=$true
    machine_ip=$MIP
    machine_port=$MPORT
    machine_password=$MPASS
    machine_number=$MNO
    sdk_dll_path=$DLL
    user_id=$UID
    user_name="Kunal Verma-Test"
    card_no="230"
  }
} | ConvertTo-Json -Depth 10 -Compress

Invoke-RestMethod -Method Post -Uri "$BASE/api/v1/employees" -Headers @{"x-api-key"=$MW} -ContentType "application/json" -Body $createBody
```

Expected:

1. employee saved in app DB.
2. `machine_sync.requested = true`.
3. `machine_sync.success = true`.

## 10. Test Method C - Read Employee From Machine

```powershell
$readBody=@{
  machine_ip=$MIP
  machine_port=$MPORT
  machine_password=$MPASS
  machine_number=$MNO
  sdk_dll_path=$DLL
  user_id=$UID
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri "$BASE/api/machine/employees/$CODE/read" -ContentType "application/json" -Body $readBody
```

Expected:

1. `exists_on_machine = true` after create/update.
2. response includes `machine_user_record` and optional `user_name`.

## 11. Test Method D - Edit Employee In App, Then Push Edit To Machine

```powershell
$patchBody=@{
  employee_name="Kunal Verma-Edited"
  phone_no="9999999999"
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Patch -Uri "$BASE/api/v1/employees/$CODE" -Headers @{"x-api-key"=$MW} -ContentType "application/json" -Body $patchBody

$pushBody=@{
  machine_ip=$MIP
  machine_port=$MPORT
  machine_password=$MPASS
  machine_number=$MNO
  sdk_dll_path=$DLL
  user_id=$UID
  user_name="Kunal Verma-Edited"
  card_no="230"
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Put -Uri "$BASE/api/machine/employees/$CODE" -ContentType "application/json" -Body $pushBody
```

Expected:

1. app DB reflects new name/phone.
2. machine write returns success with same `user_id`.

## 12. Test Method E - Disable And Enable Employee On Machine

```powershell
$toggleBody=@{
  machine_ip=$MIP
  machine_port=$MPORT
  machine_password=$MPASS
  machine_number=$MNO
  sdk_dll_path=$DLL
  user_id=$UID
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri "$BASE/api/machine/employees/$CODE/disable" -ContentType "application/json" -Body $toggleBody
Invoke-RestMethod -Method Post -Uri "$BASE/api/machine/employees/$CODE/enable"  -ContentType "application/json" -Body $toggleBody
```

Expected:

1. first call returns `enabled = false`.
2. second call returns `enabled = true`.

## 13. Test Method F - Delete Employee On Machine

```powershell
$deleteBody=@{
  machine_ip=$MIP
  machine_port=$MPORT
  machine_password=$MPASS
  machine_number=$MNO
  sdk_dll_path=$DLL
  user_id=$UID
  e_machine_number=1
  backup_number=0
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Delete -Uri "$BASE/api/machine/employees/$CODE" -ContentType "application/json" -Body $deleteBody
```

Expected:

1. response contains `deleted = true`.

Verify delete:

```powershell
Invoke-RestMethod -Method Post -Uri "$BASE/api/machine/employees/$CODE/read" -ContentType "application/json" -Body $readBody
```

Expected:

1. `exists_on_machine = false`.

## 14. Bulk Sync Test (Optional)

Preview only:

```powershell
$syncPreview=@{
  machine_ip=$MIP
  machine_port=$MPORT
  machine_password=$MPASS
  machine_number=$MNO
  sdk_dll_path=$DLL
  dry_run=$true
  limit=50
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri "$BASE/api/machine/employees/sync" -ContentType "application/json" -Body $syncPreview
```

Actual sync:

```powershell
$syncRun=@{
  machine_ip=$MIP
  machine_port=$MPORT
  machine_password=$MPASS
  machine_number=$MNO
  sdk_dll_path=$DLL
  dry_run=$false
  limit=50
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri "$BASE/api/machine/employees/sync" -ContentType "application/json" -Body $syncRun
```

## 15. Validation Matrix

Mark each as PASS/FAIL:

1. API health reachable.
2. DLL found on disk.
3. TCP connectivity to machine port 5005.
4. machine test-connection success.
5. create + machine push success.
6. read from machine success.
7. update push success.
8. disable/enable success.
9. delete success.
10. read-after-delete shows non-existence.

## 16. Common Failure Patterns And Fixes

1. `SDK DLL not found`:
   - copy `sdk_extracted` into project.
   - fix `machine_sdk_dll_path`.

2. `ConnectTcpip failed`:
   - wrong machine password/port.
   - machine unreachable from PC.
   - another software already connected.

3. `employee_code cannot map to numeric machine user_id`:
   - provide explicit `user_id` when code is alphanumeric.

4. `employee_code not found in employee_master`:
   - create employee in app DB first or use one-call create endpoint.

5. `127.0.0.1 refused to connect`:
   - gateway not running or wrong port.
   - run gateway foreground and check logs.

## 17. Recommended Daily Test Routine

1. Run connectivity check (`Test-NetConnection`).
2. Run `test-connection` API.
3. Run one employee CRUD cycle (`create -> read -> update -> read -> disable/enable -> delete -> read`).
4. Archive request/response logs for traceability.
