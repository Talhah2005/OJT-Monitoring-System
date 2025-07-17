-- Create the database
CREATE DATABASE JobTrainingMonitoring;
GO

USE JobTrainingMonitoring;
GO

SELECT * INTO Users_Backup FROM Users;
GO


-- Create Users table first (referenced by other tables)
CREATE TABLE Users (
    user_id INT IDENTITY(1,1) PRIMARY KEY,
    username NVARCHAR(50) NOT NULL UNIQUE,
    password NVARCHAR(100) NOT NULL,
    email NVARCHAR(100) NOT NULL UNIQUE,
    role NVARCHAR(20) NOT NULL CHECK (role IN ('admin', 'supervisor', 'trainee')),
    department NVARCHAR(50) NOT NULL,
    created_at DATETIME DEFAULT GETDATE(),
    is_active BIT DEFAULT 1
);
GO

-- Create TrainingPrograms table (referenced by TrainingSessions)
CREATE TABLE TrainingPrograms (
    program_id INT IDENTITY(1,1) PRIMARY KEY,
    program_name NVARCHAR(100) NOT NULL,
    description NVARCHAR(500),
    duration_days INT NOT NULL,
    required_skills NVARCHAR(255),
    certification NVARCHAR(100)
);
GO


-- Add status column to TrainingPrograms if it doesn't exist
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.COLUMNS 
               WHERE TABLE_NAME = 'TrainingPrograms' AND COLUMN_NAME = 'status')
BEGIN
    ALTER TABLE TrainingPrograms ADD status VARCHAR(20) DEFAULT 'Active';
END

-- Add program_id column to Trainees if it doesn't exist


-- Create Trainees table
CREATE TABLE Trainees (
    trainee_id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL FOREIGN KEY REFERENCES Users(user_id),
    full_name NVARCHAR(100) NOT NULL,
	 password NVARCHAR(100) NOT NULL,
    email NVARCHAR(100) NOT NULL UNIQUE,
    position NVARCHAR(50),
    training_status NVARCHAR(20) DEFAULT 'Started',
    start_date DATE,
    end_date DATE,
    profile_image NVARCHAR(255)
);
GO

IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.COLUMNS 
               WHERE TABLE_NAME = 'Trainees' AND COLUMN_NAME = 'program_id')
BEGIN
    ALTER TABLE Trainees ADD program_id INT NULL;
END

UPDATE Trainees
SET training_status = 'Started'
-- Create QR codes table
CREATE TABLE QRCodes (
    qr_id INT IDENTITY(1,1) PRIMARY KEY,
    qr_code NVARCHAR(100) UNIQUE NOT NULL,

    entity_type NVARCHAR(20) NOT NULL CHECK (entity_type IN ('trainee', 'station', 'equipment', 'session')),
    entity_id INT NOT NULL,
    creation_date DATETIME DEFAULT GETDATE(),
    expiration_date DATETIME,
    is_active BIT DEFAULT 1
);
GO

-- Create Training sessions table
CREATE TABLE TrainingSessions (
    session_id INT IDENTITY(1,1) PRIMARY KEY,
    program_id INT FOREIGN KEY REFERENCES TrainingPrograms(program_id),
    supervisor_id INT FOREIGN KEY REFERENCES Users(user_id),
    session_name NVARCHAR(100) NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    location NVARCHAR(100),
    status NVARCHAR(20) DEFAULT 'Scheduled' CHECK (status IN ('Scheduled', 'In Progress', 'Completed', 'Cancelled'))
);
GO
-- Create Admin table
CREATE TABLE Admins (
    admin_id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL FOREIGN KEY REFERENCES Users(user_id),
    full_name NVARCHAR(100) NOT NULL,
    email NVARCHAR(100) NOT NULL UNIQUE,
    position NVARCHAR(50),
    department NVARCHAR(50) NOT NULL,
    created_at DATETIME DEFAULT GETDATE(),
    is_active BIT DEFAULT 1
);
GO

-- Create Supervisor table
CREATE TABLE Supervisors (
    supervisor_id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL FOREIGN KEY REFERENCES Users(user_id),
    full_name NVARCHAR(100) NOT NULL,
    email NVARCHAR(100) NOT NULL UNIQUE,
    position NVARCHAR(50),
    department NVARCHAR(50) NOT NULL,
    created_at DATETIME DEFAULT GETDATE(),
    is_active BIT DEFAULT 1
);
GO

