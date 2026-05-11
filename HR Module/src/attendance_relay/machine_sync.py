from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from attendance_relay.db import create_db_engine, init_local_schema, is_sqlite
from attendance_relay.machine_sdk import MachineSdkError, SBXPCClient
from attendance_relay.master_data import normalize_employee_code
from attendance_relay.settings import load_settings


_SIGNED_LONG_MAX = 2_147_483_647
_UINT64_MAX = (1 << 64) - 1
_INTEGER_TEXT = re.compile(r"^[0-9]+(?:\.0+)?$")


@dataclass(slots=True)
class SyncSummary:
    scanned: int = 0
    synced: int = 0
    failed: int = 0
    skipped: int = 0


def parse_unsigned_integer(text_value: str | None, max_value: int) -> int | None:
    raw = (text_value or "").strip()
    if not raw or not _INTEGER_TEXT.fullmatch(raw):
        return None
    parsed = int(raw.split(".", 1)[0], 10)
    if parsed < 0 or parsed > max_value:
        return None
    return parsed


def choose_machine_user_id(row: dict[str, Any]) -> int | None:
    for key in ("employee_code_normalized", "employee_code"):
        parsed = parse_unsigned_integer(str(row.get(key) or ""), _SIGNED_LONG_MAX)
        if parsed is not None:
            return parsed
    return None


def choose_card_number(row: dict[str, Any], fallback_user_id: int) -> int:
    for key in ("card_no", "proximity_card_no"):
        parsed = parse_unsigned_integer(str(row.get(key) or ""), _UINT64_MAX)
        if parsed is not None:
            return parsed
    return fallback_user_id


def choose_user_name(row: dict[str, Any]) -> str:
    name = (row.get("employee_name") or "").strip()
    if name:
        return name
    code = (row.get("employee_code") or "").strip()
    return code or "UNKNOWN"


def list_employee_master_rows(engine: Engine, *, limit: int, employee_code: str | None) -> list[dict[str, Any]]:
    normalized = normalize_employee_code(employee_code or "") if employee_code else None
    params: dict[str, Any] = {
        "employee_code": employee_code,
        "employee_code_normalized": normalized,
    }

    if engine.dialect.name == "sqlite":
        query = text(
            """
            SELECT
              employee_code,
              employee_code_normalized,
              employee_name,
              card_no,
              proximity_card_no
            FROM employee_master
            WHERE :employee_code IS NULL
               OR employee_code = :employee_code
               OR employee_code_normalized = :employee_code_normalized
            ORDER BY employee_code
            LIMIT :row_limit
            """
        )
        params["row_limit"] = max(1, int(limit))
    else:
        safe_limit = max(1, int(limit))
        query = text(
            f"""
            SELECT TOP ({safe_limit})
              employee_code,
              employee_code_normalized,
              employee_name,
              card_no,
              proximity_card_no
            FROM employee_master
            WHERE :employee_code IS NULL
               OR employee_code = :employee_code
               OR employee_code_normalized = :employee_code_normalized
            ORDER BY employee_code
            """
        )

    with engine.begin() as conn:
        rows = conn.execute(query, params).mappings().all()
    return [dict(row) for row in rows]


def sync_rows_to_machine(
    *,
    rows: list[dict[str, Any]],
    machine_ip: str,
    machine_port: int,
    machine_password: int,
    machine_number: int,
    timezone1: int,
    timezone2: int,
    group_no: int,
    sdk_dll_path: str,
) -> SyncSummary:
    summary = SyncSummary(scanned=len(rows))
    client = SBXPCClient(sdk_dll_path)
    client.dotnet()
    client.connect_tcpip(machine_number=machine_number, ip_address=machine_ip, port=machine_port, password=machine_password)

    try:
        existing_user_ids = {int(entry.get("user_id", -1)) for entry in client.list_all_user_ids(machine_number)}
        client.enable_device(machine_number, False)
        for row in rows:
            code = str(row.get("employee_code") or "").strip()
            user_id = choose_machine_user_id(row)
            if user_id is None:
                summary.skipped += 1
                print(f"SKIP employee_code={code} reason=non_numeric_or_out_of_range_user_id")
                continue

            card_number = choose_card_number(row, fallback_user_id=user_id)
            user_name = choose_user_name(row)

            try:
                if user_id not in existing_user_ids:
                    client.set_enroll_data1(
                        machine_number,
                        user_id,
                        backup_number=11,
                        machine_privilege=0,
                        credential_value=card_number,
                    )
                    existing_user_ids.add(user_id)
                client.set_user_name(machine_number, user_id, user_name)
                try:
                    client.set_user_info(
                        machine_number=machine_number,
                        user_id=user_id,
                        timezone1=timezone1,
                        timezone2=timezone2,
                        group_no=group_no,
                        card_no=card_number,
                    )
                except MachineSdkError as exc:
                    print(f"WARN employee_code={code} user_id={user_id} set_user_info={exc}")
                summary.synced += 1
                print(f"OK employee_code={code} user_id={user_id} card={card_number} name={user_name}")
            except MachineSdkError as exc:
                summary.failed += 1
                print(f"FAIL employee_code={code} user_id={user_id} reason={exc}")
    finally:
        try:
            client.enable_device(machine_number, True)
        except MachineSdkError:
            pass
        client.disconnect(machine_number)
    return summary


