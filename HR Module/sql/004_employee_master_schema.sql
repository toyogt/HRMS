SET XACT_ABORT ON;
GO

IF OBJECT_ID('dbo.employee_master', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.employee_master (
        employee_code NVARCHAR(64) NOT NULL PRIMARY KEY,
        employee_code_normalized NVARCHAR(64) NOT NULL,
        employee_name NVARCHAR(200) NULL,
        father_name NVARCHAR(200) NULL,
        card_no NVARCHAR(64) NULL,
        proximity_card_no NVARCHAR(64) NULL,
        email_id NVARCHAR(200) NULL,
        phone_no NVARCHAR(64) NULL,
        department NVARCHAR(200) NULL,
        designation NVARCHAR(200) NULL,
        branch_name NVARCHAR(200) NULL,
        office_time_policy NVARCHAR(100) NULL,
        date_of_birth NVARCHAR(50) NULL,
        date_of_join NVARCHAR(50) NULL,
        shift_start_date NVARCHAR(50) NULL,
        shift_code NVARCHAR(100) NULL,
        weekly_off NVARCHAR(100) NULL,
        company_name NVARCHAR(200) NULL,
        created_at DATETIME2(0) NOT NULL CONSTRAINT DF_employee_master_created_at DEFAULT (SYSDATETIME()),
        updated_at DATETIME2(0) NOT NULL CONSTRAINT DF_employee_master_updated_at DEFAULT (SYSDATETIME())
    );
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.indexes
    WHERE name = 'IX_employee_master_employee_code_normalized'
      AND object_id = OBJECT_ID('dbo.employee_master')
)
BEGIN
    CREATE INDEX IX_employee_master_employee_code_normalized
    ON dbo.employee_master (employee_code_normalized);
END;
GO
