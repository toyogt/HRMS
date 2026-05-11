from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from attendance_relay.machine_sdk import MachineSdkError, SBXPCClient
from attendance_relay.machine_sync import (
    choose_card_number,
    choose_machine_user_id,
    choose_user_name,
    list_employee_master_rows,
    parse_unsigned_integer,
    sync_rows_to_machine,
)
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings


class MachineConnectionRequest(BaseModel):
    device_id: str | None = None
    machine_ip: str | None = None
    machine_port: int | None = Field(default=None, ge=1, le=65535)
    machine_password: int | None = None
    machine_number: int | None = Field(default=None, ge=1)
    sdk_dll_path: str | None = None


class MachineSyncRequest(MachineConnectionRequest):
    employee_code: str | None = None
    limit: int = Field(default=2000, ge=1, le=50000)
    dry_run: bool = False
    timezone1: int | None = None
    timezone2: int | None = None
    group_no: int | None = None


class MachineEmployeeUpdateRequest(MachineConnectionRequest):
    user_id: int | None = Field(default=None, ge=0, le=2_147_483_647)
    user_name: str | None = None
    card_no: str | None = None
    timezone1: int | None = None
    timezone2: int | None = None
    group_no: int | None = None
    enable: bool | None = None
    e_machine_number: int = Field(default=1, ge=1)
    backup_number: int = Field(default=0, ge=0)


class MachineEmployeeToggleRequest(MachineConnectionRequest):
    user_id: int | None = Field(default=None, ge=0, le=2_147_483_647)
    e_machine_number: int = Field(default=1, ge=1)
    backup_number: int = Field(default=0, ge=0)
    all_slots: bool = False


class MachineEmployeeReadRequest(MachineConnectionRequest):
    user_id: int | None = Field(default=None, ge=0, le=2_147_483_647)
    include_user_name: bool = True


class MachineEmployeeListRequest(MachineConnectionRequest):
    include_user_names: bool = False


class MachineEmployeeDeleteRequest(MachineConnectionRequest):
    user_id: int | None = Field(default=None, ge=0, le=2_147_483_647)
    e_machine_number: int = Field(default=1, ge=1)
    backup_number: int = Field(default=0, ge=0)
    all_slots: bool = False


class MachineDeviceDetailsRequest(MachineConnectionRequest):
    include_user_count: bool = False


class MachineTimeReadRequest(MachineConnectionRequest):
    pass


class MachineTimeSetRequest(MachineConnectionRequest):
    device_time: str | None = None


class MachineGeneralLogsReadRequest(MachineConnectionRequest):
    limit: int = Field(default=200, ge=1, le=50000)


class MachineCapabilitiesProbeRequest(MachineConnectionRequest):
    include_log_read_test: bool = False
    log_read_limit: int = Field(default=1, ge=1, le=1000)


class MachineXmlField(BaseModel):
    tag: str
    value: Any = None
    value_type: str = "auto"  # auto|string|int|long|bool


class MachineXmlBinaryField(BaseModel):
    tag: str
    data_base64: str


class MachineXmlParseField(BaseModel):
    tag: str
    value_type: str = "string"  # string|int|long|bool


class MachineXmlBinaryParseField(BaseModel):
    tag: str
    length: int = Field(default=8192, ge=1, le=1024 * 1024)


class MachineXmlExecuteRequest(MachineConnectionRequest):
    request_name: str
    msg_type: str = "request"
    include_machine_id: bool = True
    fields: list[MachineXmlField] = Field(default_factory=list)
    binary_fields: list[MachineXmlBinaryField] = Field(default_factory=list)
    parse_fields: list[MachineXmlParseField] = Field(default_factory=list)
    parse_binary_fields: list[MachineXmlBinaryParseField] = Field(default_factory=list)
    return_request_xml: bool = False
    return_response_xml: bool = True


@dataclass(slots=True)
class ResolvedMachineConnection:
    device_id: str | None
    source: str
    machine_ip: str
    machine_port: int
    machine_password: int
    machine_number: int
    sdk_dll_path: str


