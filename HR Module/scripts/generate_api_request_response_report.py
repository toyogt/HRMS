from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi.testclient import TestClient

import attendance_relay.ingress_app as ingress_app
from attendance_relay.ingress_app import create_ingress_app
from attendance_relay.settings import Settings


BASE_URL = "http://127.0.0.1:9100"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_REPORT = PROJECT_ROOT / "docs" / "API_REQUEST_RESPONSE_TEST_REPORT.md"
JSON_REPORT = PROJECT_ROOT / "var" / "logs" / "api_request_response_report.json"
TEST_EMPLOYEE_CODE = "235"
TEST_EMPLOYEE_NAME = "TESTING-001"
TEST_EMPLOYEE_CARD = "235"


def _json_default(value: Any) -> str:
    return str(value)


def _pretty(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True, default=_json_default)


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in {"x-api-key", "authorization"}:
            if value.lower().startswith("bearer "):
                output[key] = "Bearer <masked>"
            else:
                output[key] = "<masked>"
        else:
            output[key] = value
    return output


def _connection_summary(request: Any) -> dict[str, Any]:
    return {
        "device_id": getattr(request, "device_id", None) or "DEV-LIVE-01",
        "source": "test-double",
        "machine_ip": getattr(request, "machine_ip", None) or "192.168.1.19",
        "machine_port": getattr(request, "machine_port", None) or 5005,
        "machine_number": getattr(request, "machine_number", None) or 1,
    }


