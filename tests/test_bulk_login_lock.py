import re
import sqlite3

import pytest

import config
from app import create_app
from support import create_test_database


@pytest.fixture
def bulk_app(tmp_path, monkeypatch):
    database_path = tmp_path / "student.db"
    create_test_database(database_path)
    monkeypatch.setattr(config, "DATABASE", str(database_path))
    application = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
    conn = sqlite3.connect(database_path)
    conn.execute("UPDATE students SET login_id=NULL")
    conn.execute("DELETE FROM login WHERE role='student'")
    conn.commit()
    conn.close()
    return application, database_path


def csrf_token(client):
    response = client.get("/admin/students")
    return re.search(
        rb'name="csrf_token" value="([^"]+)"',
        response.data,
    ).group(1).decode()


def login_admin(client):
    login_page = client.get("/admin/login")
    token = re.search(
        rb'name="csrf_token" value="([^"]+)"',
        login_page.data,
    ).group(1).decode()
    client.post(
        "/admin/login",
        data={"username": "admin", "password": "admin123", "csrf_token": token},
    )


def bulk_create(client):
    return client.post(
        "/admin/students/create-logins",
        data={"confirm": "yes", "csrf_token": csrf_token(client)},
    )


def test_bulk_create_succeeds_while_read_cursor_is_open(bulk_app):
    application, database_path = bulk_app
    reader = sqlite3.connect(database_path)
    cursor = reader.execute("SELECT register_no FROM students")
    assert cursor.fetchone() is not None

    client = application.test_client()
    login_admin(client)
    response = bulk_create(client)

    cursor.close()
    reader.close()
    assert response.status_code == 200
    assert response.mimetype == "text/csv"


def test_bulk_create_rolls_back_after_middle_loop_error(bulk_app, monkeypatch):
    application, database_path = bulk_app
    client = application.test_client()
    login_admin(client)

    original_hash = __import__("app.legacy", fromlist=["generate_password_hash"]).generate_password_hash
    calls = {"count": 0}

    def failing_hash(password):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("injected bulk failure")
        return original_hash(password)

    monkeypatch.setattr("app.legacy.generate_password_hash", failing_hash)
    conn = sqlite3.connect(database_path)
    before_logins = conn.execute(
        "SELECT COUNT(*) FROM login WHERE role='student'"
    ).fetchone()[0]
    before_linked = conn.execute(
        "SELECT COUNT(*) FROM students WHERE login_id IS NOT NULL"
    ).fetchone()[0]
    conn.close()

    with pytest.raises(RuntimeError, match="injected bulk failure"):
        bulk_create(client)

    conn = sqlite3.connect(database_path)
    after_logins = conn.execute(
        "SELECT COUNT(*) FROM login WHERE role='student'"
    ).fetchone()[0]
    after_linked = conn.execute(
        "SELECT COUNT(*) FROM students WHERE login_id IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    assert after_logins == before_logins
    assert after_linked == before_linked


def test_bulk_create_twice_has_no_duplicates(bulk_app):
    application, database_path = bulk_app
    client = application.test_client()
    login_admin(client)
    first = bulk_create(client)
    second = bulk_create(client)
    assert first.status_code == 200
    assert second.status_code == 200

    conn = sqlite3.connect(database_path)
    total = conn.execute(
        "SELECT COUNT(*) FROM login WHERE role='student'"
    ).fetchone()[0]
    linked = conn.execute(
        "SELECT COUNT(*) FROM students WHERE login_id IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    assert total == linked
