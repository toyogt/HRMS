from __future__ import annotations

import logging
import inspect
import uuid
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from attendance_relay.dashboard import (
    render_dashboard_html,
    render_device_admin_dashboard_html,
    render_employee_dashboard_html,
)
from attendance_relay.db import create_db_engine, init_local_schema, is_sqlite
from attendance_relay.decoder import DecodeError, decode_machine_payload
from attendance_relay.hashing import build_event_hash
from attendance_relay.logging_utils import configure_logging, log_event
from attendance_relay.middleware_models import (
    AgentAttendanceBatchRequest,
    AgentHeartbeatRequest,
    CommandClaimRequest,
    CommandCreateRequest,
    CommandResultRequest,
    DevicePatchRequest,
    DeviceScopedCommandRequest,
    DeviceUpsertRequest,
    EmployeeCreateRequest,
    EmployeePatchRequest,
    MasterDataCreateRequest,
    MasterDataPatchRequest,
    WebhookDispatchRequest,
    WebhookEventRequest,
    WebhookSubscriptionRequest,
)
from attendance_relay.middleware_repository import MiddlewareRepository
from attendance_relay.machine_admin import (
    MachineCapabilitiesProbeRequest,
    MachineConnectionRequest,
    MachineDeviceDetailsRequest,
    MachineEmployeeDeleteRequest,
    MachineEmployeeListRequest,
    MachineEmployeeReadRequest,
    MachineEmployeeToggleRequest,
    MachineEmployeeUpdateRequest,
    MachineGeneralLogsReadRequest,
    MachineXmlExecuteRequest,
    MachineSdkError,
    MachineSyncRequest,
    MachineTimeReadRequest,
    MachineTimeSetRequest,
    build_machine_sync_preview,
    check_machine_connection,
    create_employee_on_machine,
    delete_employee_on_machine,
    get_employee_on_machine,
    get_machine_device_details,
    list_employees_on_machine,
    probe_machine_capabilities,
    read_machine_general_logs,
    read_machine_time,
    run_machine_xml_execute,
    run_machine_sync_from_api,
    set_machine_time,
    toggle_employee_on_machine,
    update_employee_on_machine,
)
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings
from attendance_relay.time_utils import format_datetime, now_local
from attendance_relay.webhook_dispatcher import dispatch_due_webhooks


LOGGER = logging.getLogger("attendance_relay.ingress")