def _install_machine_test_doubles() -> None:
    def fake_create_employee_on_machine(*, repo: Any, settings: Settings, employee_code: str, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "employee_code": employee_code,
            "device_id": getattr(request, "device_id", None) or "DEV-LIVE-01",
            "user_id": getattr(request, "user_id", None) or int(TEST_EMPLOYEE_CODE),
            "user_name": getattr(request, "user_name", None) or TEST_EMPLOYEE_NAME,
            "card_no": int(getattr(request, "card_no", None) or TEST_EMPLOYEE_CARD),
            "created_on_machine": True,
            "user_info_applied": True,
        }

    def fake_check_machine_connection(*, settings: Settings, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "connected": True,
            **_connection_summary(request),
            "device_time": "2026-05-09 10:30:00",
        }

    def fake_get_machine_device_details(*, settings: Settings, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "machine": _connection_summary(request),
            "serial_number": "TEST-SN-001",
            "device_model": "SBXPC test device",
            "firmware_version": "TEST-1.0",
            "backup_number": 11,
            "user_count": 2 if getattr(request, "include_user_count", False) else None,
            "warnings": [],
        }

    def fake_read_machine_time(*, settings: Settings, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "machine": _connection_summary(request),
            "device_time": "2026-05-09 10:30:00",
        }

    def fake_set_machine_time(*, settings: Settings, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "machine": _connection_summary(request),
            "device_time": getattr(request, "device_time", None) or "2026-05-09 10:30:00",
            "set": True,
        }

    def fake_read_machine_general_logs(*, settings: Settings, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "machine": _connection_summary(request),
            "loaded": 2,
            "rows": [
                {"machine_user_id": TEST_EMPLOYEE_CODE, "timestamp": "2026-05-09 09:30:00"},
                {"machine_user_id": "1002", "timestamp": "2026-05-09 09:45:00"},
            ],
        }

    def fake_probe_machine_capabilities(*, settings: Settings, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "machine": _connection_summary(request),
            "capabilities": {
                "connect_tcpip": True,
                "read_general_logs": True,
                "set_time": True,
                "employee_enable_disable": True,
            },
            "probes": {
                "general_logs_read": {
                    "success": True,
                    "loaded": 1 if getattr(request, "include_log_read_test", False) else 0,
                }
            },
        }

    def fake_run_machine_xml_execute(*, settings: Settings, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "executed": True,
            "request_name": getattr(request, "request_name", "GetDeviceInfo"),
            "parsed": {"Result": "OK"},
            "parsed_binary": {},
            "response_xml": "<Response><Result>OK</Result></Response>",
        }

    def fake_list_employees_on_machine(*, settings: Settings, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "machine": _connection_summary(request),
            "total": 2,
            "active": 1,
            "inactive": 1,
            "rows": [
                {"user_id": int(TEST_EMPLOYEE_CODE), "enabled": True, "user_name": TEST_EMPLOYEE_NAME},
                {"user_id": 1002, "enabled": False, "user_name": "Disabled User"},
            ],
        }

    def fake_update_employee_on_machine(*, repo: Any, settings: Settings, employee_code: str, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "employee_code": employee_code,
            "user_id": getattr(request, "user_id", None) or int(TEST_EMPLOYEE_CODE),
            "user_name": getattr(request, "user_name", None) or TEST_EMPLOYEE_NAME,
            "card_no": int(getattr(request, "card_no", None) or TEST_EMPLOYEE_CARD),
            "existed_before": True,
            "created_on_machine": False,
            "user_info_applied": True,
            "user_info_error": None,
        }

    def fake_get_employee_on_machine(*, repo: Any, settings: Settings, employee_code: str, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "employee_code": employee_code,
            "user_id": getattr(request, "user_id", None) or int(TEST_EMPLOYEE_CODE),
            "exists_on_machine": True,
            "user_name": TEST_EMPLOYEE_NAME,
            "machine_user_slots": 1,
            "effective_enabled": True,
            "machine_user_count": 2,
        }

    def fake_delete_employee_on_machine(*, repo: Any, settings: Settings, employee_code: str, request: Any, **_: Any) -> dict[str, Any]:
        return {
            "employee_code": employee_code,
            "user_id": getattr(request, "user_id", None) or int(TEST_EMPLOYEE_CODE),
            "deleted": True,
            "all_slots": getattr(request, "all_slots", False),
            "exists_on_machine_after": False,
            "remaining_slots": [],
        }

    def fake_toggle_employee_on_machine(
        *,
        repo: Any,
        settings: Settings,
        employee_code: str,
        enabled: bool,
        request: Any,
        **_: Any,
    ) -> dict[str, Any]:
        return {
            "employee_code": employee_code,
            "user_id": getattr(request, "user_id", None) or int(TEST_EMPLOYEE_CODE),
            "enabled": enabled,
            "all_slots": getattr(request, "all_slots", False),
            "operation_applied": True,
            "warning": None,
            "effective_enabled_after": enabled,
        }

    def fake_dispatch_due_webhooks(*, settings: Settings, repo: Any, limit: int) -> dict[str, int]:
        return {"picked": 1, "sent": 1, "failed": 0, "dead": 0, "skipped": 0}

    ingress_app.create_employee_on_machine = fake_create_employee_on_machine
    ingress_app.check_machine_connection = fake_check_machine_connection
    ingress_app.get_machine_device_details = fake_get_machine_device_details
    ingress_app.read_machine_time = fake_read_machine_time
    ingress_app.set_machine_time = fake_set_machine_time
    ingress_app.read_machine_general_logs = fake_read_machine_general_logs
    ingress_app.probe_machine_capabilities = fake_probe_machine_capabilities
    ingress_app.run_machine_xml_execute = fake_run_machine_xml_execute
    ingress_app.list_employees_on_machine = fake_list_employees_on_machine
    ingress_app.update_employee_on_machine = fake_update_employee_on_machine
    ingress_app.get_employee_on_machine = fake_get_employee_on_machine
    ingress_app.delete_employee_on_machine = fake_delete_employee_on_machine
    ingress_app.toggle_employee_on_machine = fake_toggle_employee_on_machine
    ingress_app.dispatch_due_webhooks = fake_dispatch_due_webhooks


def _body_from_response(response: Any) -> Any:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.text


def _call(
    *,
    client: TestClient,
    records: list[dict[str, Any]],
    name: str,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    content: bytes | str | None = None,
    note: str = "",
) -> Any:
    headers = headers or {}
    params = params or {}
    url = f"{BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params, doseq=True)}"

    request_record: dict[str, Any] = {
        "name": name,
        "method": method.upper(),
        "url": url,
        "path": path,
        "headers": _mask_headers(headers),
        "query": params,
        "json": json_body,
        "content": content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content,
        "note": note,
    }
    try:
        response = client.request(method, path, headers=headers, params=params, json=json_body, content=content)
        response_body = _body_from_response(response)
        request_record["response"] = {
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "body": response_body,
        }
    except Exception as exc:  # noqa: BLE001
        response_body = {"exception": f"{type(exc).__name__}: {exc}"}
        request_record["response"] = {
            "status_code": None,
            "content_type": "",
            "body": response_body,
        }
    records.append(request_record)
    return response_body


