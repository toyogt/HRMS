from __future__ import annotations

import argparse
import csv
import random
import time
from datetime import timedelta
from pathlib import Path

import httpx

from attendance_relay.time_utils import now_local


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate machine realtime_glog posts.")
    parser.add_argument("--url", required=True, help="Target ingestion/direct-listener URL.")
    parser.add_argument("--csv", default="TotalEmployee.csv", help="Employee CSV path.")
    parser.add_argument("--device-sn", default="SN-SIM-01", help="Simulated machine serial number.")
    parser.add_argument("--count", type=int, default=10, help="Number of events to send.")
    parser.add_argument("--sleep-ms", type=int, default=150, help="Delay between events in milliseconds.")
    parser.add_argument("--request-code", default="realtime_glog", help="request_code header value.")
    args = parser.parse_args()

    employees = _load_employees(Path(args.csv))
    if not employees:
        raise SystemExit(f"No employee codes found in CSV: {args.csv}")

    ok = 0
    failed = 0

    with httpx.Client(timeout=5.0, verify=False) as client:
        base_dt = now_local("Asia/Calcutta")
        for i in range(args.count):
            emp = employees[i % len(employees)]
            io_dt = base_dt + timedelta(seconds=i)
            io_time = io_dt.strftime("%Y%m%d%H%M%S")
            payload = f"user_id={emp}\tio_time={io_time}\tdev_id={args.device_sn}\n".encode("ascii")
            response = client.post(args.url, headers={"request_code": args.request_code}, content=payload)
            if response.status_code == 200 and "response_code=OK" in response.text:
                ok += 1
            else:
                failed += 1
            time.sleep(max(args.sleep_ms, 0) / 1000.0)

    print(f"Sent={args.count} OK={ok} Failed={failed}")


def _load_employees(csv_path: Path) -> list[str]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        normalized = {name.lower().strip(): name for name in reader.fieldnames}
        key = None
        for candidate in (
            "employee_code",
            "empcode",
            "employeeid",
            "employee_id",
            "code",
            "cardno",
            "user_id",
            "userid",
        ):
            if candidate in normalized:
                key = normalized[candidate]
                break
        if key is None:
            key = reader.fieldnames[0]

        employees: list[str] = []
        for row in reader:
            raw = (row.get(key) or "").strip()
            if raw:
                employees.append(raw)
        random.shuffle(employees)
        return employees
