from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from attendance_relay.ingress_app import create_ingress_app
from attendance_relay.settings import Settings


def _build_app(tmp_path: Path):
    settings = Settings(
        env="test",
        db_url=f"sqlite:///{tmp_path / 'middleware.db'}",
        log_level="WARNING",
        outbound_api_key="test-outbound",
        middleware_api_key="mw-key",
        agent_api_key="agent-key",
        agent_jwt_token="agent-jwt",
        webhook_hmac_secret="webhook-secret",
    )
    app = create_ingress_app(settings)
    return app, settings


def test_device_command_claim_and_result_flow(tmp_path: Path) -> None:
    app, settings = _build_app(tmp_path)
    with TestClient(app) as client:
        denied = client.get("/api/v1/devices")
        assert denied.status_code == 401

        headers = {"x-api-key": settings.middleware_api_key}
        created = client.post(
            "/api/v1/devices",
            headers=headers,
            json={
                "device_id": "FACTORY_T501_01",
                "device_name": "Factory Gate",
                "site_id": "PLANT-A",
                "ip": "192.168.29.98",
                "port": 5005,
                "machine_number": 2,
                "timezone": "Asia/Kolkata",
                "is_active": True,
                "sdk_protocol": "sbxpc_tcp",
            },
        )
        assert created.status_code == 201
        assert created.json()["device_id"] == "FACTORY_T501_01"
        assert created.json()["machine_number"] == 2

        command = client.post(
            "/api/v1/commands",
            headers=headers,
            json={
                "request_id": "req-001",
                "device_id": "FACTORY_T501_01",
                "command_type": "employee.enable",
                "payload": {"employee_code": "EMP001"},
                "priority": 50,
            },
        )
        assert command.status_code == 202
        command_id = command.json()["command_id"]

        agent_headers = {
            "x-api-key": settings.agent_api_key,
            "authorization": f"Bearer {settings.agent_jwt_token}",
        }
        claimed = client.post(
            "/api/v1/agent/commands/claim",
            headers=agent_headers,
            json={
                "agent_id": "AGENT_PLANT_A",
                "device_ids": ["FACTORY_T501_01"],
                "limit": 5,
            },
        )
        assert claimed.status_code == 200
        rows = claimed.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["command_id"] == command_id

        result = client.post(
            f"/api/v1/agent/commands/{command_id}/result",
            headers=agent_headers,
            json={
                "agent_id": "AGENT_PLANT_A",
                "success": True,
                "result_payload": {"applied": True},
            },
        )
        assert result.status_code == 200
        assert result.json()["status"] == "SUCCESS"


def test_agent_attendance_batch_dedup(tmp_path: Path) -> None:
    app, settings = _build_app(tmp_path)
    with TestClient(app) as client:
        mw_headers = {"x-api-key": settings.middleware_api_key}
        client.post(
            "/api/v1/devices",
            headers=mw_headers,
            json={
                "device_id": "FACTORY_T501_01",
                "device_name": "Factory Gate",
                "site_id": "PLANT-A",
                "ip": "192.168.29.98",
                "port": 5005,
                "machine_number": 1,
                "timezone": "Asia/Kolkata",
                "is_active": True,
                "sdk_protocol": "sbxpc_tcp",
            },
        )

        agent_headers = {
            "x-api-key": settings.agent_api_key,
            "authorization": f"Bearer {settings.agent_jwt_token}",
        }
        event = {
            "event_id": "evt-001",
            "employee_code": "EMP001",
            "machine_user_id": "101",
            "device_id": "FACTORY_T501_01",
            "device_ip": "192.168.29.98",
            "timestamp_local": "2026-05-05 09:30:00",
            "timestamp_utc": "2026-05-05T04:00:00Z",
            "timezone": "Asia/Kolkata",
            "verification_mode": "fingerprint",
            "source": "pull_sdk",
        }
        batch = client.post(
            "/api/v1/agent/attendance/batch",
            headers=agent_headers,
            json={"agent_id": "AGENT_PLANT_A", "events": [event, event]},
        )
        assert batch.status_code == 200
        body = batch.json()
        assert body["inserted"] == 1
        assert body["deduped"] == 1

        listed = client.get("/api/v1/attendance", headers=mw_headers)
        assert listed.status_code == 200
        assert listed.json()["loaded"] >= 1


