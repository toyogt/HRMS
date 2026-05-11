from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

import httpx

from attendance_relay.middleware_repository import MiddlewareRepository
from attendance_relay.settings import Settings


def _build_signature(secret: str, timestamp: str, payload_text: str) -> str:
    msg = f"{timestamp}.{payload_text}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def dispatch_due_webhooks(*, settings: Settings, repo: MiddlewareRepository, limit: int) -> dict[str, int]:
    rows = repo.claim_due_webhook_deliveries(limit=limit)
    sent = 0
    failed = 0
    dead = 0
    skipped = 0

    if not rows:
        return {"picked": 0, "sent": 0, "failed": 0, "dead": 0, "skipped": 0}

    with httpx.Client(timeout=settings.webhook_timeout_seconds, verify=settings.outbound_verify_tls) as client:
        for row in rows:
            payload_obj: Any = row.get("payload_json") or {}
            payload_text = json.dumps(payload_obj, ensure_ascii=True, separators=(",", ":"))
            timestamp = str(int(datetime.now().timestamp()))
            headers = {
                "Content-Type": "application/json",
                "X-Webhook-Event": str(row.get("event_type") or ""),
                "X-Webhook-Id": str(row.get("delivery_id") or ""),
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Signature": _build_signature(settings.webhook_hmac_secret, timestamp, payload_text),
            }
            target_url = str(row.get("target_url") or "").strip()
            if not target_url:
                skipped += 1
                repo.mark_webhook_failed(
                    delivery_id=str(row["delivery_id"]),
                    current_attempt_no=int(row.get("attempt_no") or 0),
                    status_code=None,
                    error_message="target_url missing",
                    response_text=None,
                )
                continue

            try:
                response = client.post(target_url, content=payload_text.encode("utf-8"), headers=headers)
                if 200 <= response.status_code < 300:
                    sent += 1
                    repo.mark_webhook_sent(
                        delivery_id=str(row["delivery_id"]),
                        status_code=response.status_code,
                        response_text=response.text[:2000],
                    )
                else:
                    failed += 1
                    repo.mark_webhook_failed(
                        delivery_id=str(row["delivery_id"]),
                        current_attempt_no=int(row.get("attempt_no") or 0),
                        status_code=response.status_code,
                        error_message=f"non_2xx_status={response.status_code}",
                        response_text=response.text[:2000],
                    )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                repo.mark_webhook_failed(
                    delivery_id=str(row["delivery_id"]),
                    current_attempt_no=int(row.get("attempt_no") or 0),
                    status_code=None,
                    error_message=f"{type(exc).__name__}: {exc}",
                    response_text=None,
                )

    # Dead count is derived from repository state after marking failures.
    dead = len(repo.list_webhook_deliveries(status="DEAD", limit=limit))
    return {"picked": len(rows), "sent": sent, "failed": failed, "dead": dead, "skipped": skipped}