-- Create Attendance/Check-ins table
CREATE TABLE CheckIns (
    checkin_id INT IDENTITY(1,1) PRIMARY KEY,
    trainee_id INT FOREIGN KEY REFERENCES Trainees(trainee_id),
    qr_code_id INT FOREIGN KEY REFERENCES QRCodes(qr_id),
    session_id INT FOREIGN KEY REFERENCES TrainingSessions(session_id),
    checkin_time DATETIME DEFAULT GETDATE(),
    checkout_time DATETIME,
    location NVARCHAR(100),
    attendance_status NVARCHAR(20) DEFAULT 'Present' CHECK (attendance_status IN ('Present', 'Late', 'Half Day', 'Absent'))
);
GO

-- Create indexes for CheckIns
CREATE INDEX IX_CheckIns_TraineeId ON CheckIns(trainee_id);
CREATE INDEX IX_CheckIns_QRCode ON CheckIns(qr_code_id);
CREATE INDEX IX_CheckIns_Session ON CheckIns(session_id);
GO

-- Create TraineeAttendance table for detailed attendance tracking
CREATE TABLE TraineeAttendance (
    attendance_id INT IDENTITY(1,1) PRIMARY KEY,
    trainee_id INT NOT NULL,
    attendance_date DATE NOT NULL DEFAULT CAST(GETDATE() AS DATE),
    checkin_time DATETIME NULL,
    checkout_time DATETIME NULL,
    checkin_location NVARCHAR(100) NULL,
    checkout_location NVARCHAR(100) NULL,
    checkin_marked_by INT NULL,
    checkout_marked_by INT NULL,
    qr_code_used NVARCHAR(100) NULL,
    attendance_status NVARCHAR(20) DEFAULT 'Present' CHECK (attendance_status IN ('Present', 'Late', 'Half Day', 'Absent')),
    FOREIGN KEY (trainee_id) REFERENCES Trainees(trainee_id),
    FOREIGN KEY (checkin_marked_by) REFERENCES Users(user_id),
    FOREIGN KEY (checkout_marked_by) REFERENCES Users(user_id),
    FOREIGN KEY (qr_code_used) REFERENCES QRCodes(qr_code)
);
GO

-- Create indexes for faster attendance queries
CREATE INDEX IX_TraineeAttendance_Date ON TraineeAttendance(attendance_date);
CREATE INDEX IX_TraineeAttendance_Trainee ON TraineeAttendance(trainee_id);
GO

-- Create stored procedure for marking attendance
CREATE OR ALTER PROCEDURE sp_MarkTraineeAttendance
    @qr_code NVARCHAR(100),
    @location NVARCHAR(100),
    @marked_by_user_id INT
AS
BEGIN
    SET NOCOUNT ON;
    
    DECLARE @trainee_id INT;
    DECLARE @current_time DATETIME = GETDATE();
    DECLARE @attendance_id INT;
    
    -- Get trainee ID from QR code
    SELECT @trainee_id = entity_id
    FROM QRCodes
    WHERE qr_code = @qr_code
    AND entity_type = 'trainee'
    AND is_active = 1;
    
    IF @trainee_id IS NULL
        THROW 50001, 'Invalid or expired QR code', 1;
    
    -- Check for existing attendance today
    SELECT @attendance_id = attendance_id
    FROM TraineeAttendance
    WHERE trainee_id = @trainee_id
    AND CAST(attendance_date AS DATE) = CAST(@current_time AS DATE);
    
    IF @attendance_id IS NULL
    BEGIN
        -- Create new attendance record (Check-in)
        INSERT INTO TraineeAttendance (
            trainee_id,
            attendance_date,
            checkin_time,
            checkin_location,
            checkin_marked_by,
            qr_code_used
        )
        VALUES (
            @trainee_id,
            @current_time,
            @current_time,
            @location,
            @marked_by_user_id,
            @qr_code
        );
        
        -- Set attendance status based on check-in time
        UPDATE TraineeAttendance
        SET attendance_status = 
            CASE 
                WHEN DATEPART(HOUR, checkin_time) >= 9 THEN 'Late'
                ELSE 'Present'
            END
        WHERE attendance_id = SCOPE_IDENTITY();
    END
    ELSE
    BEGIN
        -- Update existing attendance record (Check-out)
        UPDATE TraineeAttendance
        SET checkout_time = @current_time,
            checkout_location = @location,
            checkout_marked_by = @marked_by_user_id,
            attendance_status = 
                CASE 
                    WHEN DATEDIFF(HOUR, checkin_time, @current_time) < 4 THEN 'Half Day'
                    ELSE attendance_status
                END
        WHERE attendance_id = @attendance_id;
    END
    
    -- Return the updated attendance record
    SELECT 
        t.full_name,
        ta.attendance_date,
        ta.checkin_time,
        ta.checkout_time,
        ta.attendance_status,
        s_in.full_name as checked_in_by,
        s_out.full_name as checked_out_by
    FROM TraineeAttendance ta
    JOIN Trainees t ON ta.trainee_id = t.trainee_id
    LEFT JOIN Users u_in ON ta.checkin_marked_by = u_in.user_id
    LEFT JOIN Supervisors s_in ON u_in.user_id = s_in.user_id
    LEFT JOIN Users u_out ON ta.checkout_marked_by = u_out.user_id
    LEFT JOIN Supervisors s_out ON u_out.user_id = s_out.user_id
    WHERE ta.attendance_id = ISNULL(@attendance_id, SCOPE_IDENTITY());