def create_ingress_app(settings: Settings) -> FastAPI:
    configure_logging(settings.log_level)
    engine = create_db_engine(settings)
    if is_sqlite(engine):
        init_local_schema(engine)
    repo = AttendanceRepository(engine)
    middleware_repo = MiddlewareRepository(engine)

    app = FastAPI(title="Attendance Ingestion Service", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "x-api-key", "request_code"],
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.repo = repo
    app.state.middleware_repo = middleware_repo

    def _unauthorized(message: str) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=401)

    def _require_middleware_auth(request: Request) -> JSONResponse | None:
        api_key = (request.headers.get("x-api-key") or "").strip()
        authz = (request.headers.get("authorization") or "").strip()
        bearer = authz.removeprefix("Bearer ").strip() if authz.lower().startswith("bearer ") else ""
        api_key_ok = api_key == settings.middleware_api_key
        bearer_ok = bool(settings.middleware_bearer_token) and bearer == settings.middleware_bearer_token
        if not api_key_ok and not bearer_ok:
            return _unauthorized("invalid middleware api key")
        return None

    def _require_agent_auth(request: Request) -> JSONResponse | None:
        api_key = (request.headers.get("x-api-key") or "").strip()
        if api_key != settings.agent_api_key:
            return _unauthorized("invalid agent api key")
        authz = (request.headers.get("authorization") or "").strip()
        token = authz.removeprefix("Bearer ").strip() if authz.lower().startswith("bearer ") else ""
        if settings.agent_jwt_token and token != settings.agent_jwt_token:
            return _unauthorized("invalid agent jwt token")
        return None

    def _call_machine_helper(helper: Any, **kwargs: Any) -> Any:
        if "device_resolver" in kwargs:
            signature = inspect.signature(helper)
            accepts_kwargs = any(
                param.kind == inspect.Parameter.VAR_KEYWORD
                for param in signature.parameters.values()
            )
            if not accepts_kwargs and "device_resolver" not in signature.parameters:
                kwargs.pop("device_resolver")
        return helper(**kwargs)

    @app.get("/health")
    async def health() -> JSONResponse:
        counts = repo.get_outbox_counts()
        return JSONResponse(
            {
                "status": "ok",
                "env": settings.env,
                "db_dialect": engine.dialect.name,
                "outbox": counts,
            }
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(
        employee_code: str | None = None,
        device_sn: str | None = None,
        limit: int = Query(default=200, ge=1, le=5000),
    ) -> HTMLResponse:
        employee_filter = (employee_code or "").strip() or None
        device_filter = (device_sn or "").strip() or None
        rows = repo.list_attendance(limit=limit, employee_code=employee_filter, device_sn=device_filter)
        total = repo.get_attendance_total()
        refreshed_at = format_datetime(now_local(settings.tz_name))
        html = render_dashboard_html(
            rows=rows,
            total=total,
            employee_code_filter=employee_filter,
            device_sn_filter=device_filter,
            limit=limit,
            refreshed_at=refreshed_at,
        )
        return HTMLResponse(content=html, status_code=200)

    @app.get("/dashboard/employees", response_class=HTMLResponse)
    async def employee_dashboard(
        employee_code: str | None = None,
        department: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> HTMLResponse:
        employee_filter = (employee_code or "").strip() or None
        department_filter = (department or "").strip() or None
        rows = repo.list_employee_master(
            employee_code=employee_filter,
            department=department_filter,
            limit=limit,
        )
        refreshed_at = format_datetime(now_local(settings.tz_name))
        html = render_employee_dashboard_html(
            rows=rows,
            total=len(rows),
            employee_code_filter=employee_filter,
            department_filter=department_filter,
            limit=limit,
            refreshed_at=refreshed_at,
        )
        return HTMLResponse(content=html, status_code=200)

    @app.get("/dashboard/admin", response_class=HTMLResponse)
    async def admin_device_dashboard(
        message: str | None = None,
        error: str | None = None,
    ) -> HTMLResponse:
        rows = middleware_repo.list_devices()
        refreshed_at = format_datetime(now_local(settings.tz_name))
        html = render_device_admin_dashboard_html(
            rows=rows,
            refreshed_at=refreshed_at,
            message=(message or None),
            error=(error or None),
        )
        return HTMLResponse(content=html, status_code=200)

    @app.post("/dashboard/admin/devices/save")
    async def admin_save_device(request: Request) -> Response:
        raw_body = (await request.body()).decode("utf-8", errors="ignore")
        form = parse_qs(raw_body, keep_blank_values=True)

        def _field(name: str, default: str = "") -> str:
            return str((form.get(name) or [default])[0]).strip()

        port_text = _field("port", "5005")
        try:
            parsed_port = int(port_text or "5005")
        except ValueError:
            parsed_port = -1
        machine_number_text = _field("machine_number", "1")
        try:
            parsed_machine_number = int(machine_number_text or "1")
        except ValueError:
            parsed_machine_number = -1

        payload = {
            "device_id": _field("device_id"),
            "device_name": _field("device_name"),
            "site_id": _field("site_id"),
            "ip": _field("ip"),
            "port": parsed_port,
            "machine_number": parsed_machine_number,
            "timezone": _field("timezone", "Asia/Kolkata") or "Asia/Kolkata",
            "is_active": "is_active" in form,
            "machine_password": _field("machine_password"),
        }
        try:
            middleware_repo.upsert_device(payload)
        except ValueError as exc:
            rows = middleware_repo.list_devices()
            refreshed_at = format_datetime(now_local(settings.tz_name))
            html = render_device_admin_dashboard_html(
                rows=rows,
                refreshed_at=refreshed_at,
                error=str(exc),
            )
            return HTMLResponse(content=html, status_code=400)
        return RedirectResponse(url="/dashboard/admin?message=Device%20configuration%20saved", status_code=303)

    @app.get("/api/attendances")
    async def attendances_api(
        employee_code: str | None = None,
        device_sn: str | None = None,
        limit: int = Query(default=200, ge=1, le=5000),
    ) -> JSONResponse:
        employee_filter = (employee_code or "").strip() or None
        device_filter = (device_sn or "").strip() or None
        rows = repo.list_attendance(limit=limit, employee_code=employee_filter, device_sn=device_filter)
        return JSONResponse(
            {
                "total": repo.get_attendance_total(),
                "loaded": len(rows),
                "filters": {
                    "employee_code": employee_filter,
                    "device_sn": device_filter,
                    "limit": limit,
                },
                "rows": rows,
            }
        )

    @app.get("/api/v1/health")
    async def middleware_health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "env": settings.env,
                "db_dialect": engine.dialect.name,
                "counts": middleware_repo.get_middleware_counts(),
            }
        )

    @app.post("/api/v1/devices")
    async def create_device(request: Request, payload: DeviceUpsertRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            device = middleware_repo.upsert_device(payload.model_dump())
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(device, status_code=201)

    @app.get("/api/v1/devices")
    async def list_devices(request: Request) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        return JSONResponse({"rows": middleware_repo.list_devices()}, status_code=200)

    @app.patch("/api/v1/devices/{device_id}")
    async def patch_device(device_id: str, request: Request, payload: DevicePatchRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            patched = middleware_repo.patch_device(device_id, payload.model_dump(exclude_none=True))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return JSONResponse(patched, status_code=200)

    def _create_device_command_job(
        *,
        device_id: str,
        command_type: str,
        request_id: str,
        payload_data: dict[str, Any],
        priority: int,
    ) -> dict[str, Any]:
        return middleware_repo.create_command(
            request_id=request_id,
            device_id=device_id,
            command_type=command_type,
            payload=payload_data,
            priority=priority,
        )

    @app.post("/api/v1/devices/{device_id}/test-connection")
    async def queue_test_connection(
        device_id: str,
        request: Request,
        payload: DeviceScopedCommandRequest,
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            command = _create_device_command_job(
                device_id=device_id,
                command_type="device.test_connection",
                request_id=payload.request_id,
                payload_data=payload.payload,
                priority=payload.priority,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(command, status_code=202)

    @app.post("/api/v1/devices/{device_id}/sync-time")
    async def queue_sync_time(device_id: str, request: Request, payload: DeviceScopedCommandRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            command = _create_device_command_job(
                device_id=device_id,
                command_type="device.sync_time",
                request_id=payload.request_id,
                payload_data=payload.payload,
                priority=payload.priority,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(command, status_code=202)

    @app.post("/api/v1/devices/{device_id}/sync-employees")
    async def queue_sync_employees(
        device_id: str,
        request: Request,
        payload: DeviceScopedCommandRequest,
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            command = _create_device_command_job(
                device_id=device_id,
                command_type="employee.sync_bulk",
                request_id=payload.request_id,
                payload_data=payload.payload,
                priority=payload.priority,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(command, status_code=202)

    @app.post("/api/v1/devices/{device_id}/xml/execute")
    async def queue_xml_execute(
        device_id: str,
        request: Request,
        payload: DeviceScopedCommandRequest,
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            command = _create_device_command_job(
                device_id=device_id,
                command_type="device.xml.execute",
                request_id=payload.request_id,
                payload_data=payload.payload,
                priority=payload.priority,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(command, status_code=202)

    @app.post("/api/v1/employees")
    async def upsert_employee(request: Request, payload: EmployeeCreateRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        row = payload.model_dump(exclude={"machine"})
        row["employee_code"] = (row.get("employee_code") or "").strip()
        if not row["employee_code"]:
            return JSONResponse({"error": "employee_code is required"}, status_code=400)
        summary = repo.upsert_employee_master_records([row])
        employee = repo.find_employee_master(row["employee_code"])

        response: dict[str, Any] = {"summary": summary, "employee": employee}
        machine = payload.machine
        if machine and machine.sync_to_machine:
            try:
                machine_request = MachineEmployeeUpdateRequest(
                    **machine.model_dump(exclude={"sync_to_machine"}, exclude_none=True)
                )
                machine_result = _call_machine_helper(
                    create_employee_on_machine,
                    repo=repo,
                    settings=settings,
                    employee_code=row["employee_code"],
                    request=machine_request,
                    device_resolver=middleware_repo.get_device,
                )
            except ValueError as exc:
                response["machine_sync"] = {
                    "requested": True,
                    "success": False,
                    "error": str(exc),
                }
                return JSONResponse(response, status_code=400)
            except MachineSdkError as exc:
                response["machine_sync"] = {
                    "requested": True,
                    "success": False,
                    "error": str(exc),
                }
                return JSONResponse(response, status_code=502)

            response["machine_sync"] = {
                "requested": True,
                "success": True,
                "result": machine_result,
            }
        else:
            response["machine_sync"] = {
                "requested": False,
                "success": None,
            }
        return JSONResponse(response, status_code=201)

    @app.get("/api/v1/employees")
    async def list_employees(
        request: Request,
        employee_code: str | None = None,
        department: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        rows = repo.list_employee_master(
            employee_code=(employee_code or None),
            department=(department or None),
            limit=limit,
        )
        return JSONResponse(
            {
                "loaded": len(rows),
                "filters": {
                    "employee_code": (employee_code or None),
                    "department": (department or None),
                    "limit": limit,
                },
                "rows": rows,
            },
            status_code=200,
        )

    @app.get("/api/v1/employees/{employee_code}")
    async def get_employee(employee_code: str, request: Request) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        employee = repo.find_employee_master(employee_code)
        if not employee:
            return JSONResponse({"error": f"employee_code not found: {employee_code}"}, status_code=404)
        return JSONResponse(employee, status_code=200)

    @app.patch("/api/v1/employees/{employee_code}")
    async def patch_employee(employee_code: str, request: Request, payload: EmployeePatchRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        current = repo.find_employee_master(employee_code)
        if not current:
            return JSONResponse({"error": f"employee_code not found: {employee_code}"}, status_code=404)
        patch = payload.model_dump(exclude_none=True)
        merged = {**current, **patch}
        merged["employee_code"] = employee_code
        summary = repo.upsert_employee_master_records([merged])
        employee = repo.find_employee_master(employee_code)
        return JSONResponse({"summary": summary, "employee": employee}, status_code=200)

    @app.delete("/api/v1/employees/{employee_code}")
    async def delete_employee(employee_code: str, request: Request) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        removed = repo.delete_employee_master(employee_code)
        if not removed:
            return JSONResponse({"error": f"employee_code not found: {employee_code}"}, status_code=404)
        return JSONResponse({"deleted": True, "employee_code": employee_code}, status_code=200)

    @app.get("/api/v1/master/types")
    async def list_master_types(request: Request) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        return JSONResponse({"rows": repo.get_supported_master_types()}, status_code=200)

    @app.post("/api/v1/master/{master_type}")
    async def create_master_value(
        master_type: str,
        request: Request,
        payload: MasterDataCreateRequest,
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            row = repo.upsert_master_value(
                master_type=master_type,
                code=payload.code,
                name=payload.name,
                description=payload.description,
                is_active=payload.is_active,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        status_code = 201 if row.get("action") == "created" else 200
        return JSONResponse({"master_type": master_type, "row": row}, status_code=status_code)

    @app.get("/api/v1/master/{master_type}")
    async def list_master_values(
        master_type: str,
        request: Request,
        is_active: bool | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            rows = repo.list_master_values(master_type=master_type, is_active=is_active, limit=limit)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            {
                "master_type": master_type,
                "loaded": len(rows),
                "filters": {"is_active": is_active, "limit": limit},
                "rows": rows,
            },
            status_code=200,
        )

    @app.get("/api/v1/master/{master_type}/{code}")
    async def get_master_value(master_type: str, code: str, request: Request) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            row = repo.find_master_value(master_type=master_type, code=code)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not row:
            return JSONResponse({"error": f"code not found: {code}"}, status_code=404)
        return JSONResponse({"master_type": master_type, "row": row}, status_code=200)

    @app.patch("/api/v1/master/{master_type}/{code}")
    async def patch_master_value(
        master_type: str,
        code: str,
        request: Request,
        payload: MasterDataPatchRequest,
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        patch = payload.model_dump(exclude_none=True)
        if not patch:
            return JSONResponse({"error": "at least one field is required"}, status_code=400)
        try:
            row = repo.patch_master_value(master_type=master_type, code=code, patch=patch)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not row:
            return JSONResponse({"error": f"code not found: {code}"}, status_code=404)
        return JSONResponse({"master_type": master_type, "row": row}, status_code=200)

    @app.delete("/api/v1/master/{master_type}/{code}")
    async def delete_master_value(master_type: str, code: str, request: Request) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            removed = repo.delete_master_value(master_type=master_type, code=code)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not removed:
            return JSONResponse({"error": f"code not found: {code}"}, status_code=404)
        return JSONResponse({"deleted": True, "master_type": master_type, "code": code}, status_code=200)

    @app.post("/api/v1/devices/{device_id}/employees/{employee_code}/enable")
    async def queue_enable_employee(
        device_id: str,
        employee_code: str,
        request: Request,
        payload: DeviceScopedCommandRequest,
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        cmd_payload = {**payload.payload, "employee_code": employee_code}
        command = _create_device_command_job(
            device_id=device_id,
            command_type="employee.enable",
            request_id=payload.request_id,
            payload_data=cmd_payload,
            priority=payload.priority,
        )
        return JSONResponse(command, status_code=202)

    @app.post("/api/v1/devices/{device_id}/employees/{employee_code}/disable")
    async def queue_disable_employee(
        device_id: str,
        employee_code: str,
        request: Request,
        payload: DeviceScopedCommandRequest,
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        cmd_payload = {**payload.payload, "employee_code": employee_code}
        command = _create_device_command_job(
            device_id=device_id,
            command_type="employee.disable",
            request_id=payload.request_id,
            payload_data=cmd_payload,
            priority=payload.priority,
        )
        return JSONResponse(command, status_code=202)

    @app.delete("/api/v1/devices/{device_id}/employees/{employee_code}")
    async def queue_delete_employee_from_device(
        device_id: str,
        employee_code: str,
        request: Request,
        payload: DeviceScopedCommandRequest,
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        cmd_payload = {**payload.payload, "employee_code": employee_code}
        command = _create_device_command_job(
            device_id=device_id,
            command_type="employee.delete",
            request_id=payload.request_id,
            payload_data=cmd_payload,
            priority=payload.priority,
        )
        return JSONResponse(command, status_code=202)

    @app.get("/api/v1/attendance")
    async def list_attendance_events(
        request: Request,
        device_id: str | None = None,
        employee_code: str | None = None,
        from_utc: str | None = None,
        to_utc: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        rows = middleware_repo.list_attendance_events(
            device_id=(device_id or None),
            employee_code=(employee_code or None),
            from_utc=(from_utc or None),
            to_utc=(to_utc or None),
            limit=limit,
        )
        return JSONResponse({"loaded": len(rows), "rows": rows}, status_code=200)

    @app.post("/api/v1/commands")
    async def create_command(request: Request, payload: CommandCreateRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            row = middleware_repo.create_command(
                request_id=payload.request_id,
                device_id=payload.device_id,
                command_type=payload.command_type,
                payload=payload.payload,
                priority=payload.priority,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(row, status_code=202)

    @app.get("/api/v1/commands")
    async def list_commands(
        request: Request,
        device_id: str | None = None,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        rows = middleware_repo.list_commands(device_id=(device_id or None), status=(status or None), limit=limit)
        return JSONResponse({"loaded": len(rows), "rows": rows}, status_code=200)

    @app.get("/api/v1/commands/{command_id}")
    async def get_command(command_id: str, request: Request) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            row = middleware_repo.get_command(command_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return JSONResponse(row, status_code=200)

    @app.post("/api/v1/webhooks/subscriptions")
    async def create_webhook_subscription(request: Request, payload: WebhookSubscriptionRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            row = middleware_repo.upsert_webhook_subscription(payload.model_dump())
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(row, status_code=201)

    @app.get("/api/v1/webhooks/subscriptions")
    async def list_webhook_subscriptions(request: Request) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        rows = middleware_repo.list_webhook_subscriptions()
        return JSONResponse({"rows": rows}, status_code=200)

    @app.get("/api/v1/webhooks/deliveries")
    async def list_webhook_deliveries(
        request: Request,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        rows = middleware_repo.list_webhook_deliveries(status=(status or None), limit=limit)
        return JSONResponse({"loaded": len(rows), "rows": rows}, status_code=200)

    @app.post("/api/v1/webhooks/dispatch")
    async def dispatch_webhooks(request: Request, payload: WebhookDispatchRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        result = dispatch_due_webhooks(settings=settings, repo=middleware_repo, limit=payload.limit)
        return JSONResponse(result, status_code=200)

    @app.post("/api/v1/webhooks/events/{event_type}")
    async def enqueue_custom_webhook_event(
        event_type: str,
        request: Request,
        payload: WebhookEventRequest,
    ) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        clean_event_type = str(event_type or "").strip()
        if not clean_event_type:
            return JSONResponse({"error": "event_type is required"}, status_code=400)
        event_id = str(payload.event_id or "").strip() or str(uuid.uuid4())
        deliveries = middleware_repo.enqueue_webhook_event(
            event_type=clean_event_type,
            event_id=event_id,
            payload=payload.payload,
        )
        return JSONResponse(
            {"event_type": clean_event_type, "event_id": event_id, "enqueued_deliveries": deliveries},
            status_code=202,
        )

    @app.post("/api/v1/webhooks/retry/{delivery_id}")
    async def retry_webhook_delivery(delivery_id: str, request: Request) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            row = middleware_repo.force_retry_webhook(delivery_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return JSONResponse(row, status_code=200)

    @app.post("/api/v1/agent/heartbeat")
    async def agent_heartbeat(request: Request, payload: AgentHeartbeatRequest) -> JSONResponse:
        denied = _require_agent_auth(request)
        if denied:
            return denied
        try:
            row = middleware_repo.record_agent_heartbeat(payload.model_dump())
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(row, status_code=200)

    @app.post("/api/v1/agent/attendance/batch")
    async def agent_attendance_batch(request: Request, payload: AgentAttendanceBatchRequest) -> JSONResponse:
        denied = _require_agent_auth(request)
        if denied:
            return denied
        result = middleware_repo.ingest_attendance_batch(
            agent_id=payload.agent_id,
            events=[row.model_dump() for row in payload.events],
        )
        return JSONResponse(result, status_code=200)

    @app.post("/api/v1/agent/commands/claim")
    async def agent_claim_commands(request: Request, payload: CommandClaimRequest) -> JSONResponse:
        denied = _require_agent_auth(request)
        if denied:
            return denied
        rows = middleware_repo.claim_commands(
            agent_id=payload.agent_id,
            device_ids=payload.device_ids,
            limit=payload.limit,
        )
        return JSONResponse({"loaded": len(rows), "rows": rows}, status_code=200)

    @app.post("/api/v1/agent/commands/{command_id}/result")
    async def agent_submit_result(command_id: str, request: Request, payload: CommandResultRequest) -> JSONResponse:
        denied = _require_agent_auth(request)
        if denied:
            return denied
        try:
            row = middleware_repo.submit_command_result(
                command_id=command_id,
                agent_id=payload.agent_id,
                success=payload.success,
                error_code=payload.error_code,
                error_message=payload.error_message,
                result_payload=payload.result_payload,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return JSONResponse(row, status_code=200)

    @app.post("/api/v1/agent/device-status")
    async def agent_device_status(request: Request, payload: DeviceUpsertRequest) -> JSONResponse:
        denied = _require_agent_auth(request)
        if denied:
            return denied
        try:
            row = middleware_repo.upsert_device(payload.model_dump())
            middleware_repo.mark_device_seen(
                row["device_id"],
                last_seen_at=format_datetime(now_local(settings.tz_name)),
                device_ip=str(row.get("ip") or ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"status": "updated", "device": middleware_repo.get_device(row["device_id"])}, status_code=200)

    @app.post("/api/machine/test-connection")
    async def machine_test_connection(request: Request, payload: MachineConnectionRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = check_machine_connection(
                settings=settings,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/device/details")
    async def machine_device_details(request: Request, payload: MachineDeviceDetailsRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = get_machine_device_details(
                settings=settings,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/time/read")
    async def machine_time_read(request: Request, payload: MachineTimeReadRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = read_machine_time(
                settings=settings,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/time/set")
    async def machine_time_set(request: Request, payload: MachineTimeSetRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = set_machine_time(
                settings=settings,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/logs/general/read")
    async def machine_read_general_logs(request: Request, payload: MachineGeneralLogsReadRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = read_machine_general_logs(
                settings=settings,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/capabilities/probe")
    async def machine_capabilities_probe(request: Request, payload: MachineCapabilitiesProbeRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = probe_machine_capabilities(
                settings=settings,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/xml/execute")
    async def machine_xml_execute(request: Request, payload: MachineXmlExecuteRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = run_machine_xml_execute(
                settings=settings,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/employees/sync")
    async def machine_sync_employees(request: Request, payload: MachineSyncRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            if payload.dry_run:
                result = build_machine_sync_preview(
                    repo=repo,
                    settings=settings,
                    request=payload,
                    device_resolver=middleware_repo.get_device,
                )
            else:
                result = run_machine_sync_from_api(
                    repo=repo,
                    settings=settings,
                    request=payload,
                    device_resolver=middleware_repo.get_device,
                )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/employees/read-all")
    async def machine_read_all_employees(request: Request, payload: MachineEmployeeListRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = _call_machine_helper(
                list_employees_on_machine,
                settings=settings,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.put("/api/machine/employees/{employee_code}")
    async def machine_update_employee(employee_code: str, request: Request, payload: MachineEmployeeUpdateRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = update_employee_on_machine(
                repo=repo,
                settings=settings,
                employee_code=employee_code,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/employees/{employee_code}/read")
    async def machine_read_employee(employee_code: str, request: Request, payload: MachineEmployeeReadRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = _call_machine_helper(
                get_employee_on_machine,
                repo=repo,
                settings=settings,
                employee_code=employee_code,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.delete("/api/machine/employees/{employee_code}")
    async def machine_delete_employee(employee_code: str, request: Request, payload: MachineEmployeeDeleteRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = _call_machine_helper(
                delete_employee_on_machine,
                repo=repo,
                settings=settings,
                employee_code=employee_code,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/employees/{employee_code}/enable")
    async def machine_enable_employee(employee_code: str, request: Request, payload: MachineEmployeeToggleRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = toggle_employee_on_machine(
                repo=repo,
                settings=settings,
                employee_code=employee_code,
                enabled=True,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post("/api/machine/employees/{employee_code}/disable")
    async def machine_disable_employee(employee_code: str, request: Request, payload: MachineEmployeeToggleRequest) -> JSONResponse:
        denied = _require_middleware_auth(request)
        if denied:
            return denied
        try:
            result = toggle_employee_on_machine(
                repo=repo,
                settings=settings,
                employee_code=employee_code,
                enabled=False,
                request=payload,
                device_resolver=middleware_repo.get_device,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @app.post(settings.ingress_path)
    async def ingest_realtime_glog(request: Request) -> Response:
        request_code = request.headers.get("request_code", "")
        if request_code != settings.expected_request_code:
            log_event(
                LOGGER,
                "warning",
                "invalid_request_code",
                request_code=request_code,
                expected=settings.expected_request_code,
            )
            return PlainTextResponse("invalid request_code", status_code=400)

        raw_body = await request.body()
        downloaded_at = now_local(settings.tz_name)

        try:
            punch = decode_machine_payload(
                raw_body=raw_body,
                downloaded_at=downloaded_at,
                source_ip=(request.client.host if request.client else None),
            )
        except DecodeError as exc:
            log_event(
                LOGGER,
                "error",
                "decode_failed",
                error=str(exc),
                source_ip=(request.client.host if request.client else None),
            )
            return PlainTextResponse("decode error", status_code=400)

        event_hash = build_event_hash(
            employee_code=punch.employee_code,
            log_datetime=format_datetime(punch.log_datetime),
            log_time=punch.log_time,
            device_sn=punch.device_sn,
        )

        _, deduped = repo.persist_punch(punch=punch, event_hash=event_hash, max_retries=settings.max_retries)

        if settings.auto_register_device_from_ingress:
            device_id = str(punch.device_sn or "").strip()
            source_ip = str(punch.source_ip or "").strip()
            if device_id and source_ip:
                try:
                    middleware_repo.upsert_device(
                        {
                            "device_id": device_id,
                            "device_name": device_id,
                            "site_id": "",
                            "ip": source_ip,
                            "port": settings.machine_sync_port,
                            "machine_number": settings.machine_sync_machine_number,
                            "timezone": settings.tz_name,
                            "is_active": True,
                            "sdk_protocol": "sbxpc_tcp",
                            "machine_password": str(settings.machine_sync_password),
                        }
                    )
                    middleware_repo.mark_device_seen(
                        device_id,
                        last_seen_at=format_datetime(downloaded_at),
                        device_ip=source_ip,
                    )
                except ValueError as exc:
                    log_event(
                        LOGGER,
                        "warning",
                        "auto_register_device_failed",
                        device_id=device_id,
                        source_ip=source_ip,
                        error=str(exc),
                    )

        log_event(
            LOGGER,
            "info",
            "punch_ingested",
            employee_code=punch.employee_code,
            device_sn=punch.device_sn,
            log_datetime=format_datetime(punch.log_datetime),
            deduped=deduped,
            event_hash=event_hash,
        )

        return PlainTextResponse(
            f"response_code={settings.machine_ok_response_code}",
            status_code=200,
            headers={"response_code": settings.machine_ok_response_code},
        )

    @app.on_event("shutdown")
    def shutdown() -> None:
        engine.dispose()

    return app