def _parse_optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def resolve_machine_connection(
    settings: Settings,
    request: MachineConnectionRequest | None = None,
    *,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> ResolvedMachineConnection:
    device_id = str((request.device_id if request else "") or "").strip() or None
    device_row: dict[str, Any] | None = None
    if device_id:
        if device_resolver is None:
            raise ValueError("device_id was provided but device resolver is not configured.")
        try:
            device_row = device_resolver(device_id)
        except ValueError as exc:
            raise ValueError(f"device_id not found: {device_id}") from exc
        if not _to_bool(device_row.get("is_active", True)):
            raise ValueError(f"device_id is inactive: {device_id}")

    source = "settings"
    explicit_ip = str((request.machine_ip if request else "") or "").strip()
    device_ip = str((device_row or {}).get("ip") or "").strip()
    if explicit_ip:
        source = "request"
    elif device_row is not None:
        source = "device"

    machine_ip = (explicit_ip or device_ip or settings.machine_sync_ip).strip()
    if not machine_ip:
        raise ValueError("machine_ip is required. Set config machine_sync_ip or pass machine_ip.")

    explicit_port = request.machine_port if request and request.machine_port is not None else None
    device_port = _parse_optional_int((device_row or {}).get("port") if device_row else None, "device port")

    explicit_password = request.machine_password if request and request.machine_password is not None else None
    device_password = _parse_optional_int(
        (device_row or {}).get("machine_password") if device_row else None,
        "device machine_password",
    )
    device_machine_number = _parse_optional_int(
        (device_row or {}).get("machine_number") if device_row else None,
        "device machine_number",
    )

    return ResolvedMachineConnection(
        device_id=device_id,
        source=source,
        machine_ip=machine_ip,
        machine_port=(explicit_port if explicit_port is not None else (device_port if device_port is not None else settings.machine_sync_port)),
        machine_password=(
            explicit_password
            if explicit_password is not None
            else (device_password if device_password is not None else settings.machine_sync_password)
        ),
        machine_number=(
            request.machine_number
            if request and request.machine_number is not None
            else (device_machine_number if device_machine_number is not None else settings.machine_sync_machine_number)
        ),
        sdk_dll_path=(request.sdk_dll_path if request and request.sdk_dll_path else settings.machine_sdk_dll_path),
    )


def build_machine_sync_preview(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    request: MachineSyncRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)
    rows = list_employee_master_rows(
        repo.engine,
        limit=request.limit,
        employee_code=(request.employee_code or None),
    )
    preview: list[dict[str, Any]] = []
    for row in rows:
        user_id = choose_machine_user_id(row)
        preview.append(
            {
                "employee_code": str(row.get("employee_code") or "").strip(),
                "employee_name": str(row.get("employee_name") or "").strip(),
                "resolved_user_id": user_id,
                "resolved_card_no": (
                    choose_card_number(row, fallback_user_id=(user_id or 0)) if user_id is not None else None
                ),
                "resolved_user_name": choose_user_name(row),
            }
        )
    return {
        "dry_run": True,
        "rows": len(rows),
        "machine": {
            "device_id": resolved.device_id,
            "source": resolved.source,
            "machine_ip": resolved.machine_ip,
            "machine_port": resolved.machine_port,
            "machine_number": resolved.machine_number,
            "sdk_dll_path": resolved.sdk_dll_path,
        },
        "preview": preview,
    }


def run_machine_sync_from_api(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    request: MachineSyncRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)
    rows = list_employee_master_rows(
        repo.engine,
        limit=request.limit,
        employee_code=(request.employee_code or None),
    )
    summary = sync_rows_to_machine(
        rows=rows,
        machine_ip=resolved.machine_ip,
        machine_port=resolved.machine_port,
        machine_password=resolved.machine_password,
        machine_number=resolved.machine_number,
        timezone1=(request.timezone1 if request.timezone1 is not None else settings.machine_sync_timezone1),
        timezone2=(request.timezone2 if request.timezone2 is not None else settings.machine_sync_timezone2),
        group_no=(request.group_no if request.group_no is not None else settings.machine_sync_group_no),
        sdk_dll_path=resolved.sdk_dll_path,
    )
    return {
        "dry_run": False,
        "machine": {
            "device_id": resolved.device_id,
            "source": resolved.source,
            "machine_ip": resolved.machine_ip,
            "machine_port": resolved.machine_port,
            "machine_number": resolved.machine_number,
            "sdk_dll_path": resolved.sdk_dll_path,
        },
        "summary": {
            "scanned": summary.scanned,
            "synced": summary.synced,
            "skipped": summary.skipped,
            "failed": summary.failed,
        },
    }


def check_machine_connection(
    *,
    settings: Settings,
    request: MachineConnectionRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)
    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        device_time = client.get_device_time(resolved.machine_number)
    finally:
        client.disconnect(resolved.machine_number)
    return {
        "connected": True,
        "device_id": resolved.device_id,
        "source": resolved.source,
        "machine_ip": resolved.machine_ip,
        "machine_port": resolved.machine_port,
        "machine_number": resolved.machine_number,
        "device_time": device_time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _machine_context_payload(resolved: ResolvedMachineConnection) -> dict[str, Any]:
    return {
        "device_id": resolved.device_id,
        "source": resolved.source,
        "machine_ip": resolved.machine_ip,
        "machine_port": resolved.machine_port,
        "machine_number": resolved.machine_number,
        "sdk_dll_path": resolved.sdk_dll_path,
    }


def _parse_device_time_input(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("device_time is required")
    candidates = [raw, raw.replace("T", " ")]
    parsed: datetime | None = None
    for text in candidates:
        try:
            parsed = datetime.fromisoformat(text)
            break
        except ValueError:
            parsed = None
    if parsed is None:
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError("device_time must be ISO-8601 or 'YYYY-MM-DD HH:MM:SS'") from exc
    return parsed.replace(microsecond=0, tzinfo=None)


def get_machine_device_details(
    *,
    settings: Settings,
    request: MachineDeviceDetailsRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)
    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        device_time = client.get_device_time(resolved.machine_number)
        capabilities = client.get_bound_capabilities()

        serial_number: str | None = None
        serial_error: str | None = None
        try:
            serial_number = client.get_serial_number(resolved.machine_number)
        except MachineSdkError as exc:
            serial_error = str(exc)

        device_model: dict[str, int] | None = None
        device_model_error: str | None = None
        try:
            device_model = client.get_device_model(resolved.machine_number)
        except MachineSdkError as exc:
            device_model_error = str(exc)

        backup_number: int | None = None
        backup_number_error: str | None = None
        try:
            backup_number = client.get_backup_number(resolved.machine_number)
        except MachineSdkError as exc:
            backup_number_error = str(exc)

        internal_fw_version: int | None = None
        internal_fw_version_error: str | None = None
        try:
            internal_fw_version = client.get_internal_fw_version(resolved.machine_number)
        except MachineSdkError as exc:
            internal_fw_version_error = str(exc)

        user_count: int | None = None
        user_count_error: str | None = None
        if request.include_user_count:
            try:
                user_count = len(client.list_all_user_ids(resolved.machine_number))
            except MachineSdkError as exc:
                user_count_error = str(exc)
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "machine": _machine_context_payload(resolved),
        "device_time": device_time.strftime("%Y-%m-%d %H:%M:%S"),
        "serial_number": serial_number,
        "device_model": device_model,
        "backup_number": backup_number,
        "internal_fw_version": internal_fw_version,
        "user_count": user_count,
        "capabilities": capabilities,
        "warnings": {
            "serial_number": serial_error,
            "device_model": device_model_error,
            "backup_number": backup_number_error,
            "internal_fw_version": internal_fw_version_error,
            "user_count": user_count_error,
        },
    }


def read_machine_time(
    *,
    settings: Settings,
    request: MachineTimeReadRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)
    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        device_time = client.get_device_time(resolved.machine_number)
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "machine": _machine_context_payload(resolved),
        "device_time": device_time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def set_machine_time(
    *,
    settings: Settings,
    request: MachineTimeSetRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)
    requested_time = (
        _parse_device_time_input(request.device_time)
        if str(request.device_time or "").strip()
        else datetime.now().replace(microsecond=0)
    )
    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        client.set_device_time(resolved.machine_number, requested_time)
        device_time_after = client.get_device_time(resolved.machine_number)
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "machine": _machine_context_payload(resolved),
        "requested_device_time": requested_time.strftime("%Y-%m-%d %H:%M:%S"),
        "device_time_after": device_time_after.strftime("%Y-%m-%d %H:%M:%S"),
    }


def read_machine_general_logs(
    *,
    settings: Settings,
    request: MachineGeneralLogsReadRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)
    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        rows = client.list_general_logs(resolved.machine_number, limit=request.limit)
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "machine": _machine_context_payload(resolved),
        "limit": request.limit,
        "loaded": len(rows),
        "rows": rows,
    }


