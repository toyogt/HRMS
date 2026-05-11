SET XACT_ABORT ON;
GO

IF OBJECT_ID('dbo.attendance_outbox', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.attendance_outbox (
        id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        event_hash CHAR(64) NOT NULL,
        employee_code NVARCHAR(64) NOT NULL,
        log_datetime DATETIME2(0) NOT NULL,
        log_time TIME(0) NOT NULL,
        downloaded_at DATETIME2(0) NOT NULL,
        device_sn NVARCHAR(64) NOT NULL,
        status VARCHAR(20) NOT NULL CONSTRAINT DF_attendance_outbox_status DEFAULT ('PENDING'),
        attempt_count INT NOT NULL CONSTRAINT DF_attendance_outbox_attempt_count DEFAULT (0),
        max_retries INT NOT NULL CONSTRAINT DF_attendance_outbox_max_retries DEFAULT (5),
        next_attempt_at DATETIME2(0) NOT NULL CONSTRAINT DF_attendance_outbox_next_attempt_at DEFAULT (SYSUTCDATETIME()),
        processing_started_at DATETIME2(0) NULL,
        lease_until DATETIME2(0) NULL,
        sent_at DATETIME2(0) NULL,
        last_error NVARCHAR(1000) NULL,
        response_code INT NULL,
        response_body NVARCHAR(2000) NULL,
        created_at DATETIME2(0) NOT NULL CONSTRAINT DF_attendance_outbox_created_at DEFAULT (SYSUTCDATETIME()),
        updated_at DATETIME2(0) NOT NULL CONSTRAINT DF_attendance_outbox_updated_at DEFAULT (SYSUTCDATETIME())
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'UX_attendance_outbox_event_hash'
      AND object_id = OBJECT_ID('dbo.attendance_outbox')
)
BEGIN
    CREATE UNIQUE INDEX UX_attendance_outbox_event_hash
    ON dbo.attendance_outbox (event_hash);
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_attendance_outbox_status_next_attempt'
      AND object_id = OBJECT_ID('dbo.attendance_outbox')
)
BEGIN
    CREATE INDEX IX_attendance_outbox_status_next_attempt
    ON dbo.attendance_outbox (status, next_attempt_at, id)
    INCLUDE (attempt_count, max_retries, lease_until);
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_attendance_outbox_lease_until'
      AND object_id = OBJECT_ID('dbo.attendance_outbox')
)
BEGIN
    CREATE INDEX IX_attendance_outbox_lease_until
    ON dbo.attendance_outbox (lease_until, status);
END;
GO
