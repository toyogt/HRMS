from datetime import datetime
from pathlib import Path

from attendance_relay.db import create_db_engine, init_local_schema
from attendance_relay.master_data import normalize_employee_code, read_employee_master_csv
from attendance_relay.models import OutboxRecord
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings
from attendance_relay.worker import RelayWorker


class _DummyOutbound:
    def send(self, record, payload_override=None):  # noqa: ANN001
        raise RuntimeError("not used in this test")

    def close(self) -> None:
        return


def test_normalize_employee_code() -> None:
    assert normalize_employee_code("00000022") == "22"
    assert normalize_employee_code("E00000022") == "22"
    assert normalize_employee_code("EMP-12") == "EMP-12"


def test_read_csv_and_repo_lookup(tmp_path: Path) -> None:
    csv_path = tmp_path / "emp.csv"
    csv_path.write_text(
        "EmpName,EmpCode,Department,Designation,CompanyName\n"
        "SANJU KUMARI,00000022,PRODUCTION,MANPOWER,K95FoodsPvtLtd\n",
        encoding="utf-8",
    )
    rows = read_employee_master_csv(csv_path)
    assert len(rows) == 1
    assert rows[0]["employee_code"] == "00000022"

    settings = Settings(db_url=f"sqlite:///{tmp_path / 'master.db'}", outbound_api_key="test-key")
    engine = create_db_engine(settings)
    init_local_schema(engine)
    repo = AttendanceRepository(engine)
    result = repo.upsert_employee_master_records(rows)
    assert result["inserted"] == 1

    by_exact = repo.find_employee_master("00000022")
    by_normalized = repo.find_employee_master("22")
    assert by_exact is not None
    assert by_normalized is not None
    assert by_normalized["employee_name"] == "SANJU KUMARI"
    listed = repo.list_employee_master(employee_code="22", department="PRODUCTION", limit=10)
    assert len(listed) == 1
    assert listed[0]["employee_code"] == "00000022"
    engine.dispose()


def test_worker_payload_enriched_from_master(tmp_path: Path) -> None:
    settings = Settings(
        db_url=f"sqlite:///{tmp_path / 'payload.db'}",
        outbound_api_key="test-key",
        outbound_include_extended_fields=True,
        outbound_device_name_default="Realtime Device",
        outbound_device_no_default="1",
    )
    engine = create_db_engine(settings)
    init_local_schema(engine)
    repo = AttendanceRepository(engine)
    repo.upsert_employee_master_records(
        [
            {
                "employee_code": "00000022",
                "employee_code_normalized": "22",
                "employee_name": "SANJU KUMARI",
                "department": "PRODUCTION",
                "designation": "MANPOWER",
                "company_name": "K95FoodsPvtLtd",
                "card_no": "00000022",
            }
        ]
    )
    worker = RelayWorker(settings=settings, repo=repo, outbound=_DummyOutbound())
    payload = worker._build_outbound_payload(
        OutboxRecord(
            id=1,
            event_hash="x",
            employee_code="22",
            log_datetime=datetime(2026, 5, 1, 21, 0, 0),
            log_time="21:00:00",
            downloaded_at=datetime(2026, 5, 1, 21, 0, 5),
            device_sn="SN-01",
            attempt_count=0,
        )
    )
    assert payload["employee_code"] == "00000022"
    assert payload["employee_name"] == "SANJU KUMARI"
    assert payload["log_date"] == "2026-05-01"
    assert payload["device_name"] == "Realtime Device"
    assert payload["device_no"] == "1"
    engine.dispose()
