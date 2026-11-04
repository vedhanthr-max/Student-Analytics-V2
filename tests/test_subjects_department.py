import re
import sqlite3

import pytest

import config
from app import create_app
from support import create_test_database


@pytest.fixture
def subjects_app(tmp_path, monkeypatch):
    database_path = tmp_path / "student.db"
    create_test_database(database_path)
    monkeypatch.setattr(config, "DATABASE", str(database_path))
    application = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
    conn = sqlite3.connect(database_path)
    conn.execute(
        "INSERT INTO subjects(subject_code, subject_name, department, semester, credits) "
        "VALUES (?, ?, ?, ?, ?)",
        ("BASE-001", "Base Subject", "CSE", 1, 3),
    )
    conn.commit()
    conn.close()
    return application, database_path


def csrf_token(client, path):
    response = client.get(path)
    return re.search(
        rb'name="csrf_token" value="([^"]+)"',
        response.data,
    ).group(1).decode()


def login(client, role, username, password):
    client.post(
        f"/{role}/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": csrf_token(client, f"/{role}/login"),
        },
    )


def subject_data(client, **overrides):
    data = {
        "subject_code": "CSE-NEW",
        "subject_name": "New Subject",
        "department": "CSE",
        "semester": "3",
        "credits": "4",
        "csrf_token": csrf_token(client, "/add_subject"),
    }
    data.update(overrides)
    return data


def subject_count(database_path):
    conn = sqlite3.connect(database_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
    finally:
        conn.close()


def test_teacher_can_view_add_subject(subjects_app):
    application, _ = subjects_app
    client = application.test_client()
    login(client, "teacher", "teacher", "teacher123")
    assert client.get("/add_subject").status_code == 200


def test_teacher_can_create_subject_with_department(subjects_app):
    application, database_path = subjects_app
    client = application.test_client()
    login(client, "teacher", "teacher", "teacher123")
    response = client.post("/save_subject", data=subject_data(client))
    assert response.status_code == 302

    conn = sqlite3.connect(database_path)
    row = conn.execute(
        "SELECT department FROM subjects WHERE subject_code='CSE-NEW'"
    ).fetchone()
    conn.close()
    assert row == ("CSE",)


def test_invalid_department_is_rejected(subjects_app):
    application, database_path = subjects_app
    client = application.test_client()
    login(client, "teacher", "teacher", "teacher123")
    before = subject_count(database_path)
    response = client.post(
        "/save_subject",
        data=subject_data(client, department="UNKNOWN"),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert subject_count(database_path) == before


def test_duplicate_subject_code_is_rejected(subjects_app):
    application, database_path = subjects_app
    client = application.test_client()
    login(client, "teacher", "teacher", "teacher123")
    existing = sqlite3.connect(database_path).execute(
        "SELECT subject_code FROM subjects LIMIT 1"
    ).fetchone()[0]
    before = subject_count(database_path)
    response = client.post(
        "/save_subject",
        data=subject_data(client, subject_code=existing),
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Subject code already exists." in response.data
    assert subject_count(database_path) == before


@pytest.mark.parametrize("semester, credits", [("9", "4"), ("3", "-1")])
def test_invalid_semester_or_credits_is_rejected(subjects_app, semester, credits):
    application, database_path = subjects_app
    client = application.test_client()
    login(client, "teacher", "teacher", "teacher123")
    before = subject_count(database_path)
    client.post(
        "/save_subject",
        data=subject_data(client, semester=semester, credits=credits),
    )
    assert subject_count(database_path) == before


def test_teacher_cannot_delete_subject(subjects_app):
    application, database_path = subjects_app
    client = application.test_client()
    login(client, "teacher", "teacher", "teacher123")
    subject_id = sqlite3.connect(database_path).execute(
        "SELECT subject_id FROM subjects LIMIT 1"
    ).fetchone()[0]
    response = client.post(
        f"/delete_subject/{subject_id}",
        data={"csrf_token": csrf_token(client, "/teacher/login")},
    )
    assert response.status_code == 403


def test_student_cannot_add_subject(subjects_app):
    application, _ = subjects_app
    client = application.test_client()
    login(client, "student", "student", "student123")
    assert client.get("/add_subject").status_code == 403


def test_subjects_filter_by_department(subjects_app):
    application, database_path = subjects_app
    conn = sqlite3.connect(database_path)
    conn.execute(
        "INSERT INTO subjects(subject_code, subject_name, department, semester, credits) "
        "VALUES (?, ?, ?, ?, ?)",
        ("IT-FILTER", "IT Filter Subject", "IT", 2, 3),
    )
    conn.execute(
        "INSERT INTO subjects(subject_code, subject_name, department, semester, credits) "
        "VALUES (?, ?, ?, ?, ?)",
        ("CSE-FILTER", "CSE Filter Subject", "CSE", 2, 3),
    )
    conn.commit()
    conn.close()

    client = application.test_client()
    login(client, "teacher", "teacher", "teacher123")
    response = client.get("/subjects?department=CSE")
    assert response.status_code == 200
    assert b"CSE Filter Subject" in response.data
    assert b"IT Filter Subject" not in response.data
