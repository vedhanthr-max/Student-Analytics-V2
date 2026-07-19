import sqlite3

conn = sqlite3.connect("database/student.db")

cursor = conn.cursor()

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
    
    hall_ticket_status TEXT DEFAULT 'Not Generated'
    
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

# ---------------- DEFAULT LOGIN ----------------

cursor.execute("""
INSERT OR IGNORE INTO login(id,username,password,role)
VALUES
(1,'admin','admin123','admin'),
(2,'teacher','teacher123','teacher'),
(3,'student','student123','student')
""")

conn.commit()
conn.close()

print("Database Created Successfully")