from __future__ import annotations

import argparse
from pathlib import Path

from attendance_relay.db import create_db_engine, init_local_schema, is_sqlite
from attendance_relay.master_data import read_employee_master_csv
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Import employee master data from CSV.")
    parser.add_argument("--csv", required=True, help="Path to employee master CSV file.")
    parser.add_argument("--config", default=None, help="Path to app YAML config.")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")

    settings = load_settings(args.config)
    engine = create_db_engine(settings)
    if is_sqlite(engine):
        init_local_schema(engine)
    repo = AttendanceRepository(engine)

    rows = read_employee_master_csv(csv_path)
    result = repo.upsert_employee_master_records(rows)
    print(
        f"Imported employee master rows={len(rows)} "
        f"inserted={result['inserted']} updated={result['updated']} skipped={result['skipped']}"
    )
    engine.dispose()


if __name__ == "__main__":
    main()
