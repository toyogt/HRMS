from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import parse_qsl

from attendance_relay.models import MachinePunch
from attendance_relay.time_utils import format_time


class DecodeError(ValueError):
    pass


USER_KEYS = {
    "userid",
    "user",
    "uid",
    "pin",
    "enrollnumber",
    "enrollid",
    "employeecode",
}
IO_TIME_KEYS = {
    "iotime",
    "checktime",
    "timestamp",
    "time",
    "eventtime",
    "atttime",
    "logdatetime",
    "logtime",
}
DEVICE_KEYS = {
    "devid",
    "deviceid",
    "devicesn",
    "sn",
    "serialno",
    "serialnumber",
    "terminalsn",
    "terminalid",
}


def decode_machine_payload(
    *,
    raw_body: bytes,
    downloaded_at: datetime,
    source_ip: str | None = None,
) -> MachinePunch:
    text = _to_text(raw_body)
    kv = _extract_key_values(text)

    raw_user_id = _pick_by_alias(kv, USER_KEYS) or _guess_user_id(text)
    raw_io_time = _pick_by_alias(kv, IO_TIME_KEYS) or _guess_io_time(text)
    device_sn = _pick_by_alias(kv, DEVICE_KEYS) or _guess_device_sn(text)

    missing = [name for name, value in [("user_id", raw_user_id), ("io_time", raw_io_time), ("dev_id", device_sn)] if not value]
    if missing:
        raise DecodeError(f"Missing required fields: {', '.join(missing)}")

    log_datetime = _parse_machine_time(raw_io_time)
    return MachinePunch(
        employee_code=raw_user_id,
        log_datetime=log_datetime,
        log_time=format_time(log_datetime),
        downloaded_at=downloaded_at,
        device_sn=device_sn,
        raw_user_id=raw_user_id,
        raw_io_time=raw_io_time,
        source_ip=source_ip,
        raw_preview=text[:2000],
    )


def _to_text(raw_body: bytes) -> str:
    if not raw_body:
        return ""
    # Keep bytes visible even if payload includes non-UTF8 sections.
    return raw_body.decode("latin-1", errors="ignore")


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", key.strip().lower())


def _extract_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}

    normalized = text.replace("\x00", "\n").replace("\r", "\n")
    chunks = re.split(r"[\n\t;]+", normalized)

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if "&" in chunk and "=" in chunk:
            for key, value in parse_qsl(chunk, keep_blank_values=True):
                k = _normalize_key(key)
                if k and value and k not in values:
                    values[k] = value.strip()
            continue
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            k = _normalize_key(key)
            v = value.strip()
            if k and v and k not in values:
                values[k] = v
            continue
        if ":" in chunk:
            key, value = chunk.split(":", 1)
            k = _normalize_key(key)
            v = value.strip()
            if k and v and k not in values:
                values[k] = v

    for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_-]{1,40})\s*=\s*([^\r\n\t& ]+)", text):
        key = _normalize_key(match.group(1))
        value = match.group(2).strip()
        if key and value and key not in values:
            values[key] = value

    return values


def _pick_by_alias(values: dict[str, str], aliases: set[str]) -> str | None:
    for alias in aliases:
        if alias in values and values[alias]:
            return values[alias]
    return None


def _guess_io_time(text: str) -> str | None:
    match = re.search(r"\b\d{14}\b", text)
    if match:
        return match.group(0)
    match = re.search(r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\b", text)
    if match:
        return match.group(0).replace("T", " ")
    return None


def _guess_user_id(text: str) -> str | None:
    for pattern in (
        r"(?i)\b(?:uid|user[_ ]?id|pin|enrollnumber)\s*[:=]\s*([A-Za-z0-9_-]{1,64})",
        r"\b([A-Za-z0-9]{2,20})\b",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _guess_device_sn(text: str) -> str | None:
    match = re.search(r"(?i)\b(?:sn|dev[_ ]?id|device[_ ]?sn|terminalsn)\s*[:=]\s*([A-Za-z0-9_-]{2,64})", text)
    if match:
        return match.group(1)
    return None


def _parse_machine_time(raw: str) -> datetime:
    candidate = raw.strip()
    patterns = (
        "%Y%m%d%H%M%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    )
    for pattern in patterns:
        try:
            return datetime.strptime(candidate, pattern)
        except ValueError:
            continue
    raise DecodeError(f"Unsupported io_time format: {raw!r}")
