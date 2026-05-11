from attendance_relay.hashing import build_event_hash


def test_event_hash_stable() -> None:
    hash_a = build_event_hash(
        employee_code="E1001",
        log_datetime="2026-05-01 10:00:00",
        log_time="10:00:00",
        device_sn="SN-01",
    )
    hash_b = build_event_hash(
        employee_code="E1001",
        log_datetime="2026-05-01 10:00:00",
        log_time="10:00:00",
        device_sn="SN-01",
    )
    assert hash_a == hash_b
    assert len(hash_a) == 64
