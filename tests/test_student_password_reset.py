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
def reset_app(tmp_path, monkeypatch):
    database_path = tmp_path / "student.db"
    shutil.copy2(ROOT / "database" / "student.db", database_path)
    monkeypatch.setattr(config, "DATABASE", str(database_path))
    application = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
    return application, database_path


def csrf_token(client, path):
    response = client.get(path)
    return re.search(
        rb'name="csrf_token" value="([^"]+)"',
        response.data,
    ).group(1).decode()


def login(client, role, username, password):
    return client.post(
        f"/{role}/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": csrf_token(client, f"/{role}/login"),
        },
        follow_redirects=False,
    )


def create_student_login(database_path, password="OldPass123"):
    conn = sqlite3.connect(database_path)
    login_id = conn.execute(
        "INSERT INTO login(username, password, role) VALUES (?, ?, 'student')",
        (REGISTER_NO, password),
    ).lastrowid
    conn.execute(
        "UPDATE students SET login_id=? WHERE register_no=?",
        (login_id, REGISTER_NO),
    )
    conn.commit()
    conn.close()


def test_reset_replaces_old_password_and_new_password_logs_in(reset_app, monkeypatch):
    application, database_path = reset_app
    create_student_login(database_path)
    monkeypatch.setattr(
        "app.legacy.secrets.token_urlsafe",
        lambda length: "NewPass123",
    )
    admin = application.test_client()
    login(admin, "admin", "admin", "admin123")

    response = admin.post(
        f"/admin/students/{REGISTER_NO}/reset-login-password",
        data={"csrf_token": csrf_token(admin, "/admin/students")},
    )
    assert response.status_code == 302

    conn = sqlite3.connect(database_path)
    stored_password = conn.execute(
        "SELECT password FROM login WHERE username=? AND role='student'",
        (REGISTER_NO,),
    ).fetchone()[0]
    conn.close()
    assert check_password_hash(stored_password, "NewPass123")
    assert not check_password_hash(stored_password, "OldPass123")

    student = application.test_client()
    old_response = login(student, "student", REGISTER_NO, "OldPass123")
    assert old_response.status_code == 401
    new_response = login(student, "student", REGISTER_NO, "NewPass123")
    assert new_response.status_code == 302
    assert new_response.headers["Location"].endswith("/students")


def test_reset_without_login_account_does_not_change_data(reset_app, monkeypatch):
    application, database_path = reset_app
    monkeypatch.setattr(
        "app.legacy.secrets.token_urlsafe",
        lambda length: "ShouldNotBeUsed",
    )
    client = application.test_client()
    login(client, "admin", "admin", "admin123")
    response = client.post(
        f"/admin/students/{REGISTER_NO}/reset-login-password",
        data={"csrf_token": csrf_token(client, "/admin/students")},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"This student has no login account. Create one first." in response.data
    conn = sqlite3.connect(database_path)
    assert conn.execute(
        "SELECT login_id FROM students WHERE register_no=?",
        (REGISTER_NO,),
    ).fetchone()[0] is None
    assert conn.execute(
        "SELECT COUNT(*) FROM login WHERE username=? AND role='student'",
        (REGISTER_NO,),
    ).fetchone()[0] == 0
    conn.close()


def test_non_admin_cannot_reset_password(reset_app):
    application, database_path = reset_app
    create_student_login(database_path)
    client = application.test_client()
    login(client, "teacher", "teacher", "teacher123")
    response = client.post(
        f"/admin/students/{REGISTER_NO}/reset-login-password",
        data={"csrf_token": csrf_token(client, "/teacher/login")},
    )
    assert response.status_code == 403


def test_reset_requires_csrf_token(reset_app):
    application, database_path = reset_app
    create_student_login(database_path)
    client = application.test_client()
    login(client, "admin", "admin", "admin123")
    response = client.post(
        f"/admin/students/{REGISTER_NO}/reset-login-password",
    )
    assert response.status_code == 400
