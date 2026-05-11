from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from attendance_relay.time_utils import format_datetime


@dataclass(slots=True)
class CommandRetryPlan:
    status: str
    next_attempt_at: str | None


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _safe_json_load(text_value: str | None) -> Any:
    if not text_value:
        return None
    try:
        return json.loads(text_value)
    except json.JSONDecodeError:
        return None


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_any_datetime(raw: str) -> datetime:
    text_value = (raw or "").strip()
    if not text_value:
        raise ValueError("datetime value is empty")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(text_value, fmt)
            if fmt.endswith("Z"):
                return parsed.replace(tzinfo=UTC)
            return parsed
        except ValueError:
            continue
    try:
        parsed_iso = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid datetime: {raw}") from exc
    return parsed_iso


def _normalize_timestamp_utc(
    *,
    timestamp_local: str,
    timestamp_utc: str | None,
    timezone_name: str,
) -> str:
    if timestamp_utc:
        parsed = _parse_any_datetime(timestamp_utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return _utc_iso(parsed)

    local_dt = _parse_any_datetime(timestamp_local)
    if local_dt.tzinfo is None:
        from zoneinfo import ZoneInfo

        local_dt = local_dt.replace(tzinfo=ZoneInfo(timezone_name))
    return _utc_iso(local_dt)


def _as_bool(raw_value: Any) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, int):
        return raw_value != 0
    text_value = str(raw_value or "").strip().lower()
    return text_value in {"1", "true", "yes", "y", "on"}


def _build_retry_plan(retry_count: int, now_utc: datetime) -> CommandRetryPlan:
    # Retry sequence: 1m -> 5m -> 15m -> 1h, then dead-letter
    schedule_minutes = [1, 5, 15, 60]
    if retry_count >= len(schedule_minutes):
        return CommandRetryPlan(status="DEAD", next_attempt_at=None)
    next_eta = now_utc + timedelta(minutes=schedule_minutes[retry_count])
    return CommandRetryPlan(status="RETRY", next_attempt_at=_utc_iso(next_eta))


def _build_webhook_retry_plan(attempt_no: int, now_utc: datetime) -> CommandRetryPlan:
    # Same delivery policy requested for webhooks.
    schedule_minutes = [1, 5, 15, 60]
    if attempt_no >= len(schedule_minutes):
        return CommandRetryPlan(status="DEAD", next_attempt_at=None)
    next_eta = now_utc + timedelta(minutes=schedule_minutes[attempt_no])
    return CommandRetryPlan(status="RETRY", next_attempt_at=_utc_iso(next_eta))


class MiddlewareRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.is_sqlite = engine.dialect.name == "sqlite"

    def upsert_device(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = str(payload.get("device_id") or "").strip()
        if not device_id:
            raise ValueError("device_id is required")
        ip = str(payload.get("ip") or "").strip()
        if not ip:
            raise ValueError("ip is required")
        try:
            port = int(payload.get("port") or 5005)
        except (TypeError, ValueError) as exc:
            raise ValueError("port must be an integer") from exc
        if port < 1 or port > 65535:
            raise ValueError("port must be between 1 and 65535")
        try:
            machine_number = int(payload.get("machine_number") or 1)
        except (TypeError, ValueError) as exc:
            raise ValueError("machine_number must be an integer") from exc
        if machine_number < 1:
            raise ValueError("machine_number must be greater than or equal to 1")

        machine_password = str(payload.get("machine_password") or "").strip()
        if machine_password and not machine_password.isdigit():
            raise ValueError("machine_password must be numeric")

        now_s = format_datetime(datetime.now().replace(microsecond=0))
        params = {
            "device_id": device_id,
            "device_name": str(payload.get("device_name") or "").strip(),
            "site_id": str(payload.get("site_id") or "").strip(),
            "ip": ip,
            "port": port,
            "machine_number": machine_number,
            "timezone": str(payload.get("timezone") or "Asia/Kolkata").strip() or "Asia/Kolkata",
            "is_active": 1 if _as_bool(payload.get("is_active", True)) else 0,
            "sdk_protocol": str(payload.get("sdk_protocol") or "sbxpc_tcp").strip() or "sbxpc_tcp",
            "machine_password": machine_password,
            "updated_at": now_s,
            "created_at": now_s,
        }

        with self.engine.begin() as conn:
            updated = conn.execute(
                text(
                    """
                    UPDATE devices
                    SET device_name = :device_name,
                        site_id = :site_id,
                        ip = :ip,
                        port = :port,
                        machine_number = :machine_number,
                        timezone = :timezone,
                        is_active = :is_active,
                        sdk_protocol = :sdk_protocol,
                        machine_password = :machine_password,
                        updated_at = :updated_at
                    WHERE device_id = :device_id
                    """
                ),
                params,
            )
            if int(updated.rowcount or 0) == 0:
                conn.execute(
                    text(
                        """
                        INSERT INTO devices (
                          device_id, device_name, site_id, ip, port, machine_number, timezone, is_active,
                          sdk_protocol, machine_password, created_at, updated_at
                        ) VALUES (
                          :device_id, :device_name, :site_id, :ip, :port, :machine_number, :timezone, :is_active,
                          :sdk_protocol, :machine_password, :created_at, :updated_at
                        )
                        """
                    ),
                    params,
                )
        return self.get_device(device_id)

    def list_devices(self) -> list[dict[str, Any]]:
        query = text(
            """
            SELECT
              device_id,
              device_name,
              site_id,
              ip,
              port,
              machine_number,
              timezone,
              is_active,
              sdk_protocol,
              machine_password,
              created_at,
              updated_at,
              last_seen_at,
              last_sync_at
            FROM devices
            ORDER BY device_id
            """
        )
        with self.engine.begin() as conn:
            rows = conn.execute(query).mappings().all()
        output = [dict(row) for row in rows]
        for row in output:
            row["is_active"] = _as_bool(row.get("is_active"))
        return output

    def list_attendance_events(
        self,
        *,
        device_id: str | None = None,
        employee_code: str | None = None,
        from_utc: str | None = None,
        to_utc: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 5000))
        filters: list[str] = []
        params: dict[str, Any] = {}
        if device_id:
            filters.append("device_id = :device_id")
            params["device_id"] = device_id
        if employee_code:
            filters.append("employee_code = :employee_code")
            params["employee_code"] = employee_code
        if from_utc:
            filters.append("timestamp_utc >= :from_utc")
            params["from_utc"] = from_utc
        if to_utc:
            filters.append("timestamp_utc <= :to_utc")
            params["to_utc"] = to_utc
        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""

        if self.is_sqlite:
            query = text(
                f"""
                SELECT
                  event_id, idempotency_key, agent_id, device_id, device_ip, employee_code,
                  machine_user_id, timestamp_local, timestamp_utc, timezone, verification_mode,
                  source, raw_payload, created_at, synced_at
                FROM attendance_events
                {where_sql}
                ORDER BY timestamp_utc DESC
                LIMIT :row_limit
                """
            )
            params["row_limit"] = safe_limit
        else:
            query = text(
                f"""
                SELECT TOP ({safe_limit})
                  event_id, idempotency_key, agent_id, device_id, device_ip, employee_code,
                  machine_user_id, timestamp_local, timestamp_utc, timezone, verification_mode,
                  source, raw_payload, created_at, synced_at
                FROM attendance_events
                {where_sql}
                ORDER BY timestamp_utc DESC
                """
            )
        with self.engine.begin() as conn:
            rows = conn.execute(query, params).mappings().all()
        output = [dict(row) for row in rows]
        for row in output:
            row["raw_payload"] = _safe_json_load(str(row.get("raw_payload") or ""))
        return output

    def get_middleware_counts(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            total_events = int(conn.execute(text("SELECT COUNT(*) FROM attendance_events")).scalar_one())
            total_devices = int(conn.execute(text("SELECT COUNT(*) FROM devices")).scalar_one())
            total_agents = int(conn.execute(text("SELECT COUNT(*) FROM agent_nodes")).scalar_one())
            command_rows = conn.execute(
                text(
                    """
                    SELECT status, COUNT(*) AS total
                    FROM command_jobs
                    GROUP BY status
                    """
                )
            ).all()
            webhook_rows = conn.execute(
                text(
                    """
                    SELECT status, COUNT(*) AS total
                    FROM webhook_deliveries
                    GROUP BY status
                    """
                )
            ).all()
            dead_letters = int(conn.execute(text("SELECT COUNT(*) FROM dead_letter_events")).scalar_one())
        return {
            "attendance_events": total_events,
            "devices": total_devices,
            "agents": total_agents,
            "command_status": {str(status): int(total) for status, total in command_rows},
            "webhook_status": {str(status): int(total) for status, total in webhook_rows},
            "dead_letters": dead_letters,
        }

    def get_device(self, device_id: str) -> dict[str, Any]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                      device_id,
                      device_name,
                      site_id,
                      ip,
                      port,
                      machine_number,
                      timezone,
                      is_active,
                      sdk_protocol,
                      machine_password,
                      created_at,
                      updated_at,
                      last_seen_at,
                      last_sync_at
                    FROM devices
                    WHERE device_id = :device_id
                    """
                ),
                {"device_id": device_id},
            ).mappings().first()
        if not row:
            raise ValueError(f"device not found: {device_id}")
        out = dict(row)
        out["is_active"] = _as_bool(out.get("is_active"))
        return out

    def patch_device(self, device_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_device(device_id)
        merged = {
            "device_id": device_id,
            "device_name": patch.get("device_name", current.get("device_name")),
            "site_id": patch.get("site_id", current.get("site_id")),
            "ip": patch.get("ip", current.get("ip")),
            "port": patch.get("port", current.get("port")),
            "machine_number": patch.get("machine_number", current.get("machine_number")),
            "timezone": patch.get("timezone", current.get("timezone")),
            "is_active": patch.get("is_active", current.get("is_active")),
            "sdk_protocol": patch.get("sdk_protocol", current.get("sdk_protocol")),
            "machine_password": patch.get("machine_password", current.get("machine_password")),
        }
        return self.upsert_device(merged)

    def mark_device_seen(self, device_id: str, *, last_seen_at: str, device_ip: str | None = None) -> None:
        with self.engine.begin() as conn:
            if device_ip:
                conn.execute(
                    text(
                        """
                        UPDATE devices
                        SET last_seen_at = :last_seen_at,
                            ip = :device_ip,
                            updated_at = :updated_at
                        WHERE device_id = :device_id
                        """
                    ),
                    {
                        "device_id": device_id,
                        "last_seen_at": last_seen_at,
                        "device_ip": device_ip,
                        "updated_at": format_datetime(datetime.now().replace(microsecond=0)),
                    },
                )
            else:
                conn.execute(
                    text(
                        """
                        UPDATE devices
                        SET last_seen_at = :last_seen_at,
                            updated_at = :updated_at
                        WHERE device_id = :device_id
                        """
                    ),
                    {
                        "device_id": device_id,
                        "last_seen_at": last_seen_at,
                        "updated_at": format_datetime(datetime.now().replace(microsecond=0)),
                    },
                )

    def mark_device_sync(self, device_id: str, when_utc: str | None = None) -> None:
        now_s = when_utc or _utc_iso(_utc_now())
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE devices
                    SET last_sync_at = :when_utc,
                        updated_at = :now_s
                    WHERE device_id = :device_id
                    """
                ),
                {
                    "device_id": device_id,
                    "when_utc": now_s,
                    "now_s": format_datetime(datetime.now().replace(microsecond=0)),
                },
            )

    def record_agent_heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(payload.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        now_utc = _utc_iso(_utc_now())
        details_json = _json_dump(payload.get("details") or {})

        with self.engine.begin() as conn:
            updated = conn.execute(
                text(
                    """
                    UPDATE agent_nodes
                    SET site_id = :site_id,
                        version = :version,
                        host_name = :host_name,
                        local_ip = :local_ip,
                        status = 'ONLINE',
                        last_seen_at = :last_seen_at,
                        details_json = :details_json
                    WHERE agent_id = :agent_id
                    """
                ),
                {
                    "agent_id": agent_id,
                    "site_id": str(payload.get("site_id") or "").strip(),
                    "version": str(payload.get("version") or "").strip(),
                    "host_name": str(payload.get("host_name") or "").strip(),
                    "local_ip": str(payload.get("local_ip") or "").strip(),
                    "last_seen_at": now_utc,
                    "details_json": details_json,
                },
            )
            if int(updated.rowcount or 0) == 0:
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_nodes (
                          agent_id, site_id, version, host_name, local_ip,
                          status, last_seen_at, details_json
                        ) VALUES (
                          :agent_id, :site_id, :version, :host_name, :local_ip,
                          'ONLINE', :last_seen_at, :details_json
                        )
                        """
                    ),
                    {
                        "agent_id": agent_id,
                        "site_id": str(payload.get("site_id") or "").strip(),
                        "version": str(payload.get("version") or "").strip(),
                        "host_name": str(payload.get("host_name") or "").strip(),
                        "local_ip": str(payload.get("local_ip") or "").strip(),
                        "last_seen_at": now_utc,
                        "details_json": details_json,
                    },
                )

            row = conn.execute(
                text(
                    """
                    SELECT agent_id, site_id, version, host_name, local_ip, status, last_seen_at, details_json
                    FROM agent_nodes
                    WHERE agent_id = :agent_id
                    """
                ),
                {"agent_id": agent_id},
            ).mappings().first()
        return dict(row) if row else {"agent_id": agent_id, "status": "ONLINE"}

    def ingest_attendance_batch(self, *, agent_id: str, events: list[dict[str, Any]]) -> dict[str, int]:
        inserted = 0
        deduped = 0
        invalid = 0
        now_s = _utc_iso(_utc_now())

        with self.engine.begin() as conn:
            for event in events:
                try:
                    device_id = str(event.get("device_id") or "").strip()
                    employee_code = str(event.get("employee_code") or "").strip()
                    timestamp_local = str(event.get("timestamp_local") or "").strip()
                    timezone_name = str(event.get("timezone") or "Asia/Kolkata").strip() or "Asia/Kolkata"
                    if not (device_id and employee_code and timestamp_local):
                        invalid += 1
                        continue
                    timestamp_utc = _normalize_timestamp_utc(
                        timestamp_local=timestamp_local,
                        timestamp_utc=(event.get("timestamp_utc") or None),
                        timezone_name=timezone_name,
                    )

                    event_id = str(event.get("event_id") or "").strip() or str(uuid.uuid4())
                    idempotency_key = (
                        str(event.get("idempotency_key") or "").strip()
                        or f"{device_id}|{employee_code}|{timestamp_local}"
                    )
                    payload_json = _json_dump(event.get("raw_payload") or {})

                    try:
                        conn.execute(
                            text(
                                """
                                INSERT INTO attendance_events (
                                  event_id, idempotency_key, agent_id, device_id, device_ip,
                                  employee_code, machine_user_id, timestamp_local, timestamp_utc,
                                  timezone, verification_mode, source, raw_payload, created_at
                                ) VALUES (
                                  :event_id, :idempotency_key, :agent_id, :device_id, :device_ip,
                                  :employee_code, :machine_user_id, :timestamp_local, :timestamp_utc,
                                  :timezone, :verification_mode, :source, :raw_payload, :created_at
                                )
                                """
                            ),
                            {
                                "event_id": event_id,
                                "idempotency_key": idempotency_key,
                                "agent_id": agent_id,
                                "device_id": device_id,
                                "device_ip": str(event.get("device_ip") or "").strip(),
                                "employee_code": employee_code,
                                "machine_user_id": str(event.get("machine_user_id") or "").strip(),
                                "timestamp_local": timestamp_local,
                                "timestamp_utc": timestamp_utc,
                                "timezone": timezone_name,
                                "verification_mode": str(event.get("verification_mode") or "").strip(),
                                "source": str(event.get("source") or "pull_sdk").strip() or "pull_sdk",
                                "raw_payload": payload_json,
                                "created_at": now_s,
                            },
                        )
                        inserted += 1
                        self._enqueue_webhook_rows(
                            conn,
                            event_type="attendance.created",
                            event_id=event_id,
                            payload={
                                "event_id": event_id,
                                "employee_code": employee_code,
                                "machine_user_id": str(event.get("machine_user_id") or ""),
                                "device_id": device_id,
                                "device_ip": str(event.get("device_ip") or ""),
                                "timestamp_local": timestamp_local,
                                "timestamp_utc": timestamp_utc,
                                "timezone": timezone_name,
                                "verification_mode": str(event.get("verification_mode") or ""),
                                "source": str(event.get("source") or "pull_sdk"),
                            },
                            now_utc=now_s,
                        )
                    except IntegrityError:
                        deduped += 1
                except Exception:
                    invalid += 1
        return {"inserted": inserted, "deduped": deduped, "invalid": invalid}

    def create_command(
        self,
        *,
        request_id: str,
        device_id: str,
        command_type: str,
        payload: dict[str, Any],
        priority: int = 100,
    ) -> dict[str, Any]:
        request_id = str(request_id or "").strip()
        if not request_id:
            raise ValueError("request_id is required")
        device_id = str(device_id or "").strip()
        if not device_id:
            raise ValueError("device_id is required")
        command_type = str(command_type or "").strip()
        if not command_type:
            raise ValueError("command_type is required")

        command_id = str(uuid.uuid4())
        now_utc = _utc_iso(_utc_now())
        payload_json = _json_dump(payload or {})

        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT command_id
                    FROM command_jobs
                    WHERE request_id = :request_id
                    """
                ),
                {"request_id": request_id},
            ).mappings().first()
            if row:
                return self.get_command(str(row["command_id"]))

            conn.execute(
                text(
                    """
                    INSERT INTO command_jobs (
                      command_id, request_id, device_id, command_type, payload_json,
                      status, priority, retry_count, next_attempt_at, created_at, updated_at
                    ) VALUES (
                      :command_id, :request_id, :device_id, :command_type, :payload_json,
                      'PENDING', :priority, 0, :next_attempt_at, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "command_id": command_id,
                    "request_id": request_id,
                    "device_id": device_id,
                    "command_type": command_type,
                    "payload_json": payload_json,
                    "priority": int(priority),
                    "next_attempt_at": now_utc,
                    "created_at": now_utc,
                    "updated_at": now_utc,
                },
            )
        return self.get_command(command_id)

    def list_commands(
        self,
        *,
        device_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        filters = []
        params: dict[str, Any] = {}
        if device_id:
            filters.append("device_id = :device_id")
            params["device_id"] = device_id
        if status:
            filters.append("status = :status")
            params["status"] = status
        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""

        if self.is_sqlite:
            query = text(
                f"""
                SELECT
                  command_id, request_id, device_id, command_type, payload_json, status, priority,
                  retry_count, next_attempt_at, claimed_at, claimed_by, completed_at,
                  error_code, last_error, created_at, updated_at
                FROM command_jobs
                {where_sql}
                ORDER BY created_at DESC
                LIMIT :row_limit
                """
            )
            params["row_limit"] = safe_limit
        else:
            query = text(
                f"""
                SELECT TOP ({safe_limit})
                  command_id, request_id, device_id, command_type, payload_json, status, priority,
                  retry_count, next_attempt_at, claimed_at, claimed_by, completed_at,
                  error_code, last_error, created_at, updated_at
                FROM command_jobs
                {where_sql}
                ORDER BY created_at DESC
                """
            )
        with self.engine.begin() as conn:
            rows = conn.execute(query, params).mappings().all()
        return [self._command_row_to_dict(dict(row)) for row in rows]

    def get_command(self, command_id: str) -> dict[str, Any]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                      command_id, request_id, device_id, command_type, payload_json, status, priority,
                      retry_count, next_attempt_at, claimed_at, claimed_by, completed_at,
                      error_code, last_error, created_at, updated_at
                    FROM command_jobs
                    WHERE command_id = :command_id
                    """
                ),
                {"command_id": command_id},
            ).mappings().first()
        if not row:
            raise ValueError(f"command not found: {command_id}")
        return self._command_row_to_dict(dict(row))

    def claim_commands(self, *, agent_id: str, device_ids: list[str], limit: int) -> list[dict[str, Any]]:
        clean_ids = [str(v).strip() for v in device_ids if str(v).strip()]
        if not clean_ids:
            return []
        now_utc = _utc_iso(_utc_now())
        safe_limit = max(1, min(int(limit), 100))
        placeholders = ",".join([f":device_id_{i}" for i in range(len(clean_ids))])
        params: dict[str, Any] = {"now_utc": now_utc}
        for i, value in enumerate(clean_ids):
            params[f"device_id_{i}"] = value

        if self.is_sqlite:
            query = text(
                f"""
                SELECT command_id
                FROM command_jobs
                WHERE status IN ('PENDING','RETRY')
                  AND next_attempt_at <= :now_utc
                  AND device_id IN ({placeholders})
                ORDER BY priority ASC, created_at ASC
                LIMIT :row_limit
                """
            )
            params["row_limit"] = safe_limit
        else:
            query = text(
                f"""
                SELECT TOP ({safe_limit}) command_id
                FROM command_jobs
                WHERE status IN ('PENDING','RETRY')
                  AND next_attempt_at <= :now_utc
                  AND device_id IN ({placeholders})
                ORDER BY priority ASC, created_at ASC
                """
            )
        with self.engine.begin() as conn:
            rows = conn.execute(query, params).mappings().all()
            command_ids = [str(row["command_id"]) for row in rows]
            if not command_ids:
                return []
            for command_id in command_ids:
                conn.execute(
                    text(
                        """
                        UPDATE command_jobs
                        SET status = 'CLAIMED',
                            claimed_at = :claimed_at,
                            claimed_by = :claimed_by,
                            updated_at = :updated_at
                        WHERE command_id = :command_id
                        """
                    ),
                    {
                        "claimed_at": now_utc,
                        "claimed_by": agent_id,
                        "updated_at": now_utc,
                        "command_id": command_id,
                    },
                )

            out_rows = []
            for command_id in command_ids:
                row = conn.execute(
                    text(
                        """
                        SELECT
                          command_id, request_id, device_id, command_type, payload_json, status, priority,
                          retry_count, next_attempt_at, claimed_at, claimed_by, completed_at,
                          error_code, last_error, created_at, updated_at
                        FROM command_jobs
                        WHERE command_id = :command_id
                        """
                    ),
                    {"command_id": command_id},
                ).mappings().first()
                if row:
                    out_rows.append(self._command_row_to_dict(dict(row)))
        return out_rows

    def submit_command_result(
        self,
        *,
        command_id: str,
        agent_id: str,
        success: bool,
        error_code: str | None,
        error_message: str | None,
        result_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        now_utc_dt = _utc_now()
        now_utc = _utc_iso(now_utc_dt)
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT
                      command_id, request_id, device_id, command_type, payload_json, status, priority,
                      retry_count, next_attempt_at, claimed_at, claimed_by, completed_at,
                      error_code, last_error, created_at, updated_at
                    FROM command_jobs
                    WHERE command_id = :command_id
                    """
                ),
                {"command_id": command_id},
            ).mappings().first()
            if not row:
                raise ValueError(f"command not found: {command_id}")
            retry_count = int(row["retry_count"] or 0)
            attempt_no = retry_count + 1
            command_payload = _safe_json_load(str(row.get("payload_json") or "{}")) or {}

            conn.execute(
                text(
                    """
                    INSERT INTO command_history (
                      command_id, attempt_no, agent_id, status, error_code,
                      error_message, result_json, started_at, finished_at
                    ) VALUES (
                      :command_id, :attempt_no, :agent_id, :status, :error_code,
                      :error_message, :result_json, :started_at, :finished_at
                    )
                    """
                ),
                {
                    "command_id": command_id,
                    "attempt_no": attempt_no,
                    "agent_id": agent_id,
                    "status": "SUCCESS" if success else "FAILED",
                    "error_code": error_code,
                    "error_message": (error_message or "")[:1000],
                    "result_json": _json_dump(result_payload or {}),
                    "started_at": str(row.get("claimed_at") or now_utc),
                    "finished_at": now_utc,
                },
            )

            if success:
                conn.execute(
                    text(
                        """
                        UPDATE command_jobs
                        SET status = 'SUCCESS',
                            completed_at = :completed_at,
                            retry_count = :retry_count,
                            error_code = NULL,
                            last_error = NULL,
                            updated_at = :updated_at
                        WHERE command_id = :command_id
                        """
                    ),
                    {
                        "completed_at": now_utc,
                        "retry_count": attempt_no,
                        "updated_at": now_utc,
                        "command_id": command_id,
                    },
                )
                self._enqueue_webhook_rows(
                    conn,
                    event_type="command.completed",
                    event_id=command_id,
                    payload={
                        "command_id": command_id,
                        "request_id": str(row["request_id"]),
                        "device_id": str(row["device_id"]),
                        "command_type": str(row["command_type"]),
                        "command_payload": command_payload,
                        "status": "SUCCESS",
                        "attempt_no": attempt_no,
                        "completed_at": now_utc,
                        "result": result_payload or {},
                    },
                    now_utc=now_utc,
                )
            else:
                plan = _build_retry_plan(attempt_no, now_utc_dt)
                if plan.status == "DEAD":
                    conn.execute(
                        text(
                            """
                            UPDATE command_jobs
                            SET status = 'DEAD',
                                retry_count = :retry_count,
                                completed_at = :completed_at,
                                error_code = :error_code,
                                last_error = :last_error,
                                updated_at = :updated_at
                            WHERE command_id = :command_id
                            """
                        ),
                        {
                            "retry_count": attempt_no,
                            "completed_at": now_utc,
                            "error_code": error_code,
                            "last_error": (error_message or "command failed")[:1000],
                            "updated_at": now_utc,
                            "command_id": command_id,
                        },
                    )
                    conn.execute(
                        text(
                            """
                            INSERT INTO dead_letter_events (
                              entity_type, entity_id, reason, payload_json, created_at
                            ) VALUES (
                              'command', :entity_id, :reason, :payload_json, :created_at
                            )
                            """
                        ),
                        {
                            "entity_id": command_id,
                            "reason": (error_message or "command failed")[:1000],
                            "payload_json": str(row["payload_json"]),
                            "created_at": now_utc,
                        },
                    )
                    self._enqueue_webhook_rows(
                        conn,
                        event_type="command.failed",
                        event_id=command_id,
                        payload={
                            "command_id": command_id,
                            "request_id": str(row["request_id"]),
                            "device_id": str(row["device_id"]),
                            "command_type": str(row["command_type"]),
                            "command_payload": command_payload,
                            "status": "DEAD",
                            "attempt_no": attempt_no,
                            "error_code": error_code,
                            "error_message": error_message or "command failed",
                            "completed_at": now_utc,
                            "result": result_payload or {},
                        },
                        now_utc=now_utc,
                    )
                else:
                    conn.execute(
                        text(
                            """
                            UPDATE command_jobs
                            SET status = 'RETRY',
                                retry_count = :retry_count,
                                next_attempt_at = :next_attempt_at,
                                error_code = :error_code,
                                last_error = :last_error,
                                updated_at = :updated_at
                            WHERE command_id = :command_id
                            """
                        ),
                        {
                            "retry_count": attempt_no,
                            "next_attempt_at": plan.next_attempt_at,
                            "error_code": error_code,
                            "last_error": (error_message or "command failed")[:1000],
                            "updated_at": now_utc,
                            "command_id": command_id,
                        },
                    )
        return self.get_command(command_id)

    def upsert_webhook_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_type = str(payload.get("event_type") or "").strip()
        target_url = str(payload.get("target_url") or "").strip()
        if not event_type:
            raise ValueError("event_type is required")
        if not target_url:
            raise ValueError("target_url is required")
        subscription_id = str(payload.get("subscription_id") or "").strip() or str(uuid.uuid4())
        now_utc = _utc_iso(_utc_now())
        is_active = 1 if _as_bool(payload.get("is_active", True)) else 0

        with self.engine.begin() as conn:
            updated = conn.execute(
                text(
                    """
                    UPDATE webhook_subscriptions
                    SET event_type = :event_type,
                        target_url = :target_url,
                        is_active = :is_active,
                        updated_at = :updated_at
                    WHERE subscription_id = :subscription_id
                    """
                ),
                {
                    "subscription_id": subscription_id,
                    "event_type": event_type,
                    "target_url": target_url,
                    "is_active": is_active,
                    "updated_at": now_utc,
                },
            )
            if int(updated.rowcount or 0) == 0:
                conn.execute(
                    text(
                        """
                        INSERT INTO webhook_subscriptions (
                          subscription_id, event_type, target_url, is_active, created_at, updated_at
                        ) VALUES (
                          :subscription_id, :event_type, :target_url, :is_active, :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        "subscription_id": subscription_id,
                        "event_type": event_type,
                        "target_url": target_url,
                        "is_active": is_active,
                        "created_at": now_utc,
                        "updated_at": now_utc,
                    },
                )
            row = conn.execute(
                text(
                    """
                    SELECT subscription_id, event_type, target_url, is_active, created_at, updated_at
                    FROM webhook_subscriptions
                    WHERE subscription_id = :subscription_id
                    """
                ),
                {"subscription_id": subscription_id},
            ).mappings().first()
        out = dict(row) if row else {}
        out["is_active"] = _as_bool(out.get("is_active"))
        return out

    def list_webhook_subscriptions(self) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT subscription_id, event_type, target_url, is_active, created_at, updated_at
                    FROM webhook_subscriptions
                    ORDER BY created_at DESC
                    """
                )
            ).mappings().all()
        out = [dict(row) for row in rows]
        for row in out:
            row["is_active"] = _as_bool(row.get("is_active"))
        return out

    def enqueue_webhook_event(self, *, event_type: str, event_id: str, payload: dict[str, Any]) -> int:
        now_utc = _utc_iso(_utc_now())
        with self.engine.begin() as conn:
            return self._enqueue_webhook_rows(
                conn,
                event_type=event_type,
                event_id=event_id,
                payload=payload,
                now_utc=now_utc,
            )

    def _enqueue_webhook_rows(
        self,
        conn: Any,
        *,
        event_type: str,
        event_id: str,
        payload: dict[str, Any],
        now_utc: str,
    ) -> int:
        subscriptions = conn.execute(
            text(
                """
                SELECT subscription_id, target_url
                FROM webhook_subscriptions
                WHERE event_type = :event_type
                  AND is_active = 1
                """
            ),
            {"event_type": event_type},
        ).mappings().all()
        inserted = 0
        for sub in subscriptions:
            conn.execute(
                text(
                    """
                    INSERT INTO webhook_deliveries (
                      delivery_id, subscription_id, event_type, event_id, target_url, payload_json,
                      status, attempt_no, next_attempt_at, created_at, updated_at
                    ) VALUES (
                      :delivery_id, :subscription_id, :event_type, :event_id, :target_url, :payload_json,
                      'PENDING', 0, :next_attempt_at, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "delivery_id": str(uuid.uuid4()),
                    "subscription_id": str(sub["subscription_id"]),
                    "event_type": event_type,
                    "event_id": event_id,
                    "target_url": str(sub["target_url"]),
                    "payload_json": _json_dump(payload),
                    "next_attempt_at": now_utc,
                    "created_at": now_utc,
                    "updated_at": now_utc,
                },
            )
            inserted += 1
        return inserted

    def list_webhook_deliveries(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        params: dict[str, Any] = {}
        where_sql = ""
        if status:
            where_sql = "WHERE status = :status"
            params["status"] = status

        if self.is_sqlite:
            query = text(
                f"""
                SELECT
                  delivery_id, subscription_id, event_type, event_id, target_url, payload_json,
                  status, attempt_no, next_attempt_at, last_status_code, last_error,
                  last_response, created_at, updated_at
                FROM webhook_deliveries
                {where_sql}
                ORDER BY created_at DESC
                LIMIT :row_limit
                """
            )
            params["row_limit"] = safe_limit
        else:
            query = text(
                f"""
                SELECT TOP ({safe_limit})
                  delivery_id, subscription_id, event_type, event_id, target_url, payload_json,
                  status, attempt_no, next_attempt_at, last_status_code, last_error,
                  last_response, created_at, updated_at
                FROM webhook_deliveries
                {where_sql}
                ORDER BY created_at DESC
                """
            )

        with self.engine.begin() as conn:
            rows = conn.execute(query, params).mappings().all()
        out = [dict(row) for row in rows]
        for row in out:
            row["payload_json"] = _safe_json_load(str(row.get("payload_json") or ""))
        return out

    def claim_due_webhook_deliveries(self, *, limit: int) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        now_utc = _utc_iso(_utc_now())

        if self.is_sqlite:
            query = text(
                """
                SELECT
                  delivery_id, subscription_id, event_type, event_id, target_url, payload_json,
                  status, attempt_no, next_attempt_at, last_status_code, last_error,
                  last_response, created_at, updated_at
                FROM webhook_deliveries
                WHERE status IN ('PENDING','RETRY')
                  AND next_attempt_at <= :now_utc
                ORDER BY next_attempt_at ASC
                LIMIT :row_limit
                """
            )
            params = {"now_utc": now_utc, "row_limit": safe_limit}
        else:
            query = text(
                f"""
                SELECT TOP ({safe_limit})
                  delivery_id, subscription_id, event_type, event_id, target_url, payload_json,
                  status, attempt_no, next_attempt_at, last_status_code, last_error,
                  last_response, created_at, updated_at
                FROM webhook_deliveries
                WHERE status IN ('PENDING','RETRY')
                  AND next_attempt_at <= :now_utc
                ORDER BY next_attempt_at ASC
                """
            )
            params = {"now_utc": now_utc}
        with self.engine.begin() as conn:
            rows = conn.execute(query, params).mappings().all()
        out = [dict(row) for row in rows]
        for row in out:
            row["payload_json"] = _safe_json_load(str(row.get("payload_json") or ""))
        return out

    def mark_webhook_sent(self, *, delivery_id: str, status_code: int | None, response_text: str | None) -> None:
        now_utc = _utc_iso(_utc_now())
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE webhook_deliveries
                    SET status = 'SENT',
                        attempt_no = attempt_no + 1,
                        last_status_code = :status_code,
                        last_error = NULL,
                        last_response = :last_response,
                        updated_at = :updated_at
                    WHERE delivery_id = :delivery_id
                    """
                ),
                {
                    "delivery_id": delivery_id,
                    "status_code": status_code,
                    "last_response": (response_text or "")[:2000],
                    "updated_at": now_utc,
                },
            )

    def mark_webhook_failed(
        self,
        *,
        delivery_id: str,
        current_attempt_no: int,
        status_code: int | None,
        error_message: str,
        response_text: str | None,
    ) -> None:
        now_utc_dt = _utc_now()
        now_utc = _utc_iso(now_utc_dt)
        next_attempt_no = int(current_attempt_no) + 1
        plan = _build_webhook_retry_plan(next_attempt_no, now_utc_dt)

        with self.engine.begin() as conn:
            if plan.status == "DEAD":
                conn.execute(
                    text(
                        """
                        UPDATE webhook_deliveries
                        SET status = 'DEAD',
                            attempt_no = :attempt_no,
                            last_status_code = :status_code,
                            last_error = :last_error,
                            last_response = :last_response,
                            updated_at = :updated_at
                        WHERE delivery_id = :delivery_id
                        """
                    ),
                    {
                        "delivery_id": delivery_id,
                        "attempt_no": next_attempt_no,
                        "status_code": status_code,
                        "last_error": error_message[:1000],
                        "last_response": (response_text or "")[:2000],
                        "updated_at": now_utc,
                    },
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO dead_letter_events (
                          entity_type, entity_id, reason, payload_json, created_at
                        )
                        SELECT
                          'webhook_delivery',
                          delivery_id,
                          :reason,
                          payload_json,
                          :created_at
                        FROM webhook_deliveries
                        WHERE delivery_id = :delivery_id
                        """
                    ),
                    {
                        "delivery_id": delivery_id,
                        "reason": error_message[:1000],
                        "created_at": now_utc,
                    },
                )
            else:
                conn.execute(
                    text(
                        """
                        UPDATE webhook_deliveries
                        SET status = 'RETRY',
                            attempt_no = :attempt_no,
                            next_attempt_at = :next_attempt_at,
                            last_status_code = :status_code,
                            last_error = :last_error,
                            last_response = :last_response,
                            updated_at = :updated_at
                        WHERE delivery_id = :delivery_id
                        """
                    ),
                    {
                        "delivery_id": delivery_id,
                        "attempt_no": next_attempt_no,
                        "next_attempt_at": plan.next_attempt_at,
                        "status_code": status_code,
                        "last_error": error_message[:1000],
                        "last_response": (response_text or "")[:2000],
                        "updated_at": now_utc,
                    },
                )

    def force_retry_webhook(self, delivery_id: str) -> dict[str, Any]:
        now_utc = _utc_iso(_utc_now())
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE webhook_deliveries
                    SET status = 'RETRY',
                        next_attempt_at = :next_attempt_at,
                        updated_at = :updated_at
                    WHERE delivery_id = :delivery_id
                    """
                ),
                {"delivery_id": delivery_id, "next_attempt_at": now_utc, "updated_at": now_utc},
            )
            row = conn.execute(
                text(
                    """
                    SELECT
                      delivery_id, subscription_id, event_type, event_id, target_url, payload_json,
                      status, attempt_no, next_attempt_at, last_status_code, last_error,
                      last_response, created_at, updated_at
                    FROM webhook_deliveries
                    WHERE delivery_id = :delivery_id
                    """
                ),
                {"delivery_id": delivery_id},
            ).mappings().first()
        if not row:
            raise ValueError(f"webhook delivery not found: {delivery_id}")
        out = dict(row)
        out["payload_json"] = _safe_json_load(str(out.get("payload_json") or ""))
        return out

    @staticmethod
    def _command_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
        row["payload"] = _safe_json_load(str(row.get("payload_json") or "{}")) or {}
        row.pop("payload_json", None)
        return row
