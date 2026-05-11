from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from attendance_relay.master_data import normalize_employee_code
from attendance_relay.models import MachinePunch, OutboxRecord
from attendance_relay.time_utils import format_datetime

_MASTER_TABLES: dict[str, str] = {
    "department": "department_master",
    "departments": "department_master",
    "designation": "designation_master",
    "designations": "designation_master",
    "office_time_policy": "office_time_policy_master",
    "office_time_policies": "office_time_policy_master",
    "office-time-policy": "office_time_policy_master",
    "office-time-policies": "office_time_policy_master",
    "company": "company_master",
    "companies": "company_master",
    "company_name": "company_master",
    "company_names": "company_master",
    "branch": "branch_master",
    "branches": "branch_master",
    "branch_name": "branch_master",
    "branch_names": "branch_master",
    "shift_code": "shift_code_master",
    "shift_codes": "shift_code_master",
    "shift-code": "shift_code_master",
    "shift-codes": "shift_code_master",
}

_MASTER_TABLES_CANONICAL: dict[str, str] = {
    "departments": "department_master",
    "designations": "designation_master",
    "office_time_policies": "office_time_policy_master",
    "companies": "company_master",
    "branches": "branch_master",
    "shift_codes": "shift_code_master",
}


class AttendanceRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @property
    def is_sqlite(self) -> bool:
        return self.engine.dialect.name == "sqlite"

    def persist_punch(self, punch: MachinePunch, event_hash: str, max_retries: int) -> tuple[int, bool]:
        now = format_datetime(punch.downloaded_at)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tbl_realtime_glog (
                      employee_code, log_datetime, log_time, downloaded_at, device_sn,
                      raw_user_id, raw_io_time, source_ip, raw_preview, created_at
                    ) VALUES (
                      :employee_code, :log_datetime, :log_time, :downloaded_at, :device_sn,
                      :raw_user_id, :raw_io_time, :source_ip, :raw_preview, :created_at
                    )
                    """
                ),
                {
                    "employee_code": punch.employee_code,
                    "log_datetime": format_datetime(punch.log_datetime),
                    "log_time": punch.log_time,
                    "downloaded_at": format_datetime(punch.downloaded_at),
                    "device_sn": punch.device_sn,
                    "raw_user_id": punch.raw_user_id,
                    "raw_io_time": punch.raw_io_time,
                    "source_ip": punch.source_ip,
                    "raw_preview": punch.raw_preview,
                    "created_at": now,
                },
            )

            deduped = False
            try:
                conn.execute(
                    text(
                        """
                        INSERT INTO attendance_outbox (
                          event_hash, employee_code, log_datetime, log_time, downloaded_at, device_sn,
                          status, attempt_count, max_retries, next_attempt_at, created_at, updated_at
                        ) VALUES (
                          :event_hash, :employee_code, :log_datetime, :log_time, :downloaded_at, :device_sn,
                          'PENDING', 0, :max_retries, :next_attempt_at, :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        "event_hash": event_hash,
                        "employee_code": punch.employee_code,
                        "log_datetime": format_datetime(punch.log_datetime),
                        "log_time": punch.log_time,
                        "downloaded_at": format_datetime(punch.downloaded_at),
                        "device_sn": punch.device_sn,
                        "max_retries": max_retries,
                        "next_attempt_at": now,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            except IntegrityError:
                deduped = True

            row = conn.execute(text("SELECT last_insert_rowid() AS id")) if self.is_sqlite else None
            inserted_id = int(row.scalar()) if row is not None else 0
            return inserted_id, deduped

    def claim_outbox_batch(
        self,
        *,
        limit: int,
        now: datetime,
        lease_seconds: int,
    ) -> list[OutboxRecord]:
        now_s = format_datetime(now)
        lease_until = format_datetime(now + timedelta(seconds=lease_seconds))

        if self.is_sqlite:
            return self._claim_sqlite(limit=limit, now_s=now_s, lease_until=lease_until)
        return self._claim_mssql(limit=limit, now_s=now_s, lease_until=lease_until)

    def _claim_sqlite(self, *, limit: int, now_s: str, lease_until: str) -> list[OutboxRecord]:
        with self.engine.begin() as conn:
            eligible_ids = [
                int(row.id)
                for row in conn.execute(
                    text(
                        """
                        SELECT id
                        FROM attendance_outbox
                        WHERE (
                          status = 'PENDING'
                          OR (status = 'PROCESSING' AND lease_until IS NOT NULL AND lease_until < :now_s)
                        )
                        AND attempt_count < max_retries
                        AND next_attempt_at <= :now_s
                        ORDER BY id
                        LIMIT :batch_limit
                        """
                    ),
                    {"now_s": now_s, "batch_limit": limit},
                )
            ]
            if not eligible_ids:
                return []

            for outbox_id in eligible_ids:
                conn.execute(
                    text(
                        """
                        UPDATE attendance_outbox
                        SET status = 'PROCESSING',
                            processing_started_at = :now_s,
                            lease_until = :lease_until,
                            updated_at = :now_s
                        WHERE id = :outbox_id
                        """
                    ),
                    {"now_s": now_s, "lease_until": lease_until, "outbox_id": outbox_id},
                )

            rows: list[OutboxRecord] = []
            for outbox_id in eligible_ids:
                row = conn.execute(
                    text(
                        """
                        SELECT id, event_hash, employee_code, log_datetime, log_time, downloaded_at, device_sn, attempt_count
                        FROM attendance_outbox
                        WHERE id = :outbox_id
                        """
                    ),
                    {"outbox_id": outbox_id},
                ).mappings().first()
                if row:
                    rows.append(_row_to_outbox_record(row))
            return rows

    def _claim_mssql(self, *, limit: int, now_s: str, lease_until: str) -> list[OutboxRecord]:
        query = text(
            f"""
            ;WITH cte AS (
              SELECT TOP ({int(limit)}) *
              FROM attendance_outbox WITH (ROWLOCK, UPDLOCK, READPAST)
              WHERE (
                status = 'PENDING'
                OR (status = 'PROCESSING' AND lease_until IS NOT NULL AND lease_until < :now_s)
              )
              AND attempt_count < max_retries
              AND next_attempt_at <= :now_s
              ORDER BY id
            )
            UPDATE cte
            SET status = 'PROCESSING',
                processing_started_at = :now_s,
                lease_until = :lease_until,
                updated_at = :now_s
            OUTPUT
              INSERTED.id,
              INSERTED.event_hash,
              INSERTED.employee_code,
              INSERTED.log_datetime,
              INSERTED.log_time,
              INSERTED.downloaded_at,
              INSERTED.device_sn,
              INSERTED.attempt_count
            """
        )
        with self.engine.begin() as conn:
            result = conn.execute(query, {"now_s": now_s, "lease_until": lease_until}).mappings().all()
        return [_row_to_outbox_record(row) for row in result]

    def mark_sent(self, *, outbox_id: int, response_code: int | None, response_body: str | None, now: datetime) -> None:
        now_s = format_datetime(now)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE attendance_outbox
                    SET status = 'SENT',
                        sent_at = :sent_at,
                        response_code = :response_code,
                        response_body = :response_body,
                        last_error = NULL,
                        updated_at = :updated_at
                    WHERE id = :outbox_id
                    """
                ),
                {
                    "sent_at": now_s,
                    "response_code": response_code,
                    "response_body": response_body,
                    "updated_at": now_s,
                    "outbox_id": outbox_id,
                },
            )

    def mark_failed(
        self,
        *,
        outbox_id: int,
        attempt_count: int,
        error_message: str,
        next_attempt_at: datetime | None,
        now: datetime,
        max_retries: int,
    ) -> None:
        now_s = format_datetime(now)
        is_final = attempt_count >= max_retries or next_attempt_at is None
        status = "FAILED" if is_final else "PENDING"
        next_s = format_datetime(next_attempt_at) if next_attempt_at else now_s

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE attendance_outbox
                    SET status = :status,
                        attempt_count = :attempt_count,
                        last_error = :last_error,
                        next_attempt_at = :next_attempt_at,
                        lease_until = NULL,
                        updated_at = :updated_at
                    WHERE id = :outbox_id
                    """
                ),
                {
                    "status": status,
                    "attempt_count": attempt_count,
                    "last_error": error_message[:1000],
                    "next_attempt_at": next_s,
                    "updated_at": now_s,
                    "outbox_id": outbox_id,
                },
            )

    def get_outbox_counts(self) -> dict[str, int]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM attendance_outbox
                    GROUP BY status
                    """
                )
            ).all()
        counts = {"PENDING": 0, "PROCESSING": 0, "SENT": 0, "FAILED": 0}
        for status, count in rows:
            counts[str(status)] = int(count)
        return counts

    def upsert_employee_master_records(self, records: list[dict[str, str]]) -> dict[str, int]:
        if not records:
            return {"inserted": 0, "updated": 0, "skipped": 0}

        update_stmt = text(
            """
            UPDATE employee_master
            SET employee_code_normalized = :employee_code_normalized,
                employee_name = :employee_name,
                father_name = :father_name,
                card_no = :card_no,
                proximity_card_no = :proximity_card_no,
                email_id = :email_id,
                phone_no = :phone_no,
                department = :department,
                designation = :designation,
                branch_name = :branch_name,
                office_time_policy = :office_time_policy,
                date_of_birth = :date_of_birth,
                date_of_join = :date_of_join,
                shift_start_date = :shift_start_date,
                shift_code = :shift_code,
                weekly_off = :weekly_off,
                company_name = :company_name,
                updated_at = :updated_at
            WHERE employee_code = :employee_code
            """
        )

        insert_stmt = text(
            """
            INSERT INTO employee_master (
              employee_code,
              employee_code_normalized,
              employee_name,
              father_name,
              card_no,
              proximity_card_no,
              email_id,
              phone_no,
              department,
              designation,
              branch_name,
              office_time_policy,
              date_of_birth,
              date_of_join,
              shift_start_date,
              shift_code,
              weekly_off,
              company_name,
              created_at,
              updated_at
            ) VALUES (
              :employee_code,
              :employee_code_normalized,
              :employee_name,
              :father_name,
              :card_no,
              :proximity_card_no,
              :email_id,
              :phone_no,
              :department,
              :designation,
              :branch_name,
              :office_time_policy,
              :date_of_birth,
              :date_of_join,
              :shift_start_date,
              :shift_code,
              :weekly_off,
              :company_name,
              :created_at,
              :updated_at
            )
            """
        )

        inserted = 0
        updated = 0
        skipped = 0
        timestamp = format_datetime(datetime.now().replace(microsecond=0))
        with self.engine.begin() as conn:
            for record in records:
                employee_code = (record.get("employee_code") or "").strip()
                employee_code_normalized = (record.get("employee_code_normalized") or "").strip()
                if not employee_code:
                    skipped += 1
                    continue
                if not employee_code_normalized:
                    employee_code_normalized = normalize_employee_code(employee_code)
                if not employee_code_normalized:
                    skipped += 1
                    continue

                params = {
                    "employee_code": employee_code,
                    "employee_code_normalized": employee_code_normalized,
                    "employee_name": record.get("employee_name"),
                    "father_name": record.get("father_name"),
                    "card_no": record.get("card_no"),
                    "proximity_card_no": record.get("proximity_card_no"),
                    "email_id": record.get("email_id"),
                    "phone_no": record.get("phone_no"),
                    "department": record.get("department"),
                    "designation": record.get("designation"),
                    "branch_name": record.get("branch_name"),
                    "office_time_policy": record.get("office_time_policy"),
                    "date_of_birth": record.get("date_of_birth"),
                    "date_of_join": record.get("date_of_join"),
                    "shift_start_date": record.get("shift_start_date"),
                    "shift_code": record.get("shift_code"),
                    "weekly_off": record.get("weekly_off"),
                    "company_name": record.get("company_name"),
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }

                result = conn.execute(update_stmt, params)
                if int(result.rowcount or 0) > 0:
                    updated += 1
                    continue

                try:
                    conn.execute(insert_stmt, params)
                    inserted += 1
                except IntegrityError:
                    conn.execute(update_stmt, params)
                    updated += 1

        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    def find_employee_master(self, employee_code: str) -> dict[str, Any] | None:
        code = (employee_code or "").strip()
        if not code:
            return None

        normalized = normalize_employee_code(code)
        if self.is_sqlite:
            query = text(
                """
                SELECT
                  employee_code,
                  employee_code_normalized,
                  employee_name,
                  father_name,
                  card_no,
                  proximity_card_no,
                  email_id,
                  phone_no,
                  department,
                  designation,
                  branch_name,
                  office_time_policy,
                  date_of_birth,
                  date_of_join,
                  shift_start_date,
                  shift_code,
                  weekly_off,
                  company_name
                FROM employee_master
                WHERE employee_code = :employee_code
                   OR employee_code_normalized = :normalized
                ORDER BY CASE WHEN employee_code = :employee_code THEN 0 ELSE 1 END
                LIMIT 1
                """
            )
        else:
            query = text(
                """
                SELECT TOP (1)
                  employee_code,
                  employee_code_normalized,
                  employee_name,
                  father_name,
                  card_no,
                  proximity_card_no,
                  email_id,
                  phone_no,
                  department,
                  designation,
                  branch_name,
                  office_time_policy,
                  date_of_birth,
                  date_of_join,
                  shift_start_date,
                  shift_code,
                  weekly_off,
                  company_name
                FROM employee_master
                WHERE employee_code = :employee_code
                   OR employee_code_normalized = :normalized
                ORDER BY CASE WHEN employee_code = :employee_code THEN 0 ELSE 1 END
                """
            )
        with self.engine.begin() as conn:
            row = conn.execute(query, {"employee_code": code, "normalized": normalized}).mappings().first()
        return dict(row) if row else None

    def list_employee_master(
        self,
        *,
        employee_code: str | None = None,
        department: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        code = (employee_code or "").strip() or None
        normalized = normalize_employee_code(code or "") if code else None
        dept = (department or "").strip() or None
        safe_limit = max(1, min(int(limit), 5000))
        params: dict[str, Any] = {
            "employee_code": code,
            "employee_code_normalized": normalized,
            "department": dept,
        }

        select_columns = """
          employee_code,
          employee_code_normalized,
          employee_name,
          father_name,
          card_no,
          proximity_card_no,
          email_id,
          phone_no,
          department,
          designation,
          branch_name,
          office_time_policy,
          date_of_birth,
          date_of_join,
          shift_start_date,
          shift_code,
          weekly_off,
          company_name
        """
        where_clause = """
        WHERE (
          :employee_code IS NULL
          OR employee_code = :employee_code
          OR employee_code_normalized = :employee_code_normalized
        )
          AND (:department IS NULL OR department = :department)
        """

        if self.is_sqlite:
            query = text(
                f"""
                SELECT {select_columns}
                FROM employee_master
                {where_clause}
                ORDER BY employee_code
                LIMIT :row_limit
                """
            )
            params["row_limit"] = safe_limit
        else:
            query = text(
                f"""
                SELECT TOP ({safe_limit}) {select_columns}
                FROM employee_master
                {where_clause}
                ORDER BY employee_code
                """
            )

        with self.engine.begin() as conn:
            rows = conn.execute(query, params).mappings().all()
        return [dict(row) for row in rows]

    def delete_employee_master(self, employee_code: str) -> bool:
        code = (employee_code or "").strip()
        if not code:
            return False
        normalized = normalize_employee_code(code)
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    DELETE FROM employee_master
                    WHERE employee_code = :employee_code
                       OR employee_code_normalized = :normalized
                    """
                ),
                {"employee_code": code, "normalized": normalized},
            )
        return int(result.rowcount or 0) > 0

    def get_supported_master_types(self) -> list[str]:
        return sorted(_MASTER_TABLES_CANONICAL.keys())

    def upsert_master_value(
        self,
        *,
        master_type: str,
        code: str,
        name: str,
        description: str | None = None,
        is_active: bool = True,
    ) -> dict[str, Any]:
        table = self._resolve_master_table(master_type)
        normalized_code = _normalize_master_code(code)
        if not normalized_code:
            raise ValueError("code is required")
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("name is required")

        timestamp = format_datetime(datetime.now().replace(microsecond=0))
        params = {
            "code": normalized_code,
            "name": clean_name,
            "description": (description or "").strip(),
            "is_active": 1 if is_active else 0,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        update_stmt = text(
            f"""
            UPDATE {table}
            SET name = :name,
                description = :description,
                is_active = :is_active,
                updated_at = :updated_at
            WHERE code = :code
            """
        )
        insert_stmt = text(
            f"""
            INSERT INTO {table} (
              code,
              name,
              description,
              is_active,
              created_at,
              updated_at
            ) VALUES (
              :code,
              :name,
              :description,
              :is_active,
              :created_at,
              :updated_at
            )
            """
        )

        action = "created"
        with self.engine.begin() as conn:
            updated = conn.execute(update_stmt, params)
            if int(updated.rowcount or 0) > 0:
                action = "updated"
            else:
                try:
                    conn.execute(insert_stmt, params)
                except IntegrityError:
                    conn.execute(update_stmt, params)
                    action = "updated"

        row = self.find_master_value(master_type=master_type, code=normalized_code)
        if not row:
            raise ValueError("unable to load master record after upsert")
        row["action"] = action
        return row

    def list_master_values(
        self,
        *,
        master_type: str,
        is_active: bool | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        table = self._resolve_master_table(master_type)
        safe_limit = max(1, min(int(limit), 5000))
        params: dict[str, Any] = {
            "is_active": (1 if is_active else 0) if is_active is not None else None,
        }

        select_columns = """
          code,
          name,
          description,
          is_active,
          created_at,
          updated_at
        """
        where_clause = "WHERE (:is_active IS NULL OR is_active = :is_active)"

        if self.is_sqlite:
            query = text(
                f"""
                SELECT {select_columns}
                FROM {table}
                {where_clause}
                ORDER BY code
                LIMIT :row_limit
                """
            )
            params["row_limit"] = safe_limit
        else:
            query = text(
                f"""
                SELECT TOP ({safe_limit}) {select_columns}
                FROM {table}
                {where_clause}
                ORDER BY code
                """
            )

        with self.engine.begin() as conn:
            rows = conn.execute(query, params).mappings().all()
        return [_normalize_master_row(dict(row)) for row in rows]

    def find_master_value(self, *, master_type: str, code: str) -> dict[str, Any] | None:
        table = self._resolve_master_table(master_type)
        normalized_code = _normalize_master_code(code)
        if not normalized_code:
            return None

        if self.is_sqlite:
            query = text(
                f"""
                SELECT
                  code,
                  name,
                  description,
                  is_active,
                  created_at,
                  updated_at
                FROM {table}
                WHERE code = :code
                LIMIT 1
                """
            )
        else:
            query = text(
                f"""
                SELECT TOP (1)
                  code,
                  name,
                  description,
                  is_active,
                  created_at,
                  updated_at
                FROM {table}
                WHERE code = :code
                """
            )
        with self.engine.begin() as conn:
            row = conn.execute(query, {"code": normalized_code}).mappings().first()
        return _normalize_master_row(dict(row)) if row else None

    def patch_master_value(
        self,
        *,
        master_type: str,
        code: str,
        patch: dict[str, Any],
    ) -> dict[str, Any] | None:
        current = self.find_master_value(master_type=master_type, code=code)
        if not current:
            return None

        next_name = current["name"]
        next_description = current["description"]
        next_is_active = bool(current["is_active"])

        if "name" in patch:
            clean_name = str(patch.get("name") or "").strip()
            if not clean_name:
                raise ValueError("name cannot be empty")
            next_name = clean_name
        if "description" in patch:
            next_description = str(patch.get("description") or "").strip()
        if "is_active" in patch:
            next_is_active = bool(patch.get("is_active"))

        table = self._resolve_master_table(master_type)
        timestamp = format_datetime(datetime.now().replace(microsecond=0))
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    UPDATE {table}
                    SET name = :name,
                        description = :description,
                        is_active = :is_active,
                        updated_at = :updated_at
                    WHERE code = :code
                    """
                ),
                {
                    "code": current["code"],
                    "name": next_name,
                    "description": next_description,
                    "is_active": 1 if next_is_active else 0,
                    "updated_at": timestamp,
                },
            )
        return self.find_master_value(master_type=master_type, code=current["code"])

    def delete_master_value(self, *, master_type: str, code: str) -> bool:
        table = self._resolve_master_table(master_type)
        normalized_code = _normalize_master_code(code)
        if not normalized_code:
            return False
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    f"""
                    DELETE FROM {table}
                    WHERE code = :code
                    """
                ),
                {"code": normalized_code},
            )
        return int(result.rowcount or 0) > 0

    def _resolve_master_table(self, master_type: str) -> str:
        normalized = _normalize_master_type(master_type)
        table = _MASTER_TABLES.get(normalized)
        if table:
            return table
        supported = ", ".join(sorted(_MASTER_TABLES_CANONICAL.keys()))
        raise ValueError(f"unsupported master_type: {master_type}. Supported: {supported}")

    def list_attendance(
        self,
        *,
        limit: int = 500,
        employee_code: str | None = None,
        device_sn: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 5000))
        employee_code_normalized = normalize_employee_code(employee_code or "") if employee_code else None
        bind_values = {
            "employee_code": employee_code,
            "employee_code_normalized": employee_code_normalized,
            "device_sn": device_sn,
        }

        if self.is_sqlite:
            query = text(
                """
                SELECT
                    g.id,
                    g.employee_code,
                    g.log_datetime,
                    g.log_time,
                    g.downloaded_at,
                    g.device_sn,
                    g.source_ip,
                    g.created_at,
                    em.employee_name
                FROM tbl_realtime_glog g
                LEFT JOIN employee_master em
                  ON em.employee_code = g.employee_code
                WHERE (
                  :employee_code IS NULL
                  OR g.employee_code = :employee_code
                  OR g.employee_code = :employee_code_normalized
                )
                  AND (:device_sn IS NULL OR g.device_sn = :device_sn)
                ORDER BY g.id DESC
                LIMIT :row_limit
                """
            )
            bind_values["row_limit"] = safe_limit
            with self.engine.begin() as conn:
                rows = conn.execute(query, bind_values).mappings().all()
        else:
            query = text(
                f"""
                SELECT TOP ({safe_limit})
                    g.id,
                    g.employee_code,
                    g.log_datetime,
                    g.log_time,
                    g.downloaded_at,
                    g.device_sn,
                    g.source_ip,
                    g.created_at,
                    em.employee_name
                FROM tbl_realtime_glog g
                LEFT JOIN employee_master em
                  ON em.employee_code = g.employee_code
                WHERE (
                  :employee_code IS NULL
                  OR g.employee_code = :employee_code
                  OR g.employee_code = :employee_code_normalized
                )
                  AND (:device_sn IS NULL OR g.device_sn = :device_sn)
                ORDER BY g.id DESC
                """
            )
            with self.engine.begin() as conn:
                rows = conn.execute(query, bind_values).mappings().all()

        output = [dict(row) for row in rows]
        for row in output:
            if row.get("employee_name"):
                continue
            master = self.find_employee_master(str(row.get("employee_code") or ""))
            if master:
                row["employee_name"] = master.get("employee_name")
        return output

    def get_attendance_total(self) -> int:
        with self.engine.begin() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM tbl_realtime_glog")).scalar_one()
        return int(total)


def _normalize_master_type(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _normalize_master_code(value: str) -> str:
    return str(value or "").strip().upper()


def _normalize_master_row(row: dict[str, Any]) -> dict[str, Any]:
    row["is_active"] = bool(row.get("is_active"))
    return row


def _row_to_outbox_record(row: Any) -> OutboxRecord:
    return OutboxRecord(
        id=int(row["id"]),
        event_hash=str(row["event_hash"]),
        employee_code=str(row["employee_code"]),
        log_datetime=_safe_parse_datetime(row["log_datetime"]),
        log_time=str(row["log_time"]),
        downloaded_at=_safe_parse_datetime(row["downloaded_at"]),
        device_sn=str(row["device_sn"]),
        attempt_count=int(row["attempt_count"]),
    )


def _safe_parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    if isinstance(value, str):
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")
    raise TypeError(f"Unexpected datetime value: {value!r}")
