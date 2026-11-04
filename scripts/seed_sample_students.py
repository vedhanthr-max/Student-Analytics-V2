"""Seed sample students from a CSV file into the Student Analytics database.

Run from the project root:

    python scripts/seed_sample_students.py dataset/sample_students_200.csv --dry-run
    python scripts/seed_sample_students.py dataset/sample_students_200.csv
    python scripts/seed_sample_students.py dataset/sample_students_200.csv --update

Default: rows whose Register No already exists are skipped.
--update: existing rows are overwritten with the CSV values.
Any validation error stops the run before anything is written.
"""

import argparse
import csv
import io
import os
import re
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import DATABASE  # noqa: E402
from database import init_db  # noqa: E402

REQUIRED_COLUMNS = [
    "Register No", "Name", "Department", "Year", "Attendance", "Study Hours",
    "Assignment", "Internal", "Performance", "Recommendation", "Student Phone",
    "Parent Phone", "Email", "Parent Meeting", "Meeting Date", "Teacher Remarks",
    "Hall Ticket", "Status",
]
# "Cluster Explanation Gaps" is not stored: the app computes it live (explain_cluster).
PERFORMANCE_LABELS = {"Excellent", "Average", "Need Improvement", "Not Predicted"}
HALL_TICKET_STATUSES = {"Generated", "Not Generated"}
MEETING_STATUSES = {"Attended", "Not Attended"}
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}|-)$")
MAX_ERRORS_SHOWN = 20


def load_rows(csv_path):
    """Read the CSV as UTF-8 (BOM-safe) and check the header."""
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        text = fh.read()
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise SystemExit(f"No data rows found in {csv_path}")
    header = {(k or "").strip() for k in rows[0].keys()}
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise SystemExit(f"CSV is missing required columns: {', '.join(missing)}")
    return [{(k or "").strip(): (v or "") for k, v in row.items()} for row in rows]


def _row_to_record(row, line_no, errors):
    """Validate one CSV row and map it to students-table columns. Returns None on error."""
    before = len(errors)

    def get(col):
        return (row.get(col) or "").strip()

    def number(col, lo, hi, strip_pct=False):
        raw = get(col)
        if strip_pct:
            raw = raw.rstrip("%").strip()
        try:
            value = float(raw)
        except ValueError:
            errors.append(f"line {line_no}: {col} '{get(col)}' is not a number")
            return None
        if not lo <= value <= hi:
            errors.append(f"line {line_no}: {col} {value} is outside {lo}-{hi}")
            return None
        return value

    register_no = get("Register No")
    if not register_no:
        errors.append(f"line {line_no}: Register No is empty")
    if not get("Name"):
        errors.append(f"line {line_no}: Name is empty")
    if not get("Department"):
        errors.append(f"line {line_no}: Department is empty")
    if not get("Year"):
        errors.append(f"line {line_no}: Year is empty")

    performance = get("Performance")
    if performance not in PERFORMANCE_LABELS:
        errors.append(f"line {line_no}: Performance '{performance}' is not a known label")

    hall_ticket = get("Hall Ticket")
    if hall_ticket not in HALL_TICKET_STATUSES:
        errors.append(f"line {line_no}: Hall Ticket '{hall_ticket}' is not valid")

    meeting = get("Parent Meeting")
    if meeting not in MEETING_STATUSES:
        errors.append(f"line {line_no}: Parent Meeting '{meeting}' is not valid")

    meeting_date = get("Meeting Date")
    if not DATE_RE.match(meeting_date):
        errors.append(f"line {line_no}: Meeting Date '{meeting_date}' must be YYYY-MM-DD or '-'")

    email = get("Email")
    if email and "@" not in email:
        errors.append(f"line {line_no}: Email '{email}' is not valid")

    attendance = number("Attendance", 0, 100, strip_pct=True)
    study_hours = number("Study Hours", 0, 24)
    assignment = number("Assignment", 0, 100)
    internal = number("Internal", 0, 100)

    if len(errors) > before:
        return None

    return {
        "register_no": register_no,
        "name": get("Name"),
        "department": get("Department"),
        "year": get("Year"),
        "study_hours": study_hours,
        "attendance": attendance,
        "assignment_marks": assignment,
        "internal_marks": internal,
        "cluster": performance,
        "recommendation": get("Recommendation"),
        "student_phone": get("Student Phone"),
        "parent_phone": get("Parent Phone"),
        "email": email,
        "parent_meeting": meeting,
        "meeting_date": meeting_date,
        "teacher_remarks": get("Teacher Remarks"),
        "student_status": get("Status") or "Active",
        "hall_ticket_status": hall_ticket,
        # Same format as the app's generate_hallticket(); the year is the current year.
        "hall_ticket_no": f"HT{datetime.now().year}{register_no}" if hall_ticket == "Generated" else "",
        "hall_ticket_generated_date": datetime.now().strftime("%d-%m-%Y") if hall_ticket == "Generated" else "",
    }


