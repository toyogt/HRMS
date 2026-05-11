from __future__ import annotations

import csv
import re
from pathlib import Path


def normalize_employee_code(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""

    prefixed_match = re.fullmatch(r"[Ee]([0-9]+)", raw)
    if prefixed_match:
        return str(int(prefixed_match.group(1)))

    if raw.isdigit():
        return str(int(raw))

    return raw.upper()


def read_employee_master_csv(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []

        field_map = {_normalize_header(k): k for k in reader.fieldnames if k}
        rows: list[dict[str, str]] = []

        for row in reader:
            emp_code = _extract(row, field_map, ("empcode", "employeecode", "employee_code", "cardno", "userid"))
            emp_name = _extract(row, field_map, ("empname", "employeename", "employee_name", "name"))
            if not emp_code:
                continue

            employee_code = emp_code.strip()
            rows.append(
                {
                    "employee_code": employee_code,
                    "employee_code_normalized": normalize_employee_code(employee_code),
                    "employee_name": emp_name,
                    "father_name": _extract(row, field_map, ("fathername", "father_name")),
                    "card_no": _extract(row, field_map, ("cardno", "card_no")),
                    "proximity_card_no": _extract(row, field_map, ("proximitycardno", "proximity_card_no")),
                    "email_id": _extract(row, field_map, ("emailid", "email_id")),
                    "phone_no": _extract(row, field_map, ("phoneno", "phone_no", "mobile", "mobile_no")),
                    "department": _extract(row, field_map, ("department", "dept")),
                    "designation": _extract(row, field_map, ("designation",)),
                    "branch_name": _extract(row, field_map, ("branchname", "branch_name", "branch")),
                    "office_time_policy": _extract(row, field_map, ("officetimepolicy", "office_time_policy")),
                    "date_of_birth": _extract(row, field_map, ("dateofbirth", "dob", "date_of_birth")),
                    "date_of_join": _extract(row, field_map, ("dateofjoin", "doj", "date_of_join")),
                    "shift_start_date": _extract(row, field_map, ("shiftstartdate", "shift_start_date")),
                    "shift_code": _extract(row, field_map, ("shiftcode", "shift_code")),
                    "weekly_off": _extract(row, field_map, ("weeklyoff", "weekly_off")),
                    "company_name": _extract(row, field_map, ("companyname", "company_name")),
                }
            )
    return rows


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _extract(raw_row: dict[str, str], field_map: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        key = field_map.get(alias)
        if key is None:
            continue
        value = (raw_row.get(key) or "").strip()
        if value:
            return value
    return ""
