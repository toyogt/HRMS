from attendance_relay.machine_sync import (
    choose_card_number,
    choose_machine_user_id,
    choose_user_name,
    parse_unsigned_integer,
)


def test_parse_unsigned_integer_accepts_decimal_and_excel_float() -> None:
    assert parse_unsigned_integer("123", 9999) == 123
    assert parse_unsigned_integer("123.0", 9999) == 123
    assert parse_unsigned_integer("00000123", 9999) == 123


def test_parse_unsigned_integer_rejects_invalid_or_out_of_range() -> None:
    assert parse_unsigned_integer("", 100) is None
    assert parse_unsigned_integer("ABC", 100) is None
    assert parse_unsigned_integer("101", 100) is None


def test_choose_machine_user_id_prefers_normalized_value() -> None:
    row = {"employee_code_normalized": "22", "employee_code": "00000022"}
    assert choose_machine_user_id(row) == 22


def test_choose_card_number_prefers_card_columns() -> None:
    row = {
        "card_no": "5555",
        "proximity_card_no": "6666",
        "employee_code": "00000022",
        "employee_code_normalized": "22",
    }
    assert choose_card_number(row, fallback_user_id=22) == 5555


def test_choose_card_number_falls_back_to_user_id() -> None:
    row = {"card_no": "", "proximity_card_no": ""}
    assert choose_card_number(row, fallback_user_id=22) == 22


def test_choose_user_name_fallback_to_employee_code() -> None:
    row = {"employee_name": "", "employee_code": "00000022"}
    assert choose_user_name(row) == "00000022"

