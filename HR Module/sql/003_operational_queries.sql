/* Outbox status snapshot */
SELECT
    status,
    COUNT(*) AS total
FROM dbo.attendance_outbox
GROUP BY status
ORDER BY status;
GO

/* Due-to-send records */
SELECT TOP (100)
    id,
    employee_code,
    log_datetime,
    device_sn,
    status,
    attempt_count,
    max_retries,
    next_attempt_at,
    lease_until
FROM dbo.attendance_outbox
WHERE status IN ('PENDING', 'PROCESSING')
ORDER BY next_attempt_at, id;
GO

/* Final failures */
SELECT TOP (100)
    id,
    employee_code,
    log_datetime,
    device_sn,
    attempt_count,
    max_retries,
    last_error,
    updated_at
FROM dbo.attendance_outbox
WHERE status = 'FAILED'
ORDER BY updated_at DESC;
GO

/* Recover stale PROCESSING rows (example threshold 5 minutes) */
UPDATE dbo.attendance_outbox
SET
    status = 'PENDING',
    lease_until = NULL,
    updated_at = SYSDATETIME(),
    next_attempt_at = SYSDATETIME(),
    last_error = CONCAT(ISNULL(last_error, ''), CASE WHEN last_error IS NULL THEN '' ELSE ' | ' END, 'Recovered from stale PROCESSING')
WHERE status = 'PROCESSING'
  AND lease_until IS NOT NULL
  AND lease_until < DATEADD(MINUTE, -5, SYSDATETIME());
GO

/* Confirm dedup behavior */
SELECT
    event_hash,
    COUNT(*) AS hash_count
FROM dbo.attendance_outbox
GROUP BY event_hash
HAVING COUNT(*) > 1;
GO