def _write_reports(records: list[dict[str, Any]], *, settings: Settings) -> None:
    JSON_REPORT.parent.mkdir(parents=True, exist_ok=True)
    MARKDOWN_REPORT.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {
        "generated_at_utc": generated_at,
        "base_url": BASE_URL,
        "scope": "FastAPI TestClient contract run with an isolated temporary SQLite database.",
        "machine_api_note": "Direct machine SDK endpoints used test doubles, not the physical biometric device.",
        "records": records,
    }
    JSON_REPORT.write_text(_pretty(payload) + "\n", encoding="utf-8")

    lines: list[str] = [
        "# API Request/Response Test Report",
        "",
        f"Generated at UTC: `{generated_at}`",
        "",
        f"Base URL used in report: `{BASE_URL}`",
        "",
        "Scope:",
        "",
        "- This report was generated by calling the FastAPI app with a temporary isolated SQLite database.",
        f"- Main CRUD test employee: `{TEST_EMPLOYEE_CODE}` / `{TEST_EMPLOYEE_NAME}`.",
        "- Middleware and agent auth headers were sent, but secret values are masked in this report.",
        "- Direct machine SDK endpoints were tested with safe test doubles, not the physical biometric machine.",
        "- Use this report as the request/response contract for web-HRMS integration. Real-device testing is still required for SDK behavior.",
        "",
    ]
    for index, record in enumerate(records, start=1):
        response = record["response"]
        lines.extend(
            [
                f"## {index}. {record['name']}",
                "",
                f"Method: `{record['method']}`",
                "",
                f"URL: `{record['url']}`",
                "",
                f"Status: `{response['status_code']}`",
                "",
            ]
        )
        if record.get("note"):
            lines.extend(["Note:", "", record["note"], ""])
        lines.extend(["Request headers:", "", "```json", _pretty(record["headers"]), "```", ""])
        if record["query"]:
            lines.extend(["Query:", "", "```json", _pretty(record["query"]), "```", ""])
        if record["json"] is not None:
            lines.extend(["Request JSON:", "", "```json", _pretty(record["json"]), "```", ""])
        if record["content"] is not None:
            lines.extend(["Request body/content:", "", "```text", str(record["content"]), "```", ""])
        lines.extend(["Response:", "", "```json", _pretty(response["body"]), "```", ""])
    MARKDOWN_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    _install_machine_test_doubles()
    with tempfile.TemporaryDirectory(prefix="hrms_api_report_") as tmp:
        settings = Settings(
            env="test-report",
            db_url=f"sqlite:///{Path(tmp) / 'api-report.db'}",
            log_level="WARNING",
            outbound_url="https://hrms.example.com/api/attendance",
            outbound_api_key="test-outbound-key",
            middleware_api_key="dev-middleware-key",
            middleware_bearer_token="dev-middleware-token",
            agent_api_key="dev-agent-key",
            agent_jwt_token="dev-agent-jwt",
            webhook_hmac_secret="test-webhook-secret",
            webhook_timeout_seconds=1,
            machine_sync_ip="192.168.1.19",
            machine_sync_port=5005,
            machine_sync_password=0,
            machine_sync_machine_number=1,
        )
        app = create_ingress_app(settings)
        mw_headers = {"x-api-key": settings.middleware_api_key, "Content-Type": "application/json"}
        agent_headers = {
            "x-api-key": settings.agent_api_key,
            "Authorization": f"Bearer {settings.agent_jwt_token}",
            "Content-Type": "application/json",
        }
        machine_body = {"device_id": "DEV-LIVE-01"}
        records: list[dict[str, Any]] = []

        with TestClient(app, base_url=BASE_URL) as client:
            _call(client=client, records=records, name="Health check", method="GET", path="/health")
            _call(client=client, records=records, name="Middleware health", method="GET", path="/api/v1/health")
            _call(
                client=client,
                records=records,
                name="Create/update device",
                method="POST",
                path="/api/v1/devices",
                headers=mw_headers,
                json_body={
                    "device_id": "DEV-LIVE-01",
                    "device_name": "Main Gate Reader",
                    "site_id": "HQ",
                    "ip": "192.168.1.19",
                    "port": 5005,
                    "machine_number": 1,
                    "timezone": "Asia/Kolkata",
                    "is_active": True,
                    "sdk_protocol": "sbxpc_tcp",
                    "machine_password": "0",
                },
            )
            _call(client=client, records=records, name="List devices", method="GET", path="/api/v1/devices", headers=mw_headers)
            _call(
                client=client,
                records=records,
                name="Patch device",
                method="PATCH",
                path="/api/v1/devices/DEV-LIVE-01",
                headers=mw_headers,
                json_body={"device_name": "Main Gate Reader Updated", "machine_number": 1, "is_active": True},
            )

            for slug, endpoint, command_type in [
                ("Queue device test connection", "test-connection", "device.test_connection"),
                ("Queue device sync time", "sync-time", "device.sync_time"),
                ("Queue device sync employees", "sync-employees", "employee.sync_bulk"),
                ("Queue device XML execute", "xml/execute", "device.xml.execute"),
                ("Queue device employee enable", f"employees/{TEST_EMPLOYEE_CODE}/enable", "employee.enable"),
                ("Queue device employee disable", f"employees/{TEST_EMPLOYEE_CODE}/disable", "employee.disable"),
            ]:
                _call(
                    client=client,
                    records=records,
                    name=slug,
                    method="POST",
                    path=f"/api/v1/devices/DEV-LIVE-01/{endpoint}",
                    headers=mw_headers,
                    json_body={"request_id": f"req-{endpoint.replace('/', '-')}", "payload": {"command_type": command_type}, "priority": 100},
                )

            _call(
                client=client,
                records=records,
                name="Create employee CRUD sample",
                method="POST",
                path="/api/v1/employees",
                headers=mw_headers,
                json_body={
                    "employee_code": TEST_EMPLOYEE_CODE,
                    "employee_name": TEST_EMPLOYEE_NAME,
                    "card_no": TEST_EMPLOYEE_CARD,
                    "department": "IT",
                    "designation": "Engineer",
                    "branch_name": "HQ",
                    "machine": {"sync_to_machine": False},
                },
            )
            _call(
                client=client,
                records=records,
                name="Create employee and sync to machine sample",
                method="POST",
                path="/api/v1/employees",
                headers=mw_headers,
                json_body={
                    "employee_code": "236",
                    "employee_name": "TESTING-SYNC-001",
                    "card_no": "236",
                    "department": "IT",
                    "designation": "Engineer",
                    "branch_name": "HQ",
                    "machine": {
                        "sync_to_machine": True,
                        "device_id": "DEV-LIVE-01",
                        "user_id": 236,
                        "user_name": "TESTING-SYNC-001",
                        "card_no": "236",
                        "enable": True,
                    },
                },
                note="Machine SDK work is simulated in this report.",
            )
            _call(
                client=client,
                records=records,
                name="List employees",
                method="GET",
                path="/api/v1/employees",
                headers=mw_headers,
                params={"employee_code": TEST_EMPLOYEE_CODE, "department": "IT", "limit": 500},
            )
            _call(
                client=client,
                records=records,
                name="Get employee CRUD sample",
                method="GET",
                path=f"/api/v1/employees/{TEST_EMPLOYEE_CODE}",
                headers=mw_headers,
            )
            _call(
                client=client,
                records=records,
                name="Patch employee CRUD sample",
                method="PATCH",
                path=f"/api/v1/employees/{TEST_EMPLOYEE_CODE}",
                headers=mw_headers,
                json_body={
                    "employee_name": f"{TEST_EMPLOYEE_NAME}-UPDATED",
                    "designation": "Senior Engineer",
                    "phone_no": "9999999999",
                },
            )

            _call(client=client, records=records, name="List master types", method="GET", path="/api/v1/master/types", headers=mw_headers)
            _call(
                client=client,
                records=records,
                name="Create master department",
                method="POST",
                path="/api/v1/master/departments",
                headers=mw_headers,
                json_body={"code": "D001", "name": "Operations", "description": "Factory operations team", "is_active": True},
            )
            _call(
                client=client,
                records=records,
                name="List master departments",
                method="GET",
                path="/api/v1/master/departments",
                headers=mw_headers,
                params={"is_active": True, "limit": 500},
            )
            _call(
                client=client,
                records=records,
                name="Get master department",
                method="GET",
                path="/api/v1/master/departments/D001",
                headers=mw_headers,
            )
            _call(
                client=client,
                records=records,
                name="Patch master department",
                method="PATCH",
                path="/api/v1/master/departments/D001",
                headers=mw_headers,
                json_body={"name": "Operations Updated", "is_active": True},
            )

            _call(
                client=client,
                records=records,
                name="Realtime machine punch ingest",
                method="POST",
                path="/machine/realtime_glog",
                headers={"request_code": "realtime_glog"},
                content=b"user_id=E1023\tio_time=20260501184510\tdev_id=SN-REPORT-01\n",
                note="This endpoint accepts machine raw form/text content, not normal JSON.",
            )
            _call(
                client=client,
                records=records,
                name="Legacy attendance list",
                method="GET",
                path="/api/attendances",
                params={"limit": 200},
            )

            _call(
                client=client,
                records=records,
                name="Agent heartbeat",
                method="POST",
                path="/api/v1/agent/heartbeat",
                headers=agent_headers,
                json_body={
                    "agent_id": "AGENT_PLANT_A",
                    "site_id": "HQ",
                    "version": "1.0.0",
                    "host_name": "PC-REPORT-01",
                    "local_ip": "192.168.1.10",
                    "details": {"os": "Windows"},
                },
            )
            _call(
                client=client,
                records=records,
                name="Agent device status",
                method="POST",
                path="/api/v1/agent/device-status",
                headers=agent_headers,
                json_body={
                    "device_id": "DEV-LIVE-01",
                    "device_name": "Main Gate Reader",
                    "site_id": "HQ",
                    "ip": "192.168.1.19",
                    "port": 5005,
                    "machine_number": 1,
                    "timezone": "Asia/Kolkata",
                    "is_active": True,
                    "sdk_protocol": "sbxpc_tcp",
                    "machine_password": "0",
                },
            )
            _call(
                client=client,
                records=records,
                name="Agent attendance batch",
                method="POST",
                path="/api/v1/agent/attendance/batch",
                headers=agent_headers,
                json_body={
                    "agent_id": "AGENT_PLANT_A",
                    "events": [
                        {
                            "event_id": "evt-report-001",
                            "employee_code": TEST_EMPLOYEE_CODE,
                            "machine_user_id": TEST_EMPLOYEE_CODE,
                            "device_id": "DEV-LIVE-01",
                            "device_ip": "192.168.1.19",
                            "timestamp_local": "2026-05-09 09:30:00",
                            "timestamp_utc": "2026-05-09T04:00:00Z",
                            "timezone": "Asia/Kolkata",
                            "verification_mode": "fingerprint",
                            "source": "pull_sdk",
                            "raw_payload": {},
                            "idempotency_key": "DEV-LIVE-01:235:2026-05-09T04:00:00Z",
                        }
                    ],
                },
            )
            _call(client=client, records=records, name="List attendance events", method="GET", path="/api/v1/attendance", headers=mw_headers)

            command_response = _call(
                client=client,
                records=records,
                name="Create command",
                method="POST",
                path="/api/v1/commands",
                headers=mw_headers,
                json_body={
                    "request_id": "req-command-001",
                    "device_id": "DEV-LIVE-01",
                    "command_type": "employee.enable",
                    "payload": {"employee_code": TEST_EMPLOYEE_CODE},
                    "priority": 50,
                },
            )
            command_id = command_response.get("command_id") if isinstance(command_response, dict) else None
            _call(
                client=client,
                records=records,
                name="List commands",
                method="GET",
                path="/api/v1/commands",
                headers=mw_headers,
                params={"device_id": "DEV-LIVE-01", "limit": 100},
            )
            if command_id:
                _call(
                    client=client,
                    records=records,
                    name="Get command",
                    method="GET",
                    path=f"/api/v1/commands/{command_id}",
                    headers=mw_headers,
                )
            claim_response = _call(
                client=client,
                records=records,
                name="Agent claim commands",
                method="POST",
                path="/api/v1/agent/commands/claim",
                headers=agent_headers,
                json_body={"agent_id": "AGENT_PLANT_A", "device_ids": ["DEV-LIVE-01"], "limit": 10},
            )
            claimed_rows = claim_response.get("rows", []) if isinstance(claim_response, dict) else []
            claimed_command_id = claimed_rows[0].get("command_id") if claimed_rows else command_id
            if claimed_command_id:
                _call(
                    client=client,
                    records=records,
                    name="Agent command result",
                    method="POST",
                    path=f"/api/v1/agent/commands/{claimed_command_id}/result",
                    headers=agent_headers,
                    json_body={
                        "agent_id": "AGENT_PLANT_A",
                        "success": True,
                        "error_code": None,
                        "error_message": None,
                        "result_payload": {"applied": True},
                    },
                )

            _call(
                client=client,
                records=records,
                name="Create webhook subscription",
                method="POST",
                path="/api/v1/webhooks/subscriptions",
                headers=mw_headers,
                json_body={
                    "subscription_id": "sub-report-001",
                    "event_type": "attendance.created",
                    "target_url": "https://hrms.example.com/webhook/attendance",
                    "is_active": True,
                },
            )
            _call(client=client, records=records, name="List webhook subscriptions", method="GET", path="/api/v1/webhooks/subscriptions", headers=mw_headers)
            _call(
                client=client,
                records=records,
                name="Enqueue webhook event",
                method="POST",
                path="/api/v1/webhooks/events/attendance.created",
                headers=mw_headers,
                json_body={"event_id": "evt-webhook-report-001", "payload": {"employee_code": TEST_EMPLOYEE_CODE}},
            )
            deliveries_response = _call(
                client=client,
                records=records,
                name="List webhook deliveries",
                method="GET",
                path="/api/v1/webhooks/deliveries",
                headers=mw_headers,
                params={"limit": 100},
            )
            _call(
                client=client,
                records=records,
                name="Dispatch webhooks",
                method="POST",
                path="/api/v1/webhooks/dispatch",
                headers=mw_headers,
                json_body={"limit": 50},
                note="Network dispatch is simulated in this report.",
            )
            delivery_rows = deliveries_response.get("rows", []) if isinstance(deliveries_response, dict) else []
            delivery_id = delivery_rows[0].get("delivery_id") if delivery_rows else None
            if delivery_id:
                _call(
                    client=client,
                    records=records,
                    name="Retry webhook delivery",
                    method="POST",
                    path=f"/api/v1/webhooks/retry/{delivery_id}",
                    headers=mw_headers,
                )

            _call(client=client, records=records, name="Machine test connection", method="POST", path="/api/machine/test-connection", headers=mw_headers, json_body=machine_body, note="Machine SDK work is simulated in this report.")
            _call(client=client, records=records, name="Machine device details", method="POST", path="/api/machine/device/details", headers=mw_headers, json_body={**machine_body, "include_user_count": True}, note="Machine SDK work is simulated in this report.")
            _call(client=client, records=records, name="Machine time read", method="POST", path="/api/machine/time/read", headers=mw_headers, json_body=machine_body, note="Machine SDK work is simulated in this report.")
            _call(client=client, records=records, name="Machine time set", method="POST", path="/api/machine/time/set", headers=mw_headers, json_body={**machine_body, "device_time": "2026-05-09 10:30:00"}, note="Machine SDK work is simulated in this report.")
            _call(client=client, records=records, name="Machine general logs read", method="POST", path="/api/machine/logs/general/read", headers=mw_headers, json_body={**machine_body, "limit": 200}, note="Machine SDK work is simulated in this report.")
            _call(client=client, records=records, name="Machine capabilities probe", method="POST", path="/api/machine/capabilities/probe", headers=mw_headers, json_body={**machine_body, "include_log_read_test": True, "log_read_limit": 1}, note="Machine SDK work is simulated in this report.")
            _call(
                client=client,
                records=records,
                name="Machine XML execute",
                method="POST",
                path="/api/machine/xml/execute",
                headers=mw_headers,
                json_body={
                    **machine_body,
                    "request_name": "GetDeviceInfo",
                    "msg_type": "request",
                    "include_machine_id": True,
                    "fields": [{"tag": "SomeTag", "value": "SomeValue", "value_type": "string"}],
                    "parse_fields": [{"tag": "Result", "value_type": "string"}],
                    "return_request_xml": False,
                    "return_response_xml": True,
                },
                note="Machine SDK work is simulated in this report.",
            )
            _call(
                client=client,
                records=records,
                name="Machine employees sync dry run",
                method="POST",
                path="/api/machine/employees/sync",
                headers=mw_headers,
                json_body={**machine_body, "dry_run": True, "employee_code": TEST_EMPLOYEE_CODE, "limit": 2000},
            )
            _call(client=client, records=records, name="Machine employees read all", method="POST", path="/api/machine/employees/read-all", headers=mw_headers, json_body={**machine_body, "include_user_names": True}, note="Machine SDK work is simulated in this report.")
            _call(
                client=client,
                records=records,
                name="Machine update employee CRUD sample",
                method="PUT",
                path=f"/api/machine/employees/{TEST_EMPLOYEE_CODE}",
                headers=mw_headers,
                json_body={
                    **machine_body,
                    "user_id": 235,
                    "user_name": TEST_EMPLOYEE_NAME,
                    "card_no": TEST_EMPLOYEE_CARD,
                    "timezone1": 1,
                    "timezone2": 0,
                    "group_no": 1,
                    "enable": True,
                },
                note="Machine SDK work is simulated in this report.",
            )
            _call(
                client=client,
                records=records,
                name="Machine read employee CRUD sample",
                method="POST",
                path=f"/api/machine/employees/{TEST_EMPLOYEE_CODE}/read",
                headers=mw_headers,
                json_body={**machine_body, "user_id": 235, "include_user_name": True},
                note="Machine SDK work is simulated in this report.",
            )
            _call(
                client=client,
                records=records,
                name="Machine enable employee CRUD sample",
                method="POST",
                path=f"/api/machine/employees/{TEST_EMPLOYEE_CODE}/enable",
                headers=mw_headers,
                json_body={**machine_body, "user_id": 235, "all_slots": True},
                note="Machine SDK work is simulated in this report.",
            )
            _call(
                client=client,
                records=records,
                name="Machine disable employee CRUD sample",
                method="POST",
                path=f"/api/machine/employees/{TEST_EMPLOYEE_CODE}/disable",
                headers=mw_headers,
                json_body={**machine_body, "user_id": 235, "all_slots": True},
                note="Machine SDK work is simulated in this report.",
            )
            _call(
                client=client,
                records=records,
                name="Machine delete employee CRUD sample",
                method="DELETE",
                path=f"/api/machine/employees/{TEST_EMPLOYEE_CODE}",
                headers=mw_headers,
                json_body={**machine_body, "user_id": 235, "all_slots": True},
                note="Machine SDK work is simulated in this report.",
            )
            _call(
                client=client,
                records=records,
                name="Queue device employee delete",
                method="DELETE",
                path=f"/api/v1/devices/DEV-LIVE-01/employees/{TEST_EMPLOYEE_CODE}",
                headers=mw_headers,
                json_body={"request_id": "req-device-delete", "payload": {"employee_code": TEST_EMPLOYEE_CODE}, "priority": 100},
            )
            _call(client=client, records=records, name="Delete master department", method="DELETE", path="/api/v1/master/departments/D001", headers=mw_headers)
            _call(
                client=client,
                records=records,
                name="Delete employee CRUD sample",
                method="DELETE",
                path=f"/api/v1/employees/{TEST_EMPLOYEE_CODE}",
                headers=mw_headers,
            )

        _write_reports(records, settings=settings)
        print(f"Wrote {MARKDOWN_REPORT}")
        print(f"Wrote {JSON_REPORT}")
        print(f"Recorded {len(records)} API calls")


if __name__ == "__main__":
    main()
