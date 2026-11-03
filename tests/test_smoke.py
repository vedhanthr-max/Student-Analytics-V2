import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = Path(tempfile.mkdtemp(prefix="student-analytics-tests-"))
TEST_DATABASE = TEMP_ROOT / "student.db"
shutil.copy2(PROJECT_ROOT / "database" / "student.db", TEST_DATABASE)
os.environ["STUDENT_DB_PATH"] = str(TEST_DATABASE)
os.environ["SECRET_KEY"] = "test-secret"

from app import app
from services.grades import calculate_grade


def _prepare_student_login():
    conn = sqlite3.connect(TEST_DATABASE)
    conn.execute("UPDATE students SET login_id=NULL WHERE login_id=3")
    student = conn.execute("SELECT id FROM students LIMIT 1").fetchone()
    if student is None:
        conn.execute(
            "INSERT INTO students(register_no, name, login_id) VALUES (?, ?, ?)",
            ("SMOKE-1", "Smoke Student", 3),
        )
    else:
        conn.execute("UPDATE students SET login_id=3 WHERE id=?", (student[0],))
    conn.commit()
    conn.close()


_prepare_student_login()


def _login(client, role, username, password):
    login_page = client.get(f"/{role}/login")
    csrf_token = re.search(
        rb'name="csrf_token" value="([^"]+)"',
        login_page.data,
    ).group(1).decode()
    return client.post(
        f"/{role}/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": csrf_token,
        },
        follow_redirects=False,
    )


@pytest.mark.parametrize(
    ("role", "username", "password"),
    [
        ("admin", "admin", "admin123"),
        ("teacher", "teacher", "teacher123"),
        ("student", "student", "student123"),
    ],
)
def test_each_role_can_log_in(role, username, password):
    response = _login(app.test_client(), role, username, password)
    assert response.status_code == 302


def test_admin_routes_return_200():
    client = app.test_client()
    _login(client, "admin", "admin", "admin123")
    assert client.get("/admin").status_code == 200


def test_student_is_forbidden_from_admin():
    client = app.test_client()
    _login(client, "student", "student", "student123")
    assert client.get("/admin").status_code == 403


def test_delete_student_get_is_not_allowed():
    assert app.test_client().get("/delete_student/1").status_code == 405


def test_post_without_csrf_is_rejected():
    response = app.test_client().post(
        "/admin/login",
        data={"username": "admin", "password": "admin123"},
    )
    assert response.status_code == 400


def test_login_rate_limit():
    client = app.test_client()
    responses = [
        _login(client, "admin", "rate-limit-user", "wrong")
        for _ in range(6)
    ]
    assert [response.status_code for response in responses[:4]] == [401] * 4
    assert responses[4].status_code == 429
    assert responses[5].status_code == 429


def test_invalid_marks_return_400():
    client = app.test_client()
    _login(client, "admin", "admin", "admin123")
    form_page = client.get("/add_result")
    csrf_token = re.search(
        rb'name="csrf_token" value="([^"]+)"',
        form_page.data,
    ).group(1).decode()
    response = client.post(
        "/save_result",
        data={
            "register_no": "SMOKE-1",
            "semester": "1",
            "subject_code": "SMOKE",
            "internal_mark": "abc",
            "external_mark": "20",
            "csrf_token": csrf_token,
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (100, ("O", 10, "Pass")),
        (90, ("O", 10, "Pass")),
        (80, ("A+", 9, "Pass")),
        (70, ("A", 8, "Pass")),
        (60, ("B+", 7, "Pass")),
        (50, ("B", 6, "Pass")),
        (45, ("C", 5, "Pass")),
        (44, ("RA", 0, "Fail")),
    ],
)
def test_calculate_grade_thresholds(total, expected):
    assert calculate_grade(total) == expected
