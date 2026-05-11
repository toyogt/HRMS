from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"


@dataclass(slots=True)
class MachinePunch:
    employee_code: str
    log_datetime: datetime
    log_time: str
    downloaded_at: datetime
    device_sn: str
    raw_user_id: str
    raw_io_time: str
    source_ip: str | None = None
    raw_preview: str | None = None


@dataclass(slots=True)
class OutboxRecord:
    id: int
    event_hash: str
    employee_code: str
    log_datetime: datetime
    log_time: str
    downloaded_at: datetime
    device_sn: str
    attempt_count: int