def build_records(rows):
    """Return (records, errors). Nothing is written here."""
    records, errors, seen = [], [], set()
    for line_no, row in enumerate(rows, start=2):  # line 1 is the header
        record = _row_to_record(row, line_no, errors)
        if record is None:
            continue
        if record["register_no"] in seen:
            errors.append(f"line {line_no}: duplicate Register No {record['register_no']}")
            continue
        seen.add(record["register_no"])
        records.append(record)
    return records, errors


def existing_register_numbers(db_path):
    if not os.path.exists(db_path):
        return set()
    conn = sqlite3.connect(db_path)
    try:
        return {r[0] for r in conn.execute("SELECT register_no FROM students")}
    finally:
        conn.close()


def save_records(records, db_path, update=False):
    """Insert (or update) all records in one transaction. All or nothing."""
    conn = sqlite3.connect(db_path)
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    try:
        for rec in records:
            exists = conn.execute(
                "SELECT 1 FROM students WHERE register_no=?", (rec["register_no"],)
            ).fetchone()
            if exists and not update:
                counts["skipped"] += 1
                continue
            if exists:
                # Column names come from the fixed mapping above, never from user input.
                values = {k: v for k, v in rec.items() if k != "register_no"}
                assignments = ", ".join(f"{k}=?" for k in values)
                conn.execute(
                    f"UPDATE students SET {assignments} WHERE register_no=?",
                    [*values.values(), rec["register_no"]],
                )
                counts["updated"] += 1
            else:
                columns = ", ".join(rec)
                placeholders = ", ".join("?" for _ in rec)
                conn.execute(
                    f"INSERT INTO students ({columns}) VALUES ({placeholders})",
                    list(rec.values()),
                )
                counts["inserted"] += 1
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()
    return counts


def main():
    parser = argparse.ArgumentParser(description="Seed sample students from a CSV file.")
    parser.add_argument("csv_path", help="path to the students CSV")
    parser.add_argument("--db", default=None, help="database path (default: config.DATABASE)")
    parser.add_argument("--dry-run", action="store_true", help="validate only, write nothing")
    parser.add_argument("--update", action="store_true", help="overwrite rows that already exist")
    args = parser.parse_args()

    db_path = args.db or DATABASE
    rows = load_rows(args.csv_path)
    records, errors = build_records(rows)

    print(f"Rows read: {len(rows)} | valid: {len(records)} | errors: {len(errors)}")
    if errors:
        for message in errors[:MAX_ERRORS_SHOWN]:
            print("  -", message)
        if len(errors) > MAX_ERRORS_SHOWN:
            print(f"  ... and {len(errors) - MAX_ERRORS_SHOWN} more")
        print("Nothing was written. Fix the CSV and run again.")
        return 1

    present = existing_register_numbers(db_path)
    already = sum(1 for r in records if r["register_no"] in present)
    print(f"Database: {db_path}")
    print(f"Already in database: {already} | new: {len(records) - already}")
    print(f"With --update: {already} would be overwritten" if args.update
          else f"Without --update: {already} would be skipped")

    if args.dry_run:
        print("Dry run: nothing was written.")
        return 0

    init_db(db_path)  # make sure the schema exists before inserting
    counts = save_records(records, db_path, update=args.update)
    print(f"Done. inserted={counts['inserted']} updated={counts['updated']} skipped={counts['skipped']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
