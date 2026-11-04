import re
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

import config
from app import create_app
from support import create_test_database


REGISTER_NO = "2026CSE001"


@pytest.fixture
def login_app(tmp_path, monkeypatch):
    database_path = tmp_path / "student.db"
    create_test_database(database_path)
    monkeypatch.setattr(config, "DATABASE", str(database_path))
    application = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})

    conn = sqlite3.connect(database_path)
    conn.execute(
        "UPDATE login SET password=? WHERE username='admin' AND role='admin'",
        (generate_password_hash("admin123"),),
    )
    conn.execute(
        "UPDATE login SET password=? WHERE username='student' AND role='student'",
        (generate_password_hash("student123"),),
    )
    conn.execute("UPDATE students SET login_id=NULL")
    conn.execute(
        """
        UPDATE students SET login_id=(
            SELECT id FROM login WHERE username='student' AND role='student'
        ) WHERE register_no=?
        """,
        (REGISTER_NO,),
    )
    conn.commit()
    conn.close()

    import app.legacy

    app.legacy.LOGIN_ATTEMPTS.clear()
    return application, database_path


def csrf_token(client, path):
    response = client.get(path)
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match
    return match.group(1).decode()


def login(client, username, password):
    return client.post(
        "/student/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": csrf_token(client, "/student/login"),
        },
        follow_redirects=False,
    )


def admin_login(client):
    return client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": "admin123",
            "csrf_token": csrf_token(client, "/admin/login"),
        },
        follow_redirects=False,
    )


def test_reset_password_then_student_login_and_dashboard(login_app, monkeypatch):
    application, database_path = login_app
    monkeypatch.setattr("app.legacy.secrets.token_urlsafe", lambda length: "ResetPass123")
    admin = application.test_client()
    assert admin_login(admin).status_code == 302

    response = admin.post(
        f"/admin/students/{REGISTER_NO}/reset-login-password",
        data={"csrf_token": csrf_token(admin, "/admin/students")},
        follow_redirects=False,
    )
    assert response.status_code == 302

    student = application.test_client()
    response = login(student, "student", "ResetPass123")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/students")
    assert student.get("/students").status_code == 200

    conn = sqlite3.connect(database_path)
    assert conn.execute(
        "SELECT login_id FROM students WHERE register_no=?",
        (REGISTER_NO,),
    ).fetchone()[0] is not None
    conn.close()


def test_wrong_password_is_visible_on_login_page(login_app):
    application, _ = login_app
    response = login(application.test_client(), "student", "wrong-password")
    assert response.status_code == 401
    assert b"Invalid username or password." in response.data


def test_username_whitespace_is_stripped(login_app):
    application, _ = login_app
    response = login(application.test_client(), "  student  ", "student123")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/students")


def test_sixth_failed_attempt_shows_lock_message(login_app):
    application, _ = login_app
    client = application.test_client()
    responses = [login(client, "student", "wrong-password") for _ in range(6)]
    assert responses[-1].status_code == 429
    assert b"Too many failed attempts. Try again in 15 minutes." in responses[-1].data


def test_unlinked_student_login_is_explicit(login_app):
    application, database_path = login_app
    conn = sqlite3.connect(database_path)
    conn.execute(
        "INSERT INTO login(username, password, role) VALUES (?, ?, 'student')",
        ("unlinked.student", generate_password_hash("student123")),
    )
    conn.commit()
    conn.close()

    response = login(application.test_client(), "unlinked.student", "student123")
    assert response.status_code == 401
    assert b"This account is not linked to a student record. Contact the admin." in response.data
