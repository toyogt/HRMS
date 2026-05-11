from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
TIME_FMT = "%H:%M:%S"
TZ_ALIAS_FALLBACKS = {
    "Asia/Kolkata": "Asia/Calcutta",
    "Asia/Calcutta": "Asia/Kolkata",
}


def now_local(tz_name: str) -> datetime:
    # Keep local wall-clock time (naive) per requirement.
    for candidate in (tz_name, TZ_ALIAS_FALLBACKS.get(tz_name, "")):
        if not candidate:
            continue
        try:
            return datetime.now(ZoneInfo(candidate)).replace(tzinfo=None, microsecond=0)
        except ZoneInfoNotFoundError:
            continue
    return datetime.now().replace(microsecond=0)


def format_datetime(dt: datetime) -> str:
    return dt.strftime(DATETIME_FMT)


def format_time(dt: datetime) -> str:
    return dt.strftime(TIME_FMT)