def probe_machine_capabilities(
    *,
    settings: Settings,
    request: MachineCapabilitiesProbeRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)
    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        sdk_capabilities = client.get_bound_capabilities()
        probes: dict[str, Any] = {
            "connect": {"success": True},
        }

        try:
            device_time = client.get_device_time(resolved.machine_number)
            probes["device_time_read"] = {
                "success": True,
                "value": device_time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        except MachineSdkError as exc:
            probes["device_time_read"] = {"success": False, "error": str(exc)}

        try:
            serial_number = client.get_serial_number(resolved.machine_number)
            probes["serial_number_read"] = {"success": True, "value": serial_number}
        except MachineSdkError as exc:
            probes["serial_number_read"] = {"success": False, "error": str(exc)}

        try:
            model = client.get_device_model(resolved.machine_number)
            probes["device_model_read"] = {"success": True, "value": model}
        except MachineSdkError as exc:
            probes["device_model_read"] = {"success": False, "error": str(exc)}

        if request.include_log_read_test:
            try:
                sample_logs = client.list_general_logs(resolved.machine_number, limit=request.log_read_limit)
                probes["general_logs_read"] = {
                    "success": True,
                    "loaded": len(sample_logs),
                    "sample": sample_logs[: min(5, len(sample_logs))],
                }
            except MachineSdkError as exc:
                probes["general_logs_read"] = {"success": False, "error": str(exc)}
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "machine": _machine_context_payload(resolved),
        "sdk_capabilities": sdk_capabilities,
        "probes": probes,
    }


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _apply_xml_field(client: SBXPCClient, xml: str, field: MachineXmlField) -> str:
    tag = str(field.tag or "").strip()
    if not tag:
        raise ValueError("field.tag is required")
    value_type = str(field.value_type or "auto").strip().lower() or "auto"
    value = field.value

    if value_type in {"auto", "bool"} and isinstance(value, bool):
        return client.xml_add_boolean(xml, tag, value)
    if value_type in {"int", "long"}:
        return client.xml_add_long(xml, tag, int(value or 0))
    if value_type == "bool":
        return client.xml_add_boolean(xml, tag, _to_bool(value))
    if value_type == "auto":
        if isinstance(value, int):
            return client.xml_add_long(xml, tag, value)
        if isinstance(value, float) and value.is_integer():
            return client.xml_add_long(xml, tag, int(value))
    # Fallback: encode as string to keep passthrough permissive.
    return client.xml_add_string(xml, tag, "" if value is None else str(value))


