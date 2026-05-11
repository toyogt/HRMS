from __future__ import annotations

from datetime import datetime
from pathlib import Path

from attendance_relay.db import create_db_engine, init_local_schema
from attendance_relay.machine_admin import (
    MachineConnectionRequest,
    MachineEmployeeDeleteRequest,
    MachineEmployeeListRequest,
    MachineEmployeeReadRequest,
    MachineEmployeeToggleRequest,
    MachineEmployeeUpdateRequest,
    MachineSyncRequest,
    build_machine_sync_preview,
    check_machine_connection,
    create_employee_on_machine,
    delete_employee_on_machine,
    get_employee_on_machine,
    list_employees_on_machine,
    resolve_machine_connection,
    toggle_employee_on_machine,
    update_employee_on_machine,
)
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings


class FakeClient:
    instances: list["FakeClient"] = []
    user_rows: list[dict[str, int | bool]] = [
        {
            "user_id": 1001,
            "e_machine_number": 1,
            "backup_number": 0,
            "machine_privilege": 0,
            "enabled": True,
        }
    ]

    def __init__(self, dll_path: str) -> None:
        self.dll_path = dll_path
        self.calls: list[tuple[str, object]] = []
        FakeClient.instances.append(self)

    def dotnet(self) -> None:
        self.calls.append(("dotnet", None))

    def connect_tcpip(self, machine_number: int, ip_address: str, port: int, password: int) -> None:
        self.calls.append(("connect_tcpip", (machine_number, ip_address, port, password)))

    def disconnect(self, machine_number: int) -> None:
        self.calls.append(("disconnect", machine_number))

    def enable_device(self, machine_number: int, enabled: bool) -> None:
        self.calls.append(("enable_device", (machine_number, enabled)))

    def set_user_name(self, machine_number: int, user_id: int, user_name: str) -> None:
        self.calls.append(("set_user_name", (machine_number, user_id, user_name)))

    def set_user_info(
        self,
        machine_number: int,
        user_id: int,
        timezone1: int,
        timezone2: int,
        group_no: int,
        card_no: int,
    ) -> str:
        self.calls.append(
            (
                "set_user_info",
                (machine_number, user_id, timezone1, timezone2, group_no, card_no),
            )
        )
        return "<ok/>"

    def enable_user(
        self,
        machine_number: int,
        user_id: int,
        *,
        e_machine_number: int = 1,
        backup_number: int = 0,
        enabled: bool = True,
    ) -> None:
        self.calls.append(("enable_user", (machine_number, user_id, e_machine_number, backup_number, enabled)))

    def set_enroll_data1(
        self,
        machine_number: int,
        user_id: int,
        *,
        backup_number: int = 0,
        machine_privilege: int = 0,
        credential_value: int = 0,
    ) -> None:
        self.calls.append(
            (
                "set_enroll_data1",
                (machine_number, user_id, backup_number, machine_privilege, credential_value),
            )
        )

    def get_device_time(self, machine_number: int) -> datetime:
        self.calls.append(("get_device_time", machine_number))
        return datetime(2026, 5, 5, 10, 11, 12)

    def list_all_user_ids(self, machine_number: int) -> list[dict[str, int | bool]]:
        self.calls.append(("list_all_user_ids", machine_number))
        return list(self.user_rows)

    def get_user_name(self, machine_number: int, user_id: int) -> str:
        self.calls.append(("get_user_name", (machine_number, user_id)))
        return "Test User"

    def delete_enroll_data(
        self,
        machine_number: int,
        user_id: int,
        *,
        e_machine_number: int = 1,
        backup_number: int = 0,
    ) -> None:
        self.calls.append(("delete_enroll_data", (machine_number, user_id, e_machine_number, backup_number)))


