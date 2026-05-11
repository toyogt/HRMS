SET XACT_ABORT ON;
GO

CREATE OR ALTER TRIGGER dbo.trg_tbl_realtime_glog_to_outbox
ON dbo.tbl_realtime_glog
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;

    ;WITH mapped AS (
        SELECT
            CAST(i.user_id AS NVARCHAR(64)) AS employee_code,
            TRY_CONVERT(
                DATETIME2(0),
                STUFF(STUFF(STUFF(STUFF(CAST(i.io_time AS VARCHAR(14)), 13, 0, ':'), 11, 0, ':'), 9, 0, ' '), 5, 0, '-'),
                120
            ) AS log_datetime,
            CAST(i.dev_id AS NVARCHAR(64)) AS device_sn,
            SYSDATETIME() AS downloaded_at
        FROM inserted i
    ),
    normalized AS (
        SELECT
            m.employee_code,
            m.log_datetime,
            CONVERT(TIME(0), m.log_datetime) AS log_time,
            m.downloaded_at,
            m.device_sn,
            CONVERT(
                CHAR(64),
                HASHBYTES(
                    'SHA2_256',
                    CONCAT(
                        m.employee_code, '|',
                        CONVERT(VARCHAR(19), m.log_datetime, 120), '|',
                        CONVERT(VARCHAR(8), CONVERT(TIME(0), m.log_datetime), 108), '|',
                        m.device_sn
                    )
                ),
                2
            ) AS event_hash
        FROM mapped m
        WHERE m.log_datetime IS NOT NULL
    )
    INSERT INTO dbo.attendance_outbox (
        event_hash,
        employee_code,
        log_datetime,
        log_time,
        downloaded_at,
        device_sn,
        status,
        attempt_count,
        max_retries,
        next_attempt_at,
        created_at,
        updated_at
    )
    SELECT
        n.event_hash,
        n.employee_code,
        n.log_datetime,
        n.log_time,
        n.downloaded_at,
        n.device_sn,
        'PENDING',
        0,
        5,
        n.downloaded_at,
        n.downloaded_at,
        n.downloaded_at
    FROM normalized n
    WHERE NOT EXISTS (
        SELECT 1
        FROM dbo.attendance_outbox o
        WHERE o.event_hash = n.event_hash
    );
END;
GO