def run_machine_xml_execute(
    *,
    settings: Settings,
    request: MachineXmlExecuteRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)
    request_name = str(request.request_name or "").strip()
    if not request_name:
        raise ValueError("request_name is required")

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        request_xml = ""
        request_xml = client.xml_add_string(request_xml, "REQUEST", request_name)
        request_xml = client.xml_add_string(request_xml, "MSGTYPE", str(request.msg_type or "request"))
        if request.include_machine_id:
            request_xml = client.xml_add_long(request_xml, "MachineID", resolved.machine_number)

        for field in request.fields:
            request_xml = _apply_xml_field(client, request_xml, field)

        for field in request.binary_fields:
            tag = str(field.tag or "").strip()
            if not tag:
                raise ValueError("binary_fields.tag is required")
            try:
                payload = base64.b64decode((field.data_base64 or "").encode("ascii"), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError(f"invalid base64 for binary field tag={tag}") from exc
            request_xml = client.xml_add_binary_byte(request_xml, tag, payload)

        response_xml = client.general_operation_xml(resolved.machine_number, request_xml)

        parsed: dict[str, Any] = {}
        for field in request.parse_fields:
            tag = str(field.tag or "").strip()
            if not tag:
                continue
            value_type = str(field.value_type or "string").strip().lower() or "string"
            try:
                if value_type == "int":
                    parsed[tag] = client.xml_parse_int(response_xml, tag)
                elif value_type == "long":
                    parsed[tag] = client.xml_parse_long(response_xml, tag)
                elif value_type == "bool":
                    parsed[tag] = client.xml_parse_boolean(response_xml, tag)
                else:
                    parsed[tag] = client.xml_parse_string(response_xml, tag)
            except (MachineSdkError, OSError):
                parsed[tag] = None

        parsed_binary: dict[str, str | None] = {}
        for field in request.parse_binary_fields:
            tag = str(field.tag or "").strip()
            if not tag:
                continue
            try:
                parsed_binary[tag] = client.xml_parse_binary_byte_base64(response_xml, tag, int(field.length))
            except (MachineSdkError, OSError):
                parsed_binary[tag] = None
    finally:
        client.disconnect(resolved.machine_number)

    result: dict[str, Any] = {
        "executed": True,
        "machine": {
            "device_id": resolved.device_id,
            "source": resolved.source,
            "machine_ip": resolved.machine_ip,
            "machine_port": resolved.machine_port,
            "machine_number": resolved.machine_number,
            "sdk_dll_path": resolved.sdk_dll_path,
        },
        "request_name": request_name,
        "parsed": parsed,
        "parsed_binary": parsed_binary,
    }
    if request.return_request_xml:
        result["request_xml"] = request_xml
    if request.return_response_xml:
        result["response_xml"] = response_xml
    return result


def _resolve_employee_row_or_fail(repo: AttendanceRepository, employee_code: str) -> dict[str, Any]:
    row = repo.find_employee_master(employee_code)
    if not row:
        raise ValueError(f"employee_code not found in employee_master: {employee_code}")
    return row


def _resolve_employee_row_optional(repo: AttendanceRepository, employee_code: str) -> dict[str, Any] | None:
    return repo.find_employee_master(employee_code)


def _resolve_user_id(row: dict[str, Any], explicit_user_id: int | None) -> int:
    if explicit_user_id is not None:
        return explicit_user_id
    user_id = choose_machine_user_id(row)
    if user_id is None:
        code = str(row.get("employee_code") or "").strip()
        raise ValueError(f"employee_code cannot map to numeric machine user_id: {code}")
    return user_id


def _resolve_user_id_for_machine(
    repo: AttendanceRepository,
    employee_code: str,
    explicit_user_id: int | None,
) -> tuple[int, dict[str, Any] | None]:
    row = _resolve_employee_row_optional(repo, employee_code)
    if explicit_user_id is not None:
        return explicit_user_id, row
    if row is None:
        raise ValueError(
            "employee_code not found in employee_master and user_id not provided. "
            "Pass user_id for direct machine operation."
        )
    return _resolve_user_id(row, explicit_user_id), row


def _resolve_card_number(row: dict[str, Any], explicit_card_no: str | None, fallback_user_id: int) -> int:
    if explicit_card_no is not None and explicit_card_no.strip():
        parsed = parse_unsigned_integer(explicit_card_no.strip(), (1 << 64) - 1)
        if parsed is None:
            raise ValueError("card_no must be a positive integer up to uint64.")
        return parsed
    return choose_card_number(row, fallback_user_id=fallback_user_id)


def _write_employee_to_machine(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    employee_code: str,
    request: MachineEmployeeUpdateRequest,
    create_if_missing: bool,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    row = _resolve_employee_row_or_fail(repo, employee_code)
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)
    user_id = _resolve_user_id(row, request.user_id)
    user_name = (request.user_name or "").strip() or choose_user_name(row)
    card_no = _resolve_card_number(row, request.card_no, fallback_user_id=user_id)
    timezone1 = request.timezone1 if request.timezone1 is not None else settings.machine_sync_timezone1
    timezone2 = request.timezone2 if request.timezone2 is not None else settings.machine_sync_timezone2
    group_no = request.group_no if request.group_no is not None else settings.machine_sync_group_no

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        existing_users = client.list_all_user_ids(resolved.machine_number)
        existed_before = any(int(entry.get("user_id", -1)) == user_id for entry in existing_users)
        client.enable_device(resolved.machine_number, False)
        try:
            created_on_machine = False
            if create_if_missing and not existed_before:
                enroll_backup_number = 11 if card_no else request.backup_number
                enroll_credential_value = card_no if enroll_backup_number == 11 else 0
                client.set_enroll_data1(
                    resolved.machine_number,
                    user_id,
                    backup_number=enroll_backup_number,
                    machine_privilege=0,
                    credential_value=enroll_credential_value,
                )
                created_on_machine = True
            client.set_user_name(resolved.machine_number, user_id, user_name)
            user_info_error: str | None = None
            try:
                client.set_user_info(
                    machine_number=resolved.machine_number,
                    user_id=user_id,
                    timezone1=timezone1,
                    timezone2=timezone2,
                    group_no=group_no,
                    card_no=card_no,
                )
            except MachineSdkError as exc:
                user_info_error = str(exc)
            if request.enable is not None:
                client.enable_user(
                    resolved.machine_number,
                    user_id,
                    e_machine_number=request.e_machine_number,
                    backup_number=request.backup_number,
                    enabled=request.enable,
                )
        finally:
            client.enable_device(resolved.machine_number, True)
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "employee_code": str(row.get("employee_code") or employee_code),
        "device_id": resolved.device_id,
        "source": resolved.source,
        "machine_ip": resolved.machine_ip,
        "machine_port": resolved.machine_port,
        "machine_number": resolved.machine_number,
        "user_id": user_id,
        "user_name": user_name,
        "card_no": card_no,
        "timezone1": timezone1,
        "timezone2": timezone2,
        "group_no": group_no,
        "enabled": request.enable,
        "existed_before": existed_before,
        "created_on_machine": created_on_machine,
        "user_info_applied": user_info_error is None,
        "user_info_error": user_info_error,
    }