END;
GO

-- Create view for attendance summary
CREATE OR ALTER VIEW vw_TraineeAttendanceSummary
AS
SELECT 
    t.trainee_id,
    t.full_name as trainee_name,
    u.department,
    ta.attendance_date,
    ta.checkin_time,
    ta.checkout_time,
    ta.attendance_status,
    s_in.full_name as checked_in_by,
    s_out.full_name as checked_out_by,
    ta.checkin_location,
    ta.checkout_location
FROM TraineeAttendance ta
JOIN Trainees t ON ta.trainee_id = t.trainee_id
JOIN Users u ON t.user_id = u.user_id
LEFT JOIN Users u_in ON ta.checkin_marked_by = u_in.user_id
LEFT JOIN Supervisors s_in ON u_in.user_id = s_in.user_id
LEFT JOIN Users u_out ON ta.checkout_marked_by = u_out.user_id
LEFT JOIN Supervisors s_out ON u_out.user_id = s_out.user_id;
GO

-- Create function to get attendance statistics
CREATE OR ALTER FUNCTION fn_GetTraineeAttendanceStats
(
    @trainee_id INT,
    @start_date DATE,
    @end_date DATE
)
RETURNS TABLE
AS
RETURN
(
    SELECT 
        COUNT(*) as total_days,
        SUM(CASE WHEN attendance_status = 'Present' THEN 1 ELSE 0 END) as present_days,
        SUM(CASE WHEN attendance_status = 'Late' THEN 1 ELSE 0 END) as late_days,
        SUM(CASE WHEN attendance_status = 'Half Day' THEN 1 ELSE 0 END) as half_days,
        SUM(CASE WHEN attendance_status = 'Absent' THEN 1 ELSE 0 END) as absent_days,
        CAST(AVG(CASE 
            WHEN attendance_status = 'Present' THEN 1.0
            WHEN attendance_status = 'Late' THEN 0.8
            WHEN attendance_status = 'Half Day' THEN 0.5
            ELSE 0.0 
        END) * 100 AS DECIMAL(5,2)) as attendance_percentage
    FROM TraineeAttendance
    WHERE trainee_id = @trainee_id
    AND attendance_date BETWEEN @start_date AND @end_date
);
GO

-- Example test data for attendance
INSERT INTO TraineeAttendance (
    trainee_id,
    attendance_date,
    checkin_time,
    checkout_time,
    checkin_location,
    checkout_location,
    checkin_marked_by,
    checkout_marked_by,
    qr_code_used,
    attendance_status
)
SELECT TOP 1 
    t.trainee_id,
    GETDATE(),
    DATEADD(HOUR, 8, GETDATE()),  -- 8 AM checkin
    DATEADD(HOUR, 17, GETDATE()), -- 5 PM checkout
    'Main Office',
    'Main Office',
    s.user_id,  -- Supervisor marking attendance
    s.user_id,
    q.qr_code,
    'Present'
FROM Trainees t
CROSS JOIN Users s
CROSS JOIN QRCodes q
WHERE s.role = 'supervisor'
AND q.entity_type = 'trainee'
AND q.is_active = 1;

