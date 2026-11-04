import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

import config
from app import create_app


ROOT = Path(__file__).resolve().parents[1]
REGISTER_NO = "2026CSE001"


@pytest.fixture
def student_app(tmp_path, monkeypatch):
    database_path = tmp_path / "student.db"
    shutil.copy2(ROOT / "database" / "student.db", database_path)
    monkeypatch.setattr(config, "DATABASE", str(database_path))
    application = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
    conn = sqlite3.connect(database_path)
    login_id = conn.execute(
        "SELECT login_id FROM students WHERE register_no=?",
        (REGISTER_NO,),
    ).fetchone()[0]
    if login_id is not None:
        conn.execute("DELETE FROM login WHERE id=?", (login_id,))
    conn.execute(
        "UPDATE students SET login_id=NULL WHERE register_no=?",
        (REGISTER_NO,),
    )
    conn.commit()
    conn.close()
    return application, database_path


def token(client, path):
    response = client.get(path)
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match
    return match.group(1).decode()


def login(client, role, username, password):
    response = client.get(f"/{role}/login")
    response_token = re.search(
        rb'name="csrf_token" value="([^"]+)"', response.data
    ).group(1).decode()
    return client.post(
        f"/{role}/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": response_token,
        },
        follow_redirects=False,
    )


def add_registration(database_path, payment_status="Unpaid", balance_due=100):
    conn = sqlite3.connect(database_path)
    conn.execute(
        """
        INSERT INTO exam_registration(
            register_no, semester, exam_type, exam_fee, registration_date,
            amount_paid, balance_due, payment_status, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            REGISTER_NO, 1, "Regular", 100, "2026-11-04",
            0 if payment_status == "Unpaid" else 100,
            balance_due, payment_status, "Registered",
        ),
    )
    conn.commit()
    conn.close()


def test_create_student_login_and_second_call_does_nothing(student_app, monkeypatch):
    application, database_path = student_app
    monkeypatch.setattr("app.legacy.secrets.token_urlsafe", lambda length: "TempPass123")
    client = application.test_client()
    login(client, "admin", "admin", "admin123")

    response = client.post(
        f"/admin/students/{REGISTER_NO}/create-login",
        data={"csrf_token": token(client, "/admin/students")},
    )
    assert response.status_code == 302
    conn = sqlite3.connect(database_path)
    row = conn.execute(
        """
        SELECT l.username, l.password, l.role, s.login_id
        FROM login l JOIN students s ON s.login_id=l.id
        WHERE s.register_no=?
        """,
        (REGISTER_NO,),
    ).fetchone()
    count_before = conn.execute(
        "SELECT COUNT(*) FROM login WHERE username=? AND role='student'",
        (REGISTER_NO,),
    ).fetchone()[0]
    conn.close()
    assert row[0] == REGISTER_NO
    assert row[2] == "student"
    assert row[3] is not None
    assert check_password_hash(row[1], "TempPass123")

    client.post(
        f"/admin/students/{REGISTER_NO}/create-login",
        data={"csrf_token": token(client, "/admin/students")},
    )
    conn = sqlite3.connect(database_path)
    count_after = conn.execute(
        "SELECT COUNT(*) FROM login WHERE username=? AND role='student'",
        (REGISTER_NO,),
    ).fetchone()[0]
    conn.close()
    assert count_after == count_before


def test_new_student_can_log_in(student_app, monkeypatch):
    application, _ = student_app
    monkeypatch.setattr("app.legacy.secrets.token_urlsafe", lambda length: "TempPass123")
    admin = application.test_client()
    login(admin, "admin", "admin", "admin123")
    admin.post(
        f"/admin/students/{REGISTER_NO}/create-login",
        data={"csrf_token": token(admin, "/admin/students")},
    )

    student = application.test_client()
    response = login(student, "student", REGISTER_NO, "TempPass123")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/students")


def test_bulk_student_logins_are_returned_as_csv(student_app, monkeypatch):
    application, database_path = student_app
    monkeypatch.setattr("app.legacy.secrets.token_urlsafe", lambda length: "TempPass123")
    client = application.test_client()
    login(client, "admin", "admin", "admin123")
    response = client.post(
        "/admin/students/create-logins",
        data={"confirm": "yes", "csrf_token": token(client, "/admin/students")},
    )
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.data.startswith(b"register_no,username,temporary password\n")
    conn = sqlite3.connect(database_path)
    linked = conn.execute(
        "SELECT COUNT(*) FROM students WHERE login_id IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    assert linked == 201


def test_bulk_fee_assignment_is_idempotent(student_app):
    application, database_path = student_app
    client = application.test_client()
    login(client, "admin", "admin", "admin123")
    data = {
        "semester": "1",
        "exam_type": "Regular",
        "exam_fee": "250.50",
        "registration_date": "2026-11-04",
        "csrf_token": token(client, "/admin/fees/pending"),
    }
    response = client.post("/admin/fees/assign", data=data)
    assert response.status_code == 302
    response = client.post("/admin/fees/assign", data=data)
    assert response.status_code == 302

    conn = sqlite3.connect(database_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM exam_registration WHERE semester=1 AND exam_type='Regular'"
    ).fetchone()[0]
    balance = conn.execute(
        "SELECT balance_due FROM exam_registration WHERE register_no=? AND semester=1",
        (REGISTER_NO,),
    ).fetchone()[0]
    conn.close()
    assert count == 201
    assert balance == 250.5


def test_hall_ticket_requires_paid_requested_semester(student_app):
    application, database_path = student_app
    add_registration(database_path)
    conn = sqlite3.connect(database_path)
    student_id = conn.execute(
        "SELECT id FROM students WHERE register_no=?", (REGISTER_NO,)
    ).fetchone()[0]
    conn.close()
    client = application.test_client()
    login(client, "teacher", "teacher", "teacher123")
    data = {"semester": "1", "csrf_token": token(client, "/teacher/login")}
    blocked = client.post(f"/generate_hallticket/{student_id}", data=data)
    assert blocked.status_code == 200
    assert b"Pending Exam Registration Fee Payment" in blocked.data

    conn = sqlite3.connect(database_path)
    conn.execute(
        "UPDATE exam_registration SET payment_status='Paid', balance_due=0, amount_paid=100"
    )
    conn.commit()
    conn.close()
    allowed = client.post(f"/generate_hallticket/{student_id}", data=data)
    assert allowed.status_code == 302


@pytest.mark.parametrize(
    "path, role, username, password",
    [
        (f"/admin/students/{REGISTER_NO}/create-login", "teacher", "teacher", "teacher123"),
        ("/admin/fees/assign", "teacher", "teacher", "teacher123"),
    ],
)
def test_non_admin_cannot_use_admin_routes(
    student_app, path, role, username, password
):
    application, _ = student_app
    client = application.test_client()
    login(client, role, username, password)
    response = client.post(
        path,
        data={"csrf_token": token(client, f"/{role}/login")},
    )
    assert response.status_code == 403


def test_missing_csrf_is_rejected(student_app):
    application, _ = student_app
    client = application.test_client()
    login(client, "admin", "admin", "admin123")
    response = client.post(f"/admin/students/{REGISTER_NO}/create-login")
    assert response.status_code == 400
    response = client.post(
        "/admin/fees/assign",
        data={
            "semester": "1",
            "exam_type": "Regular",
            "exam_fee": "100",
            "registration_date": "2026-11-04",
        },
    )
    assert response.status_code == 400
