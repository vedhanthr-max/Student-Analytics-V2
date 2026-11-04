import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import config
from app import create_app


ROOT = Path(__file__).resolve().parents[1]
REGISTER_NO = "2026CSE001"


@pytest.fixture
def password_app(tmp_path, monkeypatch):
    database_path = tmp_path / "student.db"
    shutil.copy2(ROOT / "database" / "student.db", database_path)
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
    return application, database_path


def csrf_token(client, path):
    response = client.get(path)
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match
    return match.group(1).decode()


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


def change_password(client, old_password, new_password, confirm_password=None):
    return client.post(
        "/change_password",
        data={
            "old_password": old_password,
            "new_password": new_password,
            "confirm_password": (
                new_password if confirm_password is None else confirm_password
            ),
            "csrf_token": csrf_token(client, "/students"),
        },
        follow_redirects=True,
    )


def test_logged_out_change_password_redirects(password_app):
    application, database_path = password_app
    client = application.test_client()
    conn = sqlite3.connect(database_path)
    before = conn.execute(
        "SELECT password FROM login WHERE username='student' AND role='student'"
    ).fetchone()[0]
    conn.close()

    response = client.post(
        "/change_password",
        data={
            "old_password": "student123",
            "new_password": "Changed123",
            "confirm_password": "Changed123",
            "csrf_token": csrf_token(client, "/student/login"),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Please log in first." in response.data
    conn = sqlite3.connect(database_path)
    after = conn.execute(
        "SELECT password FROM login WHERE username='student' AND role='student'"
    ).fetchone()[0]
    conn.close()
    assert after == before


def test_student_wrong_old_password_does_not_change_it(password_app):
    application, database_path = password_app
    client = application.test_client()
    assert login(client, "student", "student", "student123").status_code == 302

    response = change_password(client, "wrong-password", "Changed123")
    assert response.status_code == 200
    assert b"Old password is incorrect." in response.data
    assert login(application.test_client(), "student", "student", "student123").status_code == 302


def test_student_can_change_password(password_app):
    application, _ = password_app
    client = application.test_client()
    assert login(client, "student", "student", "student123").status_code == 302

    response = change_password(client, "student123", "Changed123")
    assert response.status_code == 200
    assert b"Password changed." in response.data
    assert login(application.test_client(), "student", "student", "student123").status_code == 401
    assert login(application.test_client(), "student", "student", "Changed123").status_code == 302


def test_reset_password_can_then_be_changed(password_app, monkeypatch):
    application, database_path = password_app
    monkeypatch.setattr("app.legacy.secrets.token_urlsafe", lambda length: "ResetPass123")
    admin = application.test_client()
    assert login(admin, "admin", "admin", "admin123").status_code == 302

    conn = sqlite3.connect(database_path)
    login_id = conn.execute(
        "SELECT id FROM login WHERE username='student' AND role='student'"
    ).fetchone()[0]
    conn.execute(
        "UPDATE students SET login_id=? WHERE register_no=?",
        (login_id, REGISTER_NO),
    )
    conn.commit()
    conn.close()

    response = admin.post(
        f"/admin/students/{REGISTER_NO}/reset-login-password",
        data={"csrf_token": csrf_token(admin, "/admin/students")},
        follow_redirects=False,
    )
    assert response.status_code == 302

    student = application.test_client()
    assert login(student, "student", "student", "ResetPass123").status_code == 302
    assert change_password(student, "ResetPass123", "Changed123").status_code == 200
    assert login(application.test_client(), "student", "student", "Changed123").status_code == 302


@pytest.mark.parametrize(
    "new_password, confirm_password",
    [("short", "short"), ("Changed123", "Different123")],
)
def test_new_password_validation(password_app, new_password, confirm_password):
    application, _ = password_app
    client = application.test_client()
    assert login(client, "student", "student", "student123").status_code == 302

    response = change_password(client, "student123", new_password, confirm_password)
    assert response.status_code == 200
    assert b"Password changed." not in response.data


def test_change_password_requires_csrf(password_app):
    application, _ = password_app
    client = application.test_client()
    assert login(client, "student", "student", "student123").status_code == 302
    response = client.post(
        "/change_password",
        data={
            "old_password": "student123",
            "new_password": "Changed123",
            "confirm_password": "Changed123",
        },
    )
    assert response.status_code == 400


def test_forgot_password_has_no_form(password_app):
    application, _ = password_app
    response = application.test_client().get("/forgot_password")
    assert response.status_code == 200
    assert b"Forgot your password? Ask the admin to reset it." in response.data
    assert b"<form" not in response.data
