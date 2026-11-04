import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

import config
from app import create_app


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def teacher_app(tmp_path, monkeypatch):
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


def login_admin(client):
    client.post(
        "/admin/login",
        data={
            "username": "admin",
            "password": "admin123",
            "csrf_token": csrf_token(client, "/admin/login"),
        },
    )


def test_admin_creates_teacher_and_teacher_can_log_in(teacher_app):
    application, database_path = teacher_app
    client = application.test_client()
    login_admin(client)

    response = client.post(
        "/admin/teachers/add",
        data={
            "username": "new.teacher",
            "password": "teacher123",
            "confirm_password": "teacher123",
            "csrf_token": csrf_token(client, "/teacher_management"),
        },
    )

    assert response.status_code == 302
    conn = sqlite3.connect(database_path)
    row = conn.execute(
        "SELECT username, password, role FROM login WHERE username=? AND role='teacher'",
        ("new.teacher",),
    ).fetchone()
    conn.close()
    assert row[0] == "new.teacher"
    assert row[2] == "teacher"
    assert row[1].startswith(("scrypt:", "pbkdf2:"))
    assert check_password_hash(row[1], "teacher123")

    teacher_client = application.test_client()
    response = teacher_client.post(
        "/teacher/login",
        data={
            "username": "new.teacher",
            "password": "teacher123",
            "csrf_token": csrf_token(teacher_client, "/teacher/login"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/teacher")


def test_duplicate_teacher_username_does_not_insert(teacher_app):
    application, database_path = teacher_app
    client = application.test_client()
    login_admin(client)
    token = csrf_token(client, "/teacher_management")
    data = {
        "username": "duplicate.teacher",
        "password": "teacher123",
        "confirm_password": "teacher123",
        "csrf_token": token,
    }
    client.post("/admin/teachers/add", data=data)

    conn = sqlite3.connect(database_path)
    before = conn.execute(
        "SELECT COUNT(*) FROM login WHERE username=? AND role='teacher'",
        ("duplicate.teacher",),
    ).fetchone()[0]
    client.post("/admin/teachers/add", data=data)
    after = conn.execute(
        "SELECT COUNT(*) FROM login WHERE username=? AND role='teacher'",
        ("duplicate.teacher",),
    ).fetchone()[0]
    conn.close()
    assert before == 1
    assert after == before


@pytest.mark.parametrize("username", ["bad username", "bad-name!"])
def test_invalid_username_is_rejected(teacher_app, username):
    application, database_path = teacher_app
    client = application.test_client()
    login_admin(client)
    client.post(
        "/admin/teachers/add",
        data={
            "username": username,
            "password": "teacher123",
            "confirm_password": "teacher123",
            "csrf_token": csrf_token(client, "/teacher_management"),
        },
    )
    conn = sqlite3.connect(database_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM login WHERE username=? AND role='teacher'",
        (username,),
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_short_password_is_rejected(teacher_app):
    application, database_path = teacher_app
    client = application.test_client()
    login_admin(client)
    client.post(
        "/admin/teachers/add",
        data={
            "username": "short.password",
            "password": "short",
            "confirm_password": "short",
            "csrf_token": csrf_token(client, "/teacher_management"),
        },
    )
    conn = sqlite3.connect(database_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM login WHERE username=? AND role='teacher'",
        ("short.password",),
    ).fetchone()[0]
    conn.close()
    assert count == 0


@pytest.mark.parametrize("role, username, password", [
    ("teacher", "teacher", "teacher123"),
    ("student", "student", "student123"),
])
def test_non_admin_cannot_create_teacher(teacher_app, role, username, password):
    application, database_path = teacher_app
    client = application.test_client()
    login_token = csrf_token(client, f"/{role}/login")
    client.post(
        f"/{role}/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": login_token,
        },
    )
    response = client.post(
        "/admin/teachers/add",
        data={
            "username": "forbidden.teacher",
            "password": "teacher123",
            "confirm_password": "teacher123",
            "csrf_token": login_token,
        },
    )
    assert response.status_code == 403
    conn = sqlite3.connect(database_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM login WHERE username='forbidden.teacher' AND role='teacher'"
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_missing_csrf_is_rejected(teacher_app):
    application, database_path = teacher_app
    client = application.test_client()
    login_admin(client)
    response = client.post(
        "/admin/teachers/add",
        data={
            "username": "csrf.teacher",
            "password": "teacher123",
            "confirm_password": "teacher123",
        },
    )
    assert response.status_code == 400
    conn = sqlite3.connect(database_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM login WHERE username='csrf.teacher' AND role='teacher'"
    ).fetchone()[0]
    conn.close()
    assert count == 0


def test_admin_can_view_teacher_management(teacher_app):
    application, _ = teacher_app
    client = application.test_client()
    login_admin(client)
    assert client.get("/teacher_management").status_code == 200
