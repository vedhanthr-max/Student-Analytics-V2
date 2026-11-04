import sqlite3

from database import init_db
from werkzeug.security import generate_password_hash


def create_test_database(path):
    init_db(str(path))
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM students")
    accounts = [
        (1, "admin123"),
        (2, "teacher123"),
        (3, "student123"),
    ]
    for login_id, password in accounts:
        conn.execute(
            "UPDATE login SET password=? WHERE id=?",
            (generate_password_hash(password), login_id),
        )

    students = [
        (
            "2026CSE001",
            "Test Student",
            "CSE",
            "2026",
            3,
        )
    ]
    students.extend(
        (f"TEST{index:04d}", f"Test Student {index}", "CSE", "2026", None)
        for index in range(2, 202)
    )
    conn.executemany(
        """
        INSERT INTO students(register_no, name, department, year, login_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        students,
    )
    conn.commit()
    conn.close()
    return path
