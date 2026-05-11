from __future__ import annotations

import hashlib


def build_event_hash(
    *,
    employee_code: str,
    log_datetime: str,
    log_time: str,
    device_sn: str,
) -> str:
    canonical = "|".join(
        [
            employee_code.strip(),
            log_datetime.strip(),
            log_time.strip(),
            device_sn.strip(),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