def create_employee_on_machine(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    employee_code: str,
    request: MachineEmployeeUpdateRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _write_employee_to_machine(
        repo=repo,
        settings=settings,
        employee_code=employee_code,
        request=request,
        create_if_missing=True,
        device_resolver=device_resolver,
    )


def update_employee_on_machine(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    employee_code: str,
    request: MachineEmployeeUpdateRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _write_employee_to_machine(
        repo=repo,
        settings=settings,
        employee_code=employee_code,
        request=request,
        create_if_missing=False,
        device_resolver=device_resolver,
    )


def toggle_employee_on_machine(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    employee_code: str,
    enabled: bool,
    request: MachineEmployeeToggleRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    user_id, row = _resolve_user_id_for_machine(repo, employee_code, request.user_id)
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        users = client.list_all_user_ids(resolved.machine_number)
        matching = [entry for entry in users if int(entry.get("user_id", -1)) == user_id]
        target_slots: list[tuple[int, int]] = []
        if request.all_slots:
            target_slots = sorted(
                {
                    (
                        int(entry.get("e_machine_number", request.e_machine_number)),
                        int(entry.get("backup_number", request.backup_number)),
                    )
                    for entry in matching
                }
            )
        else:
            target_slots = [(request.e_machine_number, request.backup_number)]

        client.enable_device(resolved.machine_number, False)
        try:
            for e_machine_number, backup_number in target_slots:
                client.enable_user(
                    resolved.machine_number,
                    user_id,
                    e_machine_number=e_machine_number,
                    backup_number=backup_number,
                    enabled=enabled,
                )
        finally:
            client.enable_device(resolved.machine_number, True)

        users_after = client.list_all_user_ids(resolved.machine_number)
        matching_after = [entry for entry in users_after if int(entry.get("user_id", -1)) == user_id]
        effective_enabled = any(bool(entry.get("enabled")) for entry in matching_after)
    finally:
        client.disconnect(resolved.machine_number)

    operation_applied = effective_enabled == enabled if matching_after else None
    warning: str | None = None
    if operation_applied is False:
        warning = (
            "Requested enable/disable call returned success, but post-read state from GetAllUserID "
            "did not change. On some firmware/models this operation may be a no-op or state may not be "
            "authoritatively exposed via GetAllUserID."
        )

    return {
        "employee_code": str((row or {}).get("employee_code") or employee_code),
        "device_id": resolved.device_id,
        "source": resolved.source,
        "machine_ip": resolved.machine_ip,
        "machine_port": resolved.machine_port,
        "machine_number": resolved.machine_number,
        "user_id": user_id,
        "enabled": enabled,
        "e_machine_number": request.e_machine_number,
        "backup_number": request.backup_number,
        "all_slots": request.all_slots,
        "requested_slot": {
            "e_machine_number": request.e_machine_number,
            "backup_number": request.backup_number,
        },
        "affected_slots": [{"e_machine_number": e, "backup_number": b} for e, b in target_slots],
        "state_source": "GetAllUserID",
        "operation_applied": operation_applied,
        "warning": warning,
        "effective_enabled_after": effective_enabled,
        "remaining_slots": matching_after,
    }


def get_employee_on_machine(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    employee_code: str,
    request: MachineEmployeeReadRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    user_id, row = _resolve_user_id_for_machine(repo, employee_code, request.user_id)
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        users = client.list_all_user_ids(resolved.machine_number)
        matches = [entry for entry in users if int(entry.get("user_id", -1)) == user_id]
        match = matches[0] if matches else None

        user_name: str | None = None
        if matches and request.include_user_name:
            user_name = client.get_user_name(resolved.machine_number, user_id)
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "employee_code": str((row or {}).get("employee_code") or employee_code),
        "device_id": resolved.device_id,
        "source": resolved.source,
        "machine_ip": resolved.machine_ip,
        "machine_port": resolved.machine_port,
        "machine_number": resolved.machine_number,
        "user_id": user_id,
        "exists_on_machine": bool(match),
        "user_name": user_name,
        "state_source": "GetAllUserID",
        "machine_user_record": match,
        "machine_user_records": matches,
        "machine_user_slots": len(matches),
        "effective_enabled": any(bool(entry.get("enabled")) for entry in matches),
        "machine_user_count": len(users),
    }


def list_employees_on_machine(
    *,
    settings: Settings,
    request: MachineEmployeeListRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        users = client.list_all_user_ids(resolved.machine_number)
        rows: list[dict[str, Any]] = []
        for entry in users:
            row = dict(entry)
            if request.include_user_names:
                try:
                    row["user_name"] = client.get_user_name(resolved.machine_number, int(row["user_id"]))
                except MachineSdkError as exc:
                    row["user_name"] = None
                    row["user_name_error"] = str(exc)
            rows.append(row)
    finally:
        client.disconnect(resolved.machine_number)

    active_count = sum(1 for row in rows if bool(row.get("enabled")))
    return {
        "machine": {
            "device_id": resolved.device_id,
            "source": resolved.source,
            "machine_ip": resolved.machine_ip,
            "machine_port": resolved.machine_port,
            "machine_number": resolved.machine_number,
            "sdk_dll_path": resolved.sdk_dll_path,
        },
        "total": len(rows),
        "active": active_count,
        "inactive": len(rows) - active_count,
        "rows": rows,
    }


def delete_employee_on_machine(
    *,
    repo: AttendanceRepository,
    settings: Settings,
    employee_code: str,
    request: MachineEmployeeDeleteRequest,
    device_resolver: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    user_id, row = _resolve_user_id_for_machine(repo, employee_code, request.user_id)
    resolved = resolve_machine_connection(settings, request, device_resolver=device_resolver)

    client = SBXPCClient(resolved.sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(
        machine_number=resolved.machine_number,
        ip_address=resolved.machine_ip,
        port=resolved.machine_port,
        password=resolved.machine_password,
    )
    try:
        users = client.list_all_user_ids(resolved.machine_number)
        matching = [entry for entry in users if int(entry.get("user_id", -1)) == user_id]
        target_slots: list[tuple[int, int]] = []
        if request.all_slots:
            target_slots = sorted(
                {
                    (
                        int(entry.get("e_machine_number", request.e_machine_number)),
                        int(entry.get("backup_number", request.backup_number)),
                    )
                    for entry in matching
                }
            )
        else:
            target_slots = [(request.e_machine_number, request.backup_number)]

        client.enable_device(resolved.machine_number, False)
        try:
            for e_machine_number, backup_number in target_slots:
                client.delete_enroll_data(
                    resolved.machine_number,
                    user_id,
                    e_machine_number=e_machine_number,
                    backup_number=backup_number,
                )
        finally:
            client.enable_device(resolved.machine_number, True)

        users_after = client.list_all_user_ids(resolved.machine_number)
        remaining_slots = [entry for entry in users_after if int(entry.get("user_id", -1)) == user_id]
    finally:
        client.disconnect(resolved.machine_number)

    return {
        "employee_code": str((row or {}).get("employee_code") or employee_code),
        "device_id": resolved.device_id,
        "source": resolved.source,
        "machine_ip": resolved.machine_ip,
        "machine_port": resolved.machine_port,
        "machine_number": resolved.machine_number,
        "user_id": user_id,
        "deleted": True,
        "e_machine_number": request.e_machine_number,
        "backup_number": request.backup_number,
        "all_slots": request.all_slots,
        "requested_slot": {
            "e_machine_number": request.e_machine_number,
            "backup_number": request.backup_number,
        },
        "deleted_slots": [{"e_machine_number": e, "backup_number": b} for e, b in target_slots],
        "exists_on_machine_after": bool(remaining_slots),
        "remaining_slots": remaining_slots,
    }


__all__ = [
    "MachineCapabilitiesProbeRequest",
    "MachineConnectionRequest",
    "MachineDeviceDetailsRequest",
    "MachineEmployeeDeleteRequest",
    "MachineEmployeeListRequest",
    "MachineEmployeeReadRequest",
    "MachineEmployeeToggleRequest",
    "MachineEmployeeUpdateRequest",
    "MachineGeneralLogsReadRequest",
    "MachineTimeReadRequest",
    "MachineTimeSetRequest",
    "MachineXmlBinaryField",
    "MachineXmlBinaryParseField",
    "MachineXmlExecuteRequest",
    "MachineXmlField",
    "MachineXmlParseField",
    "MachineSdkError",
    "MachineSyncRequest",
    "build_machine_sync_preview",
    "check_machine_connection",
    "create_employee_on_machine",
    "delete_employee_on_machine",
    "get_employee_on_machine",
    "get_machine_device_details",
    "list_employees_on_machine",
    "probe_machine_capabilities",
    "read_machine_general_logs",
    "read_machine_time",
    "run_machine_xml_execute",
    "run_machine_sync_from_api",
    "set_machine_time",
    "toggle_employee_on_machine",
    "update_employee_on_machine",
]
