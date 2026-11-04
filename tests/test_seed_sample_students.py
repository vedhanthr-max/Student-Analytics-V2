import importlib.util
import sqlite3
from pathlib import Path

import pytest

from database import init_db

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = ROOT / "dataset" / "sample_students_200.csv"

_spec = importlib.util.spec_from_file_location("seed", ROOT / "scripts" / "seed_sample_students.py")
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test_student.db"
    init_db(str(path))
    return str(path)


def test_sample_csv_is_valid():
    records, errors = seed.build_records(seed.load_rows(SAMPLE_CSV))
    assert errors == []
    assert len(records) == 200


def test_seed_inserts_all_rows_and_is_idempotent(db_path):
    records, errors = seed.build_records(seed.load_rows(SAMPLE_CSV))
    assert errors == []
    assert seed.save_records(records, db_path) == {"inserted": 200, "updated": 0, "skipped": 0}
    assert seed.save_records(records, db_path) == {"inserted": 0, "updated": 0, "skipped": 200}

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 200
    row = conn.execute(
        "SELECT attendance, study_hours, cluster, hall_ticket_status, hall_ticket_no "
        "FROM students WHERE register_no='2026CSE001'"
    ).fetchone()
    conn.close()
    assert row[0] == 83.8          # "83.8%" stored as a number
    assert row[1] == 0.7
    assert row[2] == "Need Improvement"
    assert row[3] == "Generated"
    assert row[4].endswith("2026CSE001")


def test_update_overwrites_existing_rows(db_path):
    records, _ = seed.build_records(seed.load_rows(SAMPLE_CSV))
    seed.save_records(records, db_path)
    records[0]["name"] = "Changed Name"
    assert seed.save_records(records, db_path, update=True)["updated"] == 200
    conn = sqlite3.connect(db_path)
    name = conn.execute(
        "SELECT name FROM students WHERE register_no=?", (records[0]["register_no"],)
    ).fetchone()[0]
    conn.close()
    assert name == "Changed Name"


def test_bad_rows_are_reported(tmp_path):
    bad = tmp_path / "bad.csv"
    header = ",".join(seed.REQUIRED_COLUMNS)
    good = "2026X001,A,CSE,II,80%,4,70,70,Average,R,0000000000,0000000000,a@b.com,Not Attended,-,Remark,Generated,Active"
    broken = "2026X002,B,CSE,II,abc%,4,70,70,Average,R,0000000000,0000000000,a@b.com,Not Attended,-,Remark,Generated,Active"
    bad.write_text("\n".join([header, good, broken, good]), encoding="utf-8")
    records, errors = seed.build_records(seed.load_rows(bad))
    assert any("Attendance" in e for e in errors)
    assert any("duplicate Register No" in e for e in errors)
    assert len(records) == 1


def test_missing_column_stops_the_run(tmp_path):
    bad = tmp_path / "missing.csv"
    bad.write_text("Register No,Name\n2026X001,A\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        seed.load_rows(bad)