-- Create Progress tracking table
CREATE TABLE ProgressTracking (
    progress_id INT IDENTITY(1,1) PRIMARY KEY,
    trainee_id INT FOREIGN KEY REFERENCES Trainees(trainee_id),
    session_id INT FOREIGN KEY REFERENCES TrainingSessions(session_id),
    skills_acquired NVARCHAR(500),
    rating INT CHECK (rating BETWEEN 1 AND 5),
    comments NVARCHAR(1000),
    recorded_by INT FOREIGN KEY REFERENCES Users(user_id),
    record_date DATETIME DEFAULT GETDATE()
);
GO

-- Create indexes for performance
CREATE INDEX idx_qrcodes_code ON QRCodes(qr_code);
CREATE INDEX idx_checkins_trainee ON CheckIns(trainee_id);
CREATE INDEX idx_checkins_session ON CheckIns(session_id);
GO

-- Create a stored procedure for QR code generation and assignment
CREATE PROCEDURE sp_GenerateQRCodeForEntity
    @entity_type NVARCHAR(20),
    @entity_id INT,
    @expiration_date DATETIME = NULL
AS
BEGIN
    DECLARE @new_qr_code NVARCHAR(100);


drop table QRCodes;
   select * from QRCodes;
    -- Generate a unique QR code identifier
    SET @new_qr_code = CONCAT(
        @entity_type, '-', 
        @entity_id, '-', 
        FORMAT(GETDATE(), 'yyyyMMddHHmmss'), '-',
        SUBSTRING(REPLACE(CONVERT(NVARCHAR(36), NEWID()), '-', ''), 1, 8)
    );
    
    INSERT INTO QRCodes (qr_code, entity_type, entity_id, expiration_date)
    VALUES (@new_qr_code, @entity_type, @entity_id, @expiration_date);
    
    SELECT qr_id, qr_code FROM QRCodes WHERE qr_id = SCOPE_IDENTITY();
END;
GO

CREATE TABLE TraineeTasks (
    task_id INT IDENTITY(1,1) PRIMARY KEY,
    user_id INT NOT NULL,
    task_name NVARCHAR(255) NOT NULL,
    is_completed BIT DEFAULT 0,
    CONSTRAINT FK_TraineeTasks_User FOREIGN KEY (user_id) REFERENCES Users(user_id)
);


Select * From TraineeTasks;
ALTER TABLE TraineeTasks
ADD task_type NVARCHAR(50) NULL,
    task_url NVARCHAR(255) NULL;
UPDATE TraineeTasks
SET task_type = 'generic',
    task_url = '#'
WHERE task_type IS NULL OR task_url IS NULL;

ALTER TABLE TraineeTasks
ALTER COLUMN task_type NVARCHAR(50) NOT NULL;

ALTER TABLE TraineeTasks
ALTER COLUMN task_url NVARCHAR(255) NOT NULL;


  INSERT INTO TraineeTasks (user_id, task_name, task_type, task_url)
VALUES 
 (14, 'Complete Module 1 Quiz',   'quiz',      '/trainee/task/quiz/1'),
 (14, 'Submit Assignment 2',       'upload',    '/trainee/task/upload/2'),
 (14, 'Attend Workshop on Friday', 'attendance','/trainee/task/attend/3');

-- Create a view for trainee progress
CREATE VIEW vw_TraineeProgress AS
SELECT 
    t.trainee_id,
    u.username,
    t.full_name,
    t.position,
    t.training_status,
    COUNT(DISTINCT ci.session_id) AS sessions_attended,
    AVG(CAST(pt.rating AS DECIMAL(10,2))) AS avg_rating,
    COUNT(DISTINCT tp.program_id) AS programs_enrolled
FROM 
    Trainees t
JOIN 
    Users u ON t.user_id = u.user_id
LEFT JOIN 
    CheckIns ci ON t.trainee_id = ci.trainee_id
LEFT JOIN 
    ProgressTracking pt ON t.trainee_id = pt.trainee_id
LEFT JOIN 
    TrainingSessions ts ON ci.session_id = ts.session_id
LEFT JOIN 
    TrainingPrograms tp ON ts.program_id = tp.program_id
GROUP BY 
    t.trainee_id, u.username, t.full_name, t.position, t.training_status;
GO