def test_employee_create_can_push_to_machine(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_create_employee_on_machine(*, repo, settings, employee_code, request):
        captured["employee_code"] = employee_code
        captured["request"] = request
        return {
            "employee_code": employee_code,
            "user_id": request.user_id,
            "user_name": request.user_name,
            "card_no": int(request.card_no or 0),
        }

    monkeypatch.setattr("attendance_relay.ingress_app.create_employee_on_machine", _fake_create_employee_on_machine)

    app, settings = _build_app(tmp_path)
    with TestClient(app) as client:
        headers = {"x-api-key": settings.middleware_api_key}
        created = client.post(
            "/api/v1/employees",
            headers=headers,
            json={
                "employee_code": "KV229A",
                "employee_name": "Kunal Verma-Test",
                "card_no": "229",
                "phone_no": "9876543210",
                "department": "OPERATIONS",
                "designation": "SUPERVISOR",
                "machine": {
                    "sync_to_machine": True,
                    "machine_ip": "192.168.29.82",
                    "machine_port": 5005,
                    "machine_password": 0,
                    "machine_number": 1,
                    "user_id": 229,
                    "user_name": "Kunal Verma-Test",
                    "card_no": "229",
                },
            },
        )

        assert created.status_code == 201
        body = created.json()
        assert body["employee"]["employee_code"] == "KV229A"
        assert body["machine_sync"]["requested"] is True
        assert body["machine_sync"]["success"] is True
        assert body["machine_sync"]["result"]["user_id"] == 229
        assert body["machine_sync"]["result"]["card_no"] == 229

        assert captured["employee_code"] == "KV229A"
        request_obj = captured["request"]
        assert getattr(request_obj, "machine_ip") == "192.168.29.82"
        assert getattr(request_obj, "machine_port") == 5005
        assert getattr(request_obj, "user_id") == 229


def test_employee_list_and_read_endpoints(tmp_path: Path) -> None:
    app, settings = _build_app(tmp_path)
    with TestClient(app) as client:
        headers = {"x-api-key": settings.middleware_api_key}
        created = client.post(
            "/api/v1/employees",
            headers=headers,
            json={
                "employee_code": "E1001",
                "employee_name": "Test User",
                "card_no": "9001001",
                "department": "IT",
                "designation": "Engineer",
            },
        )
        assert created.status_code == 201

        listed = client.get("/api/v1/employees", headers=headers, params={"department": "IT"})
        assert listed.status_code == 200
        body = listed.json()
        assert body["loaded"] == 1
        assert body["rows"][0]["employee_code"] == "E1001"

        exact = client.get("/api/v1/employees/E1001", headers=headers)
        assert exact.status_code == 200
        assert exact.json()["employee_name"] == "Test User"

        normalized = client.get("/api/v1/employees/1001", headers=headers)
        assert normalized.status_code == 200
        assert normalized.json()["employee_code"] == "E1001"


def test_machine_employee_read_endpoint(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_get_employee_on_machine(*, repo, settings, employee_code, request):
        captured["employee_code"] = employee_code
        captured["request"] = request
        return {"employee_code": employee_code, "user_id": 229, "exists_on_machine": True}

    monkeypatch.setattr("attendance_relay.ingress_app.get_employee_on_machine", _fake_get_employee_on_machine)

    app, settings = _build_app(tmp_path)
    with TestClient(app) as client:
        headers = {"authorization": f"Bearer {settings.middleware_bearer_token}"}
        response = client.post(
            "/api/machine/employees/KV229A/read",
            headers=headers,
            json={
                "machine_ip": "192.168.29.82",
                "machine_port": 5005,
                "machine_password": 0,
                "machine_number": 1,
                "user_id": 229,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["exists_on_machine"] is True
        assert body["user_id"] == 229
        assert captured["employee_code"] == "KV229A"


def test_machine_employee_read_all_endpoint(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_list_employees_on_machine(*, settings, request):
        captured["request"] = request
        return {
            "machine": {"machine_ip": request.machine_ip, "machine_port": request.machine_port, "machine_number": 1},
            "total": 2,
            "active": 1,
            "inactive": 1,
            "rows": [{"user_id": 229, "enabled": True}, {"user_id": 230, "enabled": False}],
        }

    monkeypatch.setattr("attendance_relay.ingress_app.list_employees_on_machine", _fake_list_employees_on_machine)

    app, settings = _build_app(tmp_path)
    with TestClient(app) as client:
        headers = {"authorization": f"Bearer {settings.middleware_bearer_token}"}
        response = client.post(
            "/api/machine/employees/read-all",
            headers=headers,
            json={
                "machine_ip": "192.168.29.82",
                "machine_port": 5005,
                "machine_password": 0,
                "machine_number": 1,
                "include_user_names": True,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["active"] == 1
        request_obj = captured["request"]
        assert getattr(request_obj, "include_user_names") is True


def test_machine_employee_delete_endpoint(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_delete_employee_on_machine(*, repo, settings, employee_code, request):
        captured["employee_code"] = employee_code
        captured["request"] = request
        return {"employee_code": employee_code, "user_id": 229, "deleted": True}

    monkeypatch.setattr("attendance_relay.ingress_app.delete_employee_on_machine", _fake_delete_employee_on_machine)

    app, settings = _build_app(tmp_path)
    with TestClient(app) as client:
        headers = {"authorization": f"Bearer {settings.middleware_bearer_token}"}
        response = client.request(
            "DELETE",
            "/api/machine/employees/KV229A",
            headers=headers,
            json={
                "machine_ip": "192.168.29.82",
                "machine_port": 5005,
                "machine_password": 0,
                "machine_number": 1,
                "user_id": 229,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["deleted"] is True
        assert captured["employee_code"] == "KV229A"
