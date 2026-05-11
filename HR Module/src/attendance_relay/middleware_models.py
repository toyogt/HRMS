from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DeviceUpsertRequest(BaseModel):
    device_id: str
    device_name: str = ""
    site_id: str = ""
    ip: str
    port: int = Field(default=5005, ge=1, le=65535)
    machine_number: int = Field(default=1, ge=1)
    timezone: str = "Asia/Kolkata"
    is_active: bool = True
    sdk_protocol: str = "sbxpc_tcp"
    machine_password: str = ""


class DevicePatchRequest(BaseModel):
    device_name: str | None = None
    site_id: str | None = None
    ip: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    machine_number: int | None = Field(default=None, ge=1)
    timezone: str | None = None
    is_active: bool | None = None
    sdk_protocol: str | None = None
    machine_password: str | None = None


class CommandCreateRequest(BaseModel):
    request_id: str
    device_id: str
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=1, le=1000)


class CommandClaimRequest(BaseModel):
    agent_id: str
    device_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=100)


class CommandResultRequest(BaseModel):
    agent_id: str
    success: bool
    error_code: str | None = None
    error_message: str | None = None
    result_payload: dict[str, Any] = Field(default_factory=dict)


class AgentHeartbeatRequest(BaseModel):
    agent_id: str
    site_id: str = ""
    version: str = ""
    host_name: str = ""
    local_ip: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class AttendanceEventRequest(BaseModel):
    event_id: str | None = None
    employee_code: str
    machine_user_id: str = ""
    device_id: str
    device_ip: str = ""
    timestamp_local: str
    timestamp_utc: str | None = None
    timezone: str = "Asia/Kolkata"
    verification_mode: str = ""
    source: str = "pull_sdk"
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class AgentAttendanceBatchRequest(BaseModel):
    agent_id: str
    events: list[AttendanceEventRequest] = Field(default_factory=list)


class WebhookSubscriptionRequest(BaseModel):
    subscription_id: str | None = None
    event_type: str
    target_url: str
    is_active: bool = True


class WebhookDispatchRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)


class WebhookEventRequest(BaseModel):
    event_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class EmployeeUpsertRequest(BaseModel):
    employee_code: str
    employee_name: str = ""
    father_name: str = ""
    card_no: str = ""
    proximity_card_no: str = ""
    email_id: str = ""
    phone_no: str = ""
    department: str = ""
    designation: str = ""
    branch_name: str = ""
    office_time_policy: str = ""
    date_of_birth: str = ""
    date_of_join: str = ""
    shift_start_date: str = ""
    shift_code: str = ""
    weekly_off: str = ""
    company_name: str = ""


class EmployeeMachineCreateRequest(BaseModel):
    sync_to_machine: bool = False
    device_id: str | None = None
    machine_ip: str | None = None
    machine_port: int | None = Field(default=None, ge=1, le=65535)
    machine_password: int | None = None
    machine_number: int | None = Field(default=None, ge=1)
    sdk_dll_path: str | None = None
    user_id: int | None = Field(default=None, ge=0, le=2_147_483_647)
    user_name: str | None = None
    card_no: str | None = None
    timezone1: int | None = None
    timezone2: int | None = None
    group_no: int | None = None
    enable: bool | None = None
    e_machine_number: int = Field(default=1, ge=1)
    backup_number: int = Field(default=0, ge=0)


class EmployeeCreateRequest(EmployeeUpsertRequest):
    machine: EmployeeMachineCreateRequest | None = None


class EmployeePatchRequest(BaseModel):
    employee_name: str | None = None
    father_name: str | None = None
    card_no: str | None = None
    proximity_card_no: str | None = None
    email_id: str | None = None
    phone_no: str | None = None
    department: str | None = None
    designation: str | None = None
    branch_name: str | None = None
    office_time_policy: str | None = None
    date_of_birth: str | None = None
    date_of_join: str | None = None
    shift_start_date: str | None = None
    shift_code: str | None = None
    weekly_off: str | None = None
    company_name: str | None = None


class MasterDataCreateRequest(BaseModel):
    code: str
    name: str
    description: str = ""
    is_active: bool = True


class MasterDataPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class DeviceScopedCommandRequest(BaseModel):
    request_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=1, le=1000)