def _build_repo(tmp_path: Path) -> tuple[AttendanceRepository, Settings]:
    db_path = tmp_path / "test.db"
    settings = Settings(
        db_url=f"sqlite:///{db_path}",
        outbound_url="https://localhost:9443/api/attendance",
        outbound_api_key="test-key",
        machine_sync_ip="192.168.29.98",
        machine_sync_port=5005,
        machine_sync_password=0,
        machine_sync_machine_number=1,
        machine_sync_timezone1=1,
        machine_sync_timezone2=0,
        machine_sync_group_no=1,
        machine_sdk_dll_path="sdk_extracted/20211204-SBXPC-1/bin/SBXPCDLL64.dll",
    )
    engine = create_db_engine(settings)
    init_local_schema(engine)
    repo = AttendanceRepository(engine)
    repo.upsert_employee_master_records(
        [
            {
                "employee_code": "E1001",
                "employee_code_normalized": "1001",
                "employee_name": "Test User",
                "card_no": "9001001",
                "proximity_card_no": "",
                "department": "IT",
                "designation": "Engineer",
                "company_name": "Acme",
            }
        ]
    )
    return repo, settings


def test_resolve_machine_connection_defaults(tmp_path: Path) -> None:
    _, settings = _build_repo(tmp_path)
    resolved = resolve_machine_connection(settings, MachineConnectionRequest())
    assert resolved.machine_ip == "192.168.29.98"
    assert resolved.machine_port == 5005
    assert resolved.machine_number == 1


def test_resolve_machine_connection_uses_device_machine_number(tmp_path: Path) -> None:
    _, settings = _build_repo(tmp_path)
    resolved = resolve_machine_connection(
        settings,
        MachineConnectionRequest(device_id="DEV-01"),
        device_resolver=lambda _device_id: {
            "device_id": "DEV-01",
            "is_active": True,
            "ip": "192.168.29.120",
            "port": 5005,
            "machine_password": "0",
            "machine_number": 7,
        },
    )
    assert resolved.machine_ip == "192.168.29.120"
    assert resolved.machine_port == 5005
    assert resolved.machine_number == 7


def test_build_machine_sync_preview(tmp_path: Path) -> None:
    repo, settings = _build_repo(tmp_path)
    result = build_machine_sync_preview(
        repo=repo,
        settings=settings,
        request=MachineSyncRequest(dry_run=True, limit=10),
    )
    assert result["dry_run"] is True
    assert result["rows"] == 1
    assert result["preview"][0]["resolved_user_id"] == 1001


def test_machine_connection_uses_sdk(monkeypatch, tmp_path: Path) -> None:
    _, settings = _build_repo(tmp_path)
    monkeypatch.setattr("attendance_relay.machine_admin.SBXPCClient", FakeClient)
    result = check_machine_connection(settings=settings, request=MachineConnectionRequest())
    assert result["connected"] is True
    assert result["device_time"] == "2026-05-05 10:11:12"


def test_update_employee_on_machine_calls_expected_sdk_methods(monkeypatch, tmp_path: Path) -> None:
    FakeClient.instances.clear()
    repo, settings = _build_repo(tmp_path)
    monkeypatch.setattr("attendance_relay.machine_admin.SBXPCClient", FakeClient)

    result = update_employee_on_machine(
        repo=repo,
        settings=settings,
        employee_code="E1001",
        request=MachineEmployeeUpdateRequest(
            user_name="Updated Name",
            enable=True,
            timezone1=2,
            timezone2=3,
            group_no=4,
        ),
    )

    assert result["user_id"] == 1001
    assert result["user_name"] == "Updated Name"
    calls = FakeClient.instances[-1].calls
    assert any(name == "set_user_name" for name, _ in calls)
    assert any(name == "set_user_info" for name, _ in calls)
    assert any(name == "enable_user" for name, _ in calls)
    assert not any(name == "set_enroll_data1" for name, _ in calls)