SELECT * FROM Users;
SELECT * FROM Trainees;
SELECT * FROM Admins;
SELECT * FROM Supervisors;
select * from TraineeTasks;
select * from QRCodes;
-- View all users with their passwords
SELECT user_id, username, password, email, role, department 
FROM Users;

INSERT INTO TraineeTasks (user_id, task_name) VALUES (9, 'Complete Module 1 Quiz');
INSERT INTO TraineeTasks (user_id, task_name) VALUES (14, 'Submit Assignment 2');
--INSERT INTO TraineeTasks (user_id, task_name) VALUES (1, 'Attend Workshop on Friday');

EXEC sp_help 'TraineeTasks';







SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE 
FROM INFORMATION_SCHEMA.COLUMNS 
WHERE TABLE_NAME = 'TraineeTasks';

INSERT INTO TraineeTasks (user_id, task_name, task_type, task_url) VALUES
(14, 'Assignment2', 'upload', '/trainee/task/upload/1');


ALTER TABLE Trainees ADD department NVARCHAR(100) NULL;

SELECT user_id, full_name, department FROM Supervisors WHERE full_name = 'Rashid Khan';

SELECT user_id, full_name, department FROM Trainees WHERE full_name = 'Ali pasha ';

SELECT 
    t.full_name, t.department AS trainee_dept,
    s.full_name AS supervisor_name, s.department AS supervisor_dept,
    CASE WHEN RTRIM(LTRIM(t.department)) = RTRIM(LTRIM(s.department)) THEN 1 ELSE 0 END AS is_match
FROM Trainees t
CROSS JOIN Supervisors s
WHERE s.user_id = <supervisor_user_id>
AND t.department = s.department;


SELECT * FROM Users WHERE department = 'Software Engineering';


-- Add department column to Trainees if it doesn't exist
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.COLUMNS 
               WHERE TABLE_NAME = 'Trainees' AND COLUMN_NAME = 'department')
BEGIN
    ALTER TABLE Trainees ADD department NVARCHAR(50) NULL;
END

-- Add supervisor_id column to Trainees if it doesn't exist
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.COLUMNS 
               WHERE TABLE_NAME = 'Trainees' AND COLUMN_NAME = 'supervisor_id')
BEGIN
    ALTER TABLE Trainees ADD supervisor_id INT NULL;
    ALTER TABLE Trainees ADD CONSTRAINT FK_Trainees_Supervisors 
        FOREIGN KEY (supervisor_id) REFERENCES Supervisors(supervisor_id);
END


ALTER TABLE TraineeTasks
  ADD resource_url VARCHAR(255) NULL;
-- cursor

-- Create stored procedure for marking check-ins
CREATE OR ALTER PROCEDURE sp_MarkCheckIn
    @trainee_id INT,
    @qr_code_id INT,
    @session_id INT = NULL,
    @location NVARCHAR(100) = 'Main Office'
AS
BEGIN
    SET NOCOUNT ON;
    
    DECLARE @current_time DATETIME = GETDATE();
    DECLARE @existing_checkin INT;
    
    -- Check if already checked in today
    SELECT @existing_checkin = checkin_id
    FROM CheckIns
    WHERE trainee_id = @trainee_id
    AND CAST(checkin_time AS DATE) = CAST(@current_time AS DATE)
    AND checkout_time IS NULL;
    
    IF @existing_checkin IS NULL
    BEGIN
        -- New check-in
        INSERT INTO CheckIns (
            trainee_id,
            qr_code_id,
            session_id,
            checkin_time,
            location,
            attendance_status
        )
        VALUES (
            @trainee_id,
            @qr_code_id,
            @session_id,
            @current_time,
            @location,
            CASE 
                WHEN DATEPART(HOUR, @current_time) >= 9 THEN 'Late'
                ELSE 'Present'
            END
        );
        
        SELECT 'Check-in recorded successfully' as message;
    END
    ELSE
    BEGIN
        -- Checkout
        UPDATE CheckIns
        SET checkout_time = @current_time,
            attendance_status = 
                CASE 
                    WHEN DATEDIFF(HOUR, checkin_time, @current_time) < 4 THEN 'Half Day'
                    ELSE attendance_status
                END
        WHERE checkin_id = @existing_checkin;
        
        SELECT 'Checkout recorded successfully' as message;
    END;
END;
GO

