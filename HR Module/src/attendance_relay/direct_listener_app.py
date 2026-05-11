from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from attendance_relay.decoder import DecodeError, decode_machine_payload
from attendance_relay.logging_utils import configure_logging, log_event
from attendance_relay.settings import Settings
from attendance_relay.time_utils import format_datetime, now_local


LOGGER = logging.getLogger("attendance_relay.direct_listener")
_WRITE_LOCK = Lock()


def create_direct_listener_app(settings: Settings) -> FastAPI:
    configure_logging(settings.log_level)
    output_path = Path(settings.direct_listener_jsonl_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Attendance Direct Listener", version="1.0.0")
    app.state.settings = settings
    app.state.output_path = output_path

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "output_jsonl": str(output_path),
            }
        )

    @app.post(settings.direct_listener_path)
    async def capture(request: Request) -> PlainTextResponse:
        raw_body = await request.body()
        downloaded_at = now_local(settings.tz_name)
        source_ip = request.client.host if request.client else None

        record: dict[str, str | bool | None] = {
            "received_at": format_datetime(downloaded_at),
            "request_code": request.headers.get("request_code"),
            "source_ip": source_ip,
            "decoded": False,
        }
        try:
            punch = decode_machine_payload(raw_body=raw_body, downloaded_at=downloaded_at, source_ip=source_ip)
            record.update(
                {
                    "decoded": True,
                    "employee_code": punch.employee_code,
                    "log_datetime": format_datetime(punch.log_datetime),
                    "log_time": punch.log_time,
                    "downloaded_at": format_datetime(punch.downloaded_at),
                    "device_sn": punch.device_sn,
                    "raw_user_id": punch.raw_user_id,
                    "raw_io_time": punch.raw_io_time,
                }
            )
        except DecodeError as exc:
            record["decode_error"] = str(exc)
            record["raw_preview"] = raw_body[:256].hex()

        _append_jsonl(output_path, record)
        log_event(
            LOGGER,
            "info",
            "direct_listener_capture",
            decoded=record["decoded"],
            source_ip=source_ip,
        )

        return PlainTextResponse(
            f"response_code={settings.machine_ok_response_code}",
            headers={"response_code": settings.machine_ok_response_code},
        )

    return app


def _append_jsonl(path: Path, payload: dict[str, str | bool | None]) -> None:
    line = json.dumps(payload, ensure_ascii=True)
    with _WRITE_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