def test_create_employee_on_machine_creates_missing_enroll_record(monkeypatch, tmp_path: Path) -> None:
    FakeClient.instances.clear()
    FakeClient.user_rows = []
    repo, settings = _build_repo(tmp_path)
    monkeypatch.setattr("attendance_relay.machine_admin.SBXPCClient", FakeClient)

    result = create_employee_on_machine(
        repo=repo,
        settings=settings,
        employee_code="E1001",
        request=MachineEmployeeUpdateRequest(enable=True),
    )

    assert result["user_id"] == 1001
    assert result["created_on_machine"] is True
    calls = FakeClient.instances[-1].calls
    assert ("set_enroll_data1", (1, 1001, 11, 0, 9001001)) in calls
    FakeClient.user_rows = [
        {
            "user_id": 1001,
            "e_machine_number": 1,
            "backup_number": 0,
            "machine_privilege": 0,
            "enabled": True,
        }
    ]


def test_toggle_employee_disable(monkeypatch, tmp_path: Path) -> None:
    FakeClient.instances.clear()
    repo, settings = _build_repo(tmp_path)
    monkeypatch.setattr("attendance_relay.machine_admin.SBXPCClient", FakeClient)

    result = toggle_employee_on_machine(
        repo=repo,
        settings=settings,
        employee_code="E1001",
        enabled=False,
        request=MachineEmployeeToggleRequest(),
    )

    assert result["enabled"] is False
    calls = FakeClient.instances[-1].calls
    assert ("enable_user", (1, 1001, 1, 0, False)) in calls


def test_get_employee_on_machine(monkeypatch, tmp_path: Path) -> None:
    FakeClient.instances.clear()
    repo, settings = _build_repo(tmp_path)
    monkeypatch.setattr("attendance_relay.machine_admin.SBXPCClient", FakeClient)

    result = get_employee_on_machine(
        repo=repo,
        settings=settings,
        employee_code="E1001",
        request=MachineEmployeeReadRequest(),
    )

    assert result["exists_on_machine"] is True
    assert result["user_id"] == 1001
    assert result["user_name"] == "Test User"
    calls = FakeClient.instances[-1].calls
    assert any(name == "list_all_user_ids" for name, _ in calls)
    assert any(name == "get_user_name" for name, _ in calls)


def test_list_employees_on_machine_counts_active_users(monkeypatch, tmp_path: Path) -> None:
    FakeClient.instances.clear()
    FakeClient.user_rows = [
        {
            "user_id": 1001,
            "e_machine_number": 1,
            "backup_number": 0,
            "machine_privilege": 0,
            "enabled": True,
        },
        {
            "user_id": 1002,
            "e_machine_number": 1,
            "backup_number": 0,
            "machine_privilege": 0,
            "enabled": False,
        },
    ]
    _, settings = _build_repo(tmp_path)
    monkeypatch.setattr("attendance_relay.machine_admin.SBXPCClient", FakeClient)

    result = list_employees_on_machine(settings=settings, request=MachineEmployeeListRequest(include_user_names=True))

    assert result["total"] == 2
    assert result["active"] == 1
    assert result["inactive"] == 1
    assert result["rows"][0]["user_name"] == "Test User"
    calls = FakeClient.instances[-1].calls
    assert any(name == "list_all_user_ids" for name, _ in calls)
    assert any(name == "get_user_name" for name, _ in calls)
    FakeClient.user_rows = [
        {
            "user_id": 1001,
            "e_machine_number": 1,
            "backup_number": 0,
            "machine_privilege": 0,
            "enabled": True,
        }
    ]


def test_delete_employee_on_machine(monkeypatch, tmp_path: Path) -> None:
    FakeClient.instances.clear()
    repo, settings = _build_repo(tmp_path)
    monkeypatch.setattr("attendance_relay.machine_admin.SBXPCClient", FakeClient)

    result = delete_employee_on_machine(
        repo=repo,
        settings=settings,
        employee_code="E1001",
        request=MachineEmployeeDeleteRequest(),
    )

    assert result["deleted"] is True
    calls = FakeClient.instances[-1].calls
    assert ("delete_enroll_data", (1, 1001, 1, 0)) in calls