def run_machine_sync(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    engine = create_db_engine(settings)
    if is_sqlite(engine):
        init_local_schema(engine)

    try:
        rows = list_employee_master_rows(
            engine,
            limit=args.limit,
            employee_code=args.employee_code,
        )
        if not rows:
            print("No employee rows found in employee_master for sync.")
            return 0

        machine_ip = args.machine_ip or settings.machine_sync_ip
        if not machine_ip:
            raise SystemExit("Machine IP is required. Set --machine-ip or config machine_sync_ip.")

        machine_port = args.machine_port if args.machine_port is not None else settings.machine_sync_port
        machine_password = (
            args.machine_password if args.machine_password is not None else settings.machine_sync_password
        )
        machine_number = args.machine_number if args.machine_number is not None else settings.machine_sync_machine_number
        timezone1 = args.timezone1 if args.timezone1 is not None else settings.machine_sync_timezone1
        timezone2 = args.timezone2 if args.timezone2 is not None else settings.machine_sync_timezone2
        group_no = args.group_no if args.group_no is not None else settings.machine_sync_group_no
        sdk_dll_path = args.sdk_dll or settings.machine_sdk_dll_path

        if args.dry_run:
            print(
                f"DRY-RUN rows={len(rows)} machine_ip={machine_ip} machine_port={machine_port} "
                f"machine_number={machine_number} sdk_dll={sdk_dll_path}"
            )
            for row in rows:
                code = str(row.get("employee_code") or "").strip()
                user_id = choose_machine_user_id(row)
                card = choose_card_number(row, user_id or 0) if user_id is not None else None
                name = choose_user_name(row)
                print(f"ROW employee_code={code} user_id={user_id} card={card} name={name}")
            return 0

        summary = sync_rows_to_machine(
            rows=rows,
            machine_ip=machine_ip,
            machine_port=machine_port,
            machine_password=machine_password,
            machine_number=machine_number,
            timezone1=timezone1,
            timezone2=timezone2,
            group_no=group_no,
            sdk_dll_path=sdk_dll_path,
        )
    finally:
        engine.dispose()

    print(
        f"Summary scanned={summary.scanned} synced={summary.synced} "
        f"skipped={summary.skipped} failed={summary.failed}"
    )
    return 0 if summary.failed == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Push employee_master rows from HR module DB to attendance machine via SBXPC SDK."
    )
    parser.add_argument("--config", default=None, help="Path to YAML config.")
    parser.add_argument("--employee-code", default=None, help="Sync only one employee code.")
    parser.add_argument("--limit", type=int, default=2000, help="Max employee rows to sync.")
    parser.add_argument("--machine-ip", default=None, help="Attendance machine IP.")
    parser.add_argument("--machine-port", type=int, default=None, help="Attendance machine port.")
    parser.add_argument("--machine-password", type=int, default=None, help="Attendance machine password.")
    parser.add_argument("--machine-number", type=int, default=None, help="SDK machine number (usually 1).")
    parser.add_argument("--timezone1", type=int, default=None, help="Default Timezone1 for SetUserInfo.")
    parser.add_argument("--timezone2", type=int, default=None, help="Default Timezone2 for SetUserInfo.")
    parser.add_argument("--group-no", type=int, default=None, help="Default GroupNo for SetUserInfo.")
    parser.add_argument("--sdk-dll", default=None, help="Path to SBXPCDLL64.dll or SBXPCDLL.dll.")
    parser.add_argument("--dry-run", action="store_true", help="Show rows that would sync without device calls.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(run_machine_sync(args))


if __name__ == "__main__":
    main()
