from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from attendance_relay.models import OutboxRecord
from attendance_relay.time_utils import format_datetime


@dataclass(slots=True)
class SendResult:
    ok: bool
    status_code: int | None
    response_text: str | None
    error: str | None


class OutboundClient:
    def __init__(
        self,
        *,
        url: str,
        api_key_header: str,
        api_key: str,
        timeout_seconds: float,
        verify_tls: bool,
        enforce_https: bool,
        enforce_post: bool,
        method: str = "POST",
    ) -> None:
        self.url = url
        self.method = method.upper()
        self.api_key_header = api_key_header
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.verify_tls = verify_tls
        self.enforce_https = enforce_https
        self.enforce_post = enforce_post
        self._validate_policy()
        self.client = httpx.Client(timeout=self.timeout_seconds, verify=self.verify_tls)

    def close(self) -> None:
        self.client.close()

    def send(self, record: OutboxRecord, payload_override: dict[str, Any] | None = None) -> SendResult:
        payload = payload_override or {
            "employee_code": record.employee_code,
            "log_datetime": format_datetime(record.log_datetime),
            "log_time": record.log_time,
            "downloaded_at": format_datetime(record.downloaded_at),
            "device_sn": record.device_sn,
        }
        headers = {
            "Content-Type": "application/json",
            self.api_key_header: self.api_key,
        }
        try:
            response = self.client.request(self.method, self.url, json=payload, headers=headers)
            if 200 <= response.status_code < 300:
                return SendResult(ok=True, status_code=response.status_code, response_text=response.text[:1000], error=None)
            return SendResult(
                ok=False,
                status_code=response.status_code,
                response_text=response.text[:1000],
                error=f"Non-2xx response: {response.status_code}",
            )
        except Exception as exc:  # noqa: BLE001
            return SendResult(ok=False, status_code=None, response_text=None, error=f"{type(exc).__name__}: {exc}")

    def _validate_policy(self) -> None:
        if self.enforce_https and not self.url.lower().startswith("https://"):
            raise ValueError("Outbound URL must be HTTPS.")
        if self.enforce_post and self.method != "POST":
            raise ValueError("Outbound method must be POST.")
