"""Database schema setup and seed data."""

import sqlite3

import config
from werkzeug.security import generate_password_hash


def init_db(db_path=None):
    database_path = db_path or config.DATABASE
    conn = sqlite3.connect(database_path, timeout=30)

    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")

    # ---------------- LOGIN TABLE ----------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS login(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        password TEXT,
        role TEXT
    )
    """)

    # ---------------- STUDENT TABLE ----------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students(

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        register_no TEXT UNIQUE NOT NULL,

        name TEXT,
        department TEXT,
        year TEXT,

        study_hours REAL,
        attendance REAL,
        assignment_marks REAL,
        internal_marks REAL,

        cluster TEXT,
        recommendation TEXT,

        student_phone TEXT,
        parent_phone TEXT,
        email TEXT,

        parent_meeting TEXT DEFAULT 'Not Attended',
        meeting_date TEXT DEFAULT '-',
        teacher_remarks TEXT DEFAULT '-',

        photo TEXT DEFAULT '',

        student_status TEXT DEFAULT 'Active',

        semester1 REAL DEFAULT 0,
        semester2 REAL DEFAULT 0,
        semester3 REAL DEFAULT 0,
        semester4 REAL DEFAULT 0,
        semester5 REAL DEFAULT 0,
        semester6 REAL DEFAULT 0,
        semester7 REAL DEFAULT 0,
        semester8 REAL DEFAULT 0,

        arrear_count INTEGER DEFAULT 0,

        exam_fee REAL DEFAULT 0,
        revaluation_fee REAL DEFAULT 0,

        hall_ticket_status TEXT DEFAULT 'Not Generated',

        hall_ticket_no TEXT DEFAULT '',

        hall_ticket_generated_date TEXT DEFAULT '',

        exam_session TEXT DEFAULT '',

        exam_month TEXT DEFAULT '',

        exam_year INTEGER DEFAULT 0

    )

    """)

    # ---------------- SEMESTER RESULTS----------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS semester_results(

        result_id INTEGER PRIMARY KEY AUTOINCREMENT,

        register_no TEXT,

        semester INTEGER,

        subject_code TEXT,

        subject_name TEXT,

        internal_mark REAL,

        external_mark REAL,

        total_mark REAL,

        grade TEXT,

        grade_point REAL DEFAULT 0,

        credits INTEGER DEFAULT 0,

        result TEXT

    )
    """)

    # ---------------- EXAM REGISTRATION ----------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS exam_registration(

        registration_id INTEGER PRIMARY KEY AUTOINCREMENT,

        register_no TEXT,

        semester INTEGER,

        exam_type TEXT,

        exam_fee REAL,

        registration_date TEXT,

        status TEXT DEFAULT 'Registered'

    )
    """)

    # ---------------- PAYMENTS TABLE ----------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments(

        payment_id INTEGER PRIMARY KEY AUTOINCREMENT,

        registration_id INTEGER,

        register_no TEXT,

        amount REAL,

        payment_date TEXT,

        payment_mode TEXT DEFAULT 'Mock/Internal',

        transaction_ref TEXT UNIQUE,

        status TEXT DEFAULT 'Success'

    )
    """)

    # ---------------- SUBJECT TABLE ----------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subjects(

        subject_id INTEGER PRIMARY KEY AUTOINCREMENT,

        subject_code TEXT UNIQUE,

        subject_name TEXT,

        semester INTEGER,

        credits INTEGER

    )
    """)

    # ---------------- SCHEMA MIGRATIONS ----------------

    def add_column_if_missing(table, column, definition):
        cursor.execute(f"PRAGMA table_info({table})")
        existing_columns = {row[1] for row in cursor.fetchall()}

        if column not in existing_columns:
            cursor.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )


    add_column_if_missing("semester_results", "credits", "INTEGER DEFAULT 0")
    add_column_if_missing("subjects", "department", "TEXT DEFAULT ''")

    add_column_if_missing("students", "hall_ticket_no", "TEXT DEFAULT ''")
    add_column_if_missing(
        "students", "hall_ticket_generated_date", "TEXT DEFAULT ''"
    )
    add_column_if_missing("students", "exam_session", "TEXT DEFAULT ''")
    add_column_if_missing("students", "exam_month", "TEXT DEFAULT ''")
    add_column_if_missing("students", "exam_year", "INTEGER DEFAULT 0")
    add_column_if_missing("students", "login_id", "INTEGER")

    cursor.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_students_login_id
    ON students(login_id)
    """)

    add_column_if_missing("exam_registration", "amount_paid", "REAL DEFAULT 0")
    add_column_if_missing("exam_registration", "balance_due", "REAL DEFAULT 0")
    add_column_if_missing(
        "exam_registration", "payment_status", "TEXT DEFAULT 'Unpaid'"
    )
    add_column_if_missing(
        "exam_registration", "last_payment_date", "TEXT DEFAULT ''"
    )
    add_column_if_missing("exam_registration", "gateway_order_id", "TEXT DEFAULT ''")
    add_column_if_missing("exam_registration", "gateway_session_created_at", "TEXT DEFAULT ''")
    add_column_if_missing("exam_registration", "gateway_payment_id", "TEXT DEFAULT ''")
    add_column_if_missing("exam_registration", "gateway_qr_id", "TEXT DEFAULT ''")
    add_column_if_missing("exam_registration", "gateway_qr_image_url", "TEXT DEFAULT ''")
    add_column_if_missing("payments", "gateway_order_id", "TEXT DEFAULT ''")
    add_column_if_missing("payments", "gateway_payment_id", "TEXT DEFAULT ''")
    add_column_if_missing("payments", "gateway_signature", "TEXT DEFAULT ''")

    # Populate credits for existing results where the matching subject is available.
    cursor.execute("""
    UPDATE semester_results
    SET credits = (
        SELECT credits
        FROM subjects
        WHERE subjects.subject_code = semester_results.subject_code
    )
    WHERE EXISTS (
        SELECT 1
        FROM subjects
        WHERE subjects.subject_code = semester_results.subject_code
    )
    """)

    # Backfill payment state for existing exam registrations.
    cursor.execute("""
    UPDATE exam_registration
    SET amount_paid = COALESCE(amount_paid, 0)
    """)

    cursor.execute("""
    UPDATE exam_registration
    SET balance_due =
        CASE
            WHEN COALESCE(payment_status, '') = 'Paid' THEN 0
            WHEN COALESCE(balance_due, 0) <= 0 THEN
                CASE
                    WHEN COALESCE(exam_fee, 0) - COALESCE(amount_paid, 0) > 0 THEN
                        COALESCE(exam_fee, 0) - COALESCE(amount_paid, 0)
                    ELSE 0
                END
            ELSE balance_due
        END
    """)

    cursor.execute("""
    UPDATE exam_registration
    SET payment_status =
        CASE
            WHEN COALESCE(balance_due, 0) <= 0 THEN 'Paid'
            ELSE 'Unpaid'
        END
    WHERE COALESCE(payment_status, '') NOT IN ('Paid', 'Unpaid')
       OR COALESCE(payment_status, '') = ''
    """)

    cursor.execute("""
    UPDATE exam_registration
    SET status =
        CASE
            WHEN COALESCE(balance_due, 0) <= 0 THEN 'Paid'
            ELSE COALESCE(status, 'Registered')
        END
    """)

    # ---------------- DEFAULT LOGIN ----------------

    cursor.execute("""
    INSERT OR IGNORE INTO login(id,username,password,role)
    VALUES
    (1,'admin',?,'admin'),
    (2,'teacher',?,'teacher'),
    (3,'student',?,'student')
    """, (
        generate_password_hash("admin123"),
        generate_password_hash("teacher123"),
        generate_password_hash("student123"),
    ))

    conn.commit()
    conn.close()

    print("Database Created Successfully")

if __name__ == "__main__":
    init_db()
