from datetime import datetime
from datetime import timedelta
import csv
import io
import logging
import math
import os
import uuid
import sqlite3
from urllib.parse import urlencode

from flask import Flask, jsonify, render_template, request, redirect, send_file, url_for, session
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
except ImportError:
    A4 = None
    canvas = None

try:
    import razorpay
except ImportError:
    razorpay = None

from database import init_db
from config import (
    DEBUG,
    UPI_ID,
    UPI_NUMBER,
    UPI_PAYEE_NAME,
)
from services.grades import calculate_grade, compute_gpa, compute_summary, parse_marks
from services.prediction import explain_cluster, predict_student_performance
from app import route
from utils.auth import login_required, roles_required, student_identity
from utils.database import get_connection, get_row_connection

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(
    __name__,
    template_folder=os.path.join(_PROJECT_ROOT, "templates"),
    static_folder=os.path.join(_PROJECT_ROOT, "static"),
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
)

csrf = CSRFProtect(app)

os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
logger = logging.getLogger("student_analytics")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler(os.path.join(os.path.dirname(__file__), "logs", "app.log"))
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

init_db()

PAYMENT_SESSION_SECONDS = 5 * 60
LOGIN_ATTEMPTS = {}
SESSION_IDLE_SECONDS = 30 * 60


@app.before_request
def enforce_session_idle_timeout():
    if "username" not in session:
        return None

    now = datetime.utcnow().timestamp()
    last_activity = session.get("last_activity")
    if last_activity is not None and now - last_activity > SESSION_IDLE_SECONDS:
        session.clear()
        return redirect(url_for("index"))

    session.permanent = True
    session["last_activity"] = now
    return None


@app.after_request
def add_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    return "Invalid CSRF token.", 400


@app.errorhandler(403)
def handle_forbidden(error):
    return "Forbidden", 403


@app.errorhandler(404)
def handle_not_found(error):
    return "Not Found", 404


@app.errorhandler(405)
def handle_method_not_allowed(error):
    return "Method Not Allowed", 405


@app.errorhandler(500)
def handle_internal_error(error):
    logger.exception("Unhandled server error")
    return "Internal Server Error", 500


def _login_key():
    return request.remote_addr or "unknown", request.form.get("username", "").strip()


def _login_is_locked(key):
    attempt = LOGIN_ATTEMPTS.get(key)
    if attempt is None:
        return False
    now = datetime.utcnow().timestamp()
    if attempt["locked_until"] > now:
        return True
    if attempt["locked_until"]:
        LOGIN_ATTEMPTS.pop(key, None)
    return False


def _record_login_failure(key):
    attempt = LOGIN_ATTEMPTS.setdefault(key, {"count": 0, "locked_until": 0})
    attempt["count"] += 1
    if attempt["count"] >= 5:
        attempt["locked_until"] = datetime.utcnow().timestamp() + 15 * 60


def _clear_login_failures(key):
    LOGIN_ATTEMPTS.pop(key, None)


def _pagination_values():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 10))))
    except (TypeError, ValueError):
        page, per_page = 1, 10
    return page, per_page


def _total_pages(total, per_page):
    return max(1, math.ceil(total / per_page))


def _read_csv_upload(field_name):
    upload = request.files.get(field_name)
    if upload is None or not upload.filename:
        return None, ["CSV file is required."]
    if request.content_length and request.content_length > 2 * 1024 * 1024:
        return None, ["CSV file exceeds the 2 MB limit."]

    content = upload.stream.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        return None, ["CSV file exceeds the 2 MB limit."]
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, ["CSV file must be UTF-8 encoded."]
    return csv.DictReader(io.StringIO(text)), []


def _json_import_result(errors, inserted=0, dry_run=False):
    return jsonify({
        "dry_run": dry_run,
        "inserted": inserted,
        "errors": errors,
    }), 400 if errors and not dry_run else 200


def razorpay_client():
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")

    if razorpay is None or not key_id or not key_secret:
        return None

    return razorpay.Client(auth=(key_id, key_secret))


# ---------------- HOME ----------------

@route("/")
def index():
    return redirect(url_for("student_login"))


@route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        return authenticate_login("admin")
    return render_template(
        "login.html",
        login_role="admin",
        login_title="Admin Login",
        login_action=url_for("admin_login")
    )


@route("/teacher/login", methods=["GET", "POST"])
def teacher_login():
    if request.method == "POST":
        return authenticate_login("teacher")
    return render_template(
        "login.html",
        login_role="teacher",
        login_title="Teacher Login",
        login_action=url_for("teacher_login")
    )


@route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        return authenticate_login("student")
    return render_template(
        "login.html",
        login_role="student",
        login_title="Student Login",
        login_action=url_for("student_login")
    )


# ---------------- LOGIN ----------------

def authenticate_login(role):

    username = request.form["username"]
    password = request.form["password"]
    login_key = _login_key()

    if _login_is_locked(login_key):
        logger.warning("Login locked ip=%s username=%s role=%s", login_key[0], username, role)
        return "Too many failed login attempts. Try again later.", 429

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM login WHERE username=? AND role=?",
        (username, role)
    )

    user = cursor.fetchone()

    if user:
        stored_password = user["password"]
        password_matches = (
            check_password_hash(stored_password, password)
            if stored_password.startswith(("scrypt:", "pbkdf2:"))
            else stored_password == password
        )

        if not password_matches:
            conn.close()
            _record_login_failure(login_key)
            logger.warning("Login failure ip=%s username=%s role=%s", login_key[0], username, role)
            if _login_is_locked(login_key):
                return "Too many failed login attempts. Try again later.", 429
            return "Invalid Login", 401

        if not stored_password.startswith(("scrypt:", "pbkdf2:")):
            cursor.execute(
                "UPDATE login SET password=? WHERE id=?",
                (generate_password_hash(password), user["id"])
            )
            conn.commit()

        session["username"] = username
        session["role"] = user["role"]
        session.permanent = True
        _clear_login_failures(login_key)
        logger.info("Login success ip=%s username=%s role=%s", login_key[0], username, role)
        session.pop("student_id", None)
        session.pop("student_register_no", None)

        if user["role"] == "admin":
            conn.close()
            return redirect(url_for("admin"))

        elif user["role"] == "teacher":
            conn.close()
            return redirect(url_for("teacher"))

        else:
            cursor.execute(
                "SELECT id, register_no FROM students WHERE login_id=?",
                (user["id"],)
            )
            student = cursor.fetchone()

            if student is not None:
                session["student_id"] = student["id"]
                session["student_register_no"] = student["register_no"]

                conn.close()
                return redirect(url_for("students"))

            conn.close()
            return "Invalid Login", 401

    conn.close()
    _record_login_failure(login_key)
    logger.warning("Login failure ip=%s username=%s role=%s", login_key[0], username, role)
    if _login_is_locked(login_key):
        return "Too many failed login attempts. Try again later.", 429
    return "Invalid Login", 401


@route("/login", methods=["POST"])
def login():
    return "Use the role-specific login page.", 400


# ---------------- ADMIN ----------------

@route("/admin")
@roles_required("admin")
def admin():
    conn = get_row_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM login WHERE role='teacher'")
    total_teachers = cursor.fetchone()[0]

    cursor.execute("""
    SELECT COALESCE(SUM(amount), 0)
    FROM payments
    WHERE status='Success'
    """)
    fees_collected = cursor.fetchone()[0]

    cursor.execute("""
    SELECT COALESCE(SUM(CASE WHEN balance_due > 0 THEN balance_due ELSE 0 END), 0)
    FROM exam_registration
    WHERE COALESCE(payment_status, 'Unpaid') != 'Paid'
       OR COALESCE(balance_due, 0) > 0
    """)
    pending_fees = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_students=total_students,
        total_teachers=total_teachers,
        fees_collected=fees_collected,
        pending_fees=pending_fees,
    )


@route("/admin/students")
@roles_required("admin")
def admin_students():

    search = request.args.get("search", "")
    page, per_page = _pagination_values()
    offset = (page - 1) * per_page

    conn = get_row_connection()
    cursor = conn.cursor()

    if search:
        filters = (
            "%" + search + "%",
            "%" + search + "%",
            "%" + search + "%",
        )
        cursor.execute("""
        SELECT COUNT(*)
        FROM students
        WHERE name LIKE ? OR department LIKE ? OR year LIKE ?
        """, filters)
        total = cursor.fetchone()[0]
        cursor.execute("""
        SELECT * FROM students
        WHERE name LIKE ?
           OR department LIKE ?
           OR year LIKE ?
        ORDER BY register_no
        LIMIT ? OFFSET ?
        """, (
            *filters,
            per_page,
            offset,
        ))
    else:
        total = cursor.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        cursor.execute(
            "SELECT * FROM students ORDER BY register_no LIMIT ? OFFSET ?",
            (per_page, offset),
        )

    students = cursor.fetchall()
    conn.close()

    return render_template(
        "student.html",
        students=students,
        show_back_to_dashboard=True,
        page=page,
        per_page=per_page,
        total_pages=_total_pages(total, per_page),
    )


@route("/admin/import/students", methods=["POST"])
@roles_required("admin")
def import_students():
    reader, errors = _read_csv_upload("file")
    dry_run = request.values.get("dry_run") == "1"
    expected_headers = {
        "register_no", "name", "department", "year", "study_hours",
        "attendance", "assignment_marks", "internal_marks",
        "student_phone", "parent_phone", "email",
    }
    if reader is None:
        return _json_import_result(errors, dry_run=dry_run)
    if set(reader.fieldnames or []) != expected_headers:
        return _json_import_result(
            ["CSV header must contain the required student columns."],
            dry_run=dry_run,
        )

    conn = get_connection()
    cursor = conn.cursor()
    seen = set()
    rows = []
    for row_number, row in enumerate(reader, start=2):
        register_no = (row.get("register_no") or "").strip()
        if not register_no:
            errors.append(f"Row {row_number}: register_no is required.")
            continue
        if register_no in seen:
            errors.append(f"Row {row_number}: duplicate register_no in file.")
            continue
        seen.add(register_no)
        try:
            values = (
                float(row["study_hours"]),
                float(row["attendance"]),
                float(row["assignment_marks"]),
                float(row["internal_marks"]),
            )
        except (KeyError, TypeError, ValueError):
            errors.append(f"Row {row_number}: feature values must be numbers.")
            continue
        cursor.execute(
            "SELECT 1 FROM students WHERE register_no=?",
            (register_no,),
        )
        if cursor.fetchone() is not None:
            errors.append(f"Row {row_number}: register_no already exists.")
            continue
        rows.append((row, values))

    if errors:
        conn.close()
        return _json_import_result(errors, dry_run=dry_run)
    if dry_run:
        conn.close()
        return _json_import_result([], inserted=len(rows), dry_run=True)

    try:
        for row, values in rows:
            cursor.execute(
                """
                INSERT INTO students(
                    register_no, name, department, year,
                    study_hours, attendance, assignment_marks, internal_marks,
                    cluster, recommendation, student_phone, parent_phone, email
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["register_no"].strip(),
                    row["name"].strip(),
                    row["department"].strip(),
                    row["year"].strip(),
                    *values,
                    "Not Predicted",
                    "Not Generated",
                    row["student_phone"].strip(),
                    row["parent_phone"].strip(),
                    row["email"].strip(),
                ),
            )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        conn.close()
        return _json_import_result([f"Import failed: {exc}"])
    conn.close()
    logger.info("Admin action=import_students username=%s count=%s", session.get("username"), len(rows))
    return _json_import_result([], inserted=len(rows))


@route("/teacher/import/results", methods=["POST"])
@roles_required("teacher")
def import_results():
    reader, errors = _read_csv_upload("file")
    dry_run = request.values.get("dry_run") == "1"
    expected_headers = {
        "register_no", "semester", "subject_code",
        "internal_mark", "external_mark",
    }
    if reader is None:
        return _json_import_result(errors, dry_run=dry_run)
    if set(reader.fieldnames or []) != expected_headers:
        return _json_import_result(
            ["CSV header must contain the required result columns."],
            dry_run=dry_run,
        )

    conn = get_connection()
    cursor = conn.cursor()
    seen = set()
    rows = []
    for row_number, row in enumerate(reader, start=2):
        key = (
            (row.get("register_no") or "").strip(),
            (row.get("semester") or "").strip(),
            (row.get("subject_code") or "").strip(),
        )
        try:
            semester = int(key[1])
            internal, external = parse_marks(
                row["internal_mark"],
                row["external_mark"],
            )
        except (KeyError, ValueError) as exc:
            errors.append(f"Row {row_number}: {exc}")
            continue
        if key in seen:
            errors.append(f"Row {row_number}: duplicate result in file.")
            continue
        seen.add(key)
        cursor.execute(
            "SELECT 1 FROM students WHERE register_no=?",
            (key[0],),
        )
        if cursor.fetchone() is None:
            errors.append(f"Row {row_number}: student does not exist.")
            continue
        cursor.execute(
            "SELECT subject_name, credits FROM subjects WHERE subject_code=?",
            (key[2],),
        )
        subject = cursor.fetchone()
        if subject is None:
            errors.append(f"Row {row_number}: subject does not exist.")
            continue
        cursor.execute(
            """
            SELECT 1 FROM semester_results
            WHERE register_no=? AND semester=? AND subject_code=?
            """,
            (key[0], semester, key[2]),
        )
        if cursor.fetchone() is not None:
            errors.append(f"Row {row_number}: result already exists.")
            continue
        grade, grade_point, result = calculate_grade(internal + external)
        rows.append((
            key[0], semester, key[2], subject[0], internal, external,
            internal + external, grade, grade_point, subject[1], result,
        ))

    if errors:
        conn.close()
        return _json_import_result(errors, dry_run=dry_run)
    if dry_run:
        conn.close()
        return _json_import_result([], inserted=len(rows), dry_run=True)

    try:
        cursor.executemany(
            """
            INSERT INTO semester_results(
                register_no, semester, subject_code, subject_name,
                internal_mark, external_mark, total_mark, grade,
                grade_point, credits, result
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        for register_no, *_ in rows:
            cursor.execute(
                """
                UPDATE students
                SET arrear_count=(
                    SELECT COUNT(*) FROM semester_results
                    WHERE register_no=? AND result='Fail'
                )
                WHERE register_no=?
                """,
                (register_no, register_no),
            )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        conn.close()
        return _json_import_result([f"Import failed: {exc}"])
    conn.close()
    logger.info("Teacher action=import_results username=%s count=%s", session.get("username"), len(rows))
    return _json_import_result([], inserted=len(rows))


@route("/admin/teachers")
@roles_required("admin")
def admin_teachers():

    conn = get_row_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, username, role FROM login WHERE role='teacher' ORDER BY id"
    )

    teachers = cursor.fetchall()
    conn.close()

    return render_template("teacher_management.html", teachers=teachers)


@route("/admin/fees/collected")
@roles_required("admin")
def admin_fees_collected():

    conn = get_row_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        p.payment_id,
        s.name,
        s.register_no,
        er.semester,
        er.exam_type,
        p.amount,
        p.payment_date,
        p.transaction_ref
    FROM payments p
    LEFT JOIN exam_registration er
        ON er.registration_id = p.registration_id
    LEFT JOIN students s
        ON s.register_no = p.register_no
    WHERE p.status='Success'
      AND COALESCE(er.payment_status, '') = 'Paid'
    ORDER BY p.payment_id DESC
    """)

    payments = cursor.fetchall()

    cursor.execute("""
    SELECT COALESCE(SUM(p.amount), 0)
    FROM payments p
    LEFT JOIN exam_registration er
        ON er.registration_id = p.registration_id
    WHERE p.status='Success'
      AND COALESCE(er.payment_status, '') = 'Paid'
    """)

    total_collected = cursor.fetchone()[0]
    conn.close()

    return render_template(
        "admin_fees_collected.html",
        payments=payments,
        total_collected=total_collected,
    )


@route("/admin/fees/pending")
@roles_required("admin")
def admin_fees_pending():

    conn = get_row_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        er.registration_id,
        s.name,
        s.register_no,
        er.semester,
        er.exam_type,
        er.exam_fee,
        er.amount_paid,
        er.balance_due,
        er.payment_status
    FROM exam_registration er
    LEFT JOIN students s
        ON s.register_no = er.register_no
    WHERE COALESCE(er.payment_status, 'Unpaid') != 'Paid'
       OR COALESCE(er.balance_due, 0) > 0
    ORDER BY er.registration_id DESC
    """)

    pending_registrations = cursor.fetchall()

    cursor.execute("""
    SELECT COALESCE(SUM(CASE WHEN balance_due > 0 THEN balance_due ELSE 0 END), 0)
    FROM exam_registration
    WHERE COALESCE(payment_status, 'Unpaid') != 'Paid'
       OR COALESCE(balance_due, 0) > 0
    """)

    total_pending = cursor.fetchone()[0]
    conn.close()

    return render_template(
        "admin_fees_pending.html",
        pending_registrations=pending_registrations,
        total_pending=total_pending,
    )


@route("/admin/link_student_login", methods=["POST"])
@roles_required("admin")
def link_student_login():

    payload = request.get_json(silent=True) or request.form

    register_no = str(payload.get("register_no", "")).strip()
    login_id_raw = payload.get("login_id", "")

    if not register_no or login_id_raw == "":
        return "register_no and login_id are required.", 400

    try:
        login_id = int(login_id_raw)
    except (TypeError, ValueError):
        return "login_id must be a valid integer.", 400

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT id, role FROM login WHERE id=?", (login_id,))
    login_row = cursor.fetchone()

    if login_row is None:
        conn.close()
        return "Login account not found.", 404

    if login_row["role"] != "student":
        conn.close()
        return "Only student login accounts can be linked.", 400

    cursor.execute(
        "SELECT id, login_id FROM students WHERE register_no=?",
        (register_no,)
    )
    student = cursor.fetchone()

    if student is None:
        conn.close()
        return "Student Not Found", 404

    cursor.execute(
        "SELECT register_no FROM students WHERE login_id=?",
        (login_id,)
    )
    existing_link = cursor.fetchone()

    if existing_link is not None and existing_link["register_no"] != register_no:
        conn.close()
        return "This student login is already linked to another student.", 409

    if student["login_id"] is not None and student["login_id"] != login_id:
        conn.close()
        return "This student record is already linked to another login.", 409

    if student["login_id"] == login_id:
        conn.close()
        return "Student login is already linked.", 200

    try:
        cursor.execute(
            "UPDATE students SET login_id=? WHERE register_no=?",
            (login_id, register_no)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return "This student login is already linked to another student.", 409

    conn.close()
    logger.info("Admin action=link_student username=%s register_no=%s", session.get("username"), register_no)
    return "Student login linked successfully.", 200


# ---------------- TEACHER ----------------

@route("/teacher")
@roles_required("admin", "teacher")
def teacher():
    conn = get_row_connection()
    cursor = conn.cursor()
    total_students = cursor.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    total_results = cursor.execute(
        "SELECT COUNT(*) FROM semester_results"
    ).fetchone()[0]
    total_subjects = cursor.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
    conn.close()
    return render_template(
        "teacher_dashboard.html",
        total_students=total_students,
        total_results=total_results,
        total_subjects=total_subjects,
    )


# ---------------- STUDENT ----------------

@route("/students")
@roles_required("admin", "teacher", "student")
def students():

    search = request.args.get("search", "")
    page, per_page = _pagination_values()
    offset = (page - 1) * per_page

    if session.get("role") == "student":

        identity = student_identity()

        if identity is None:
            return "Forbidden", 403

        student_id, student_register_no = identity

        conn = get_row_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM students
            WHERE id=? AND register_no=? AND login_id IS NOT NULL
            LIMIT ? OFFSET ?
            """,
            (student_id, student_register_no, per_page, offset)
        )

        data = cursor.fetchall()

        conn.close()

        if not data:
            return "Forbidden", 403

        return render_template(
            "student.html",
            students=data,
            page=page,
            per_page=per_page,
            total_pages=1,
        )

    conn = get_row_connection()

    cursor = conn.cursor()

    if search:
        filters = (
            "%" + search + "%",
            "%" + search + "%",
            "%" + search + "%",
        )
        cursor.execute("""
        SELECT COUNT(*)
        FROM students
        WHERE name LIKE ? OR department LIKE ? OR year LIKE ?
        """, filters)
        total = cursor.fetchone()[0]
        cursor.execute("""

        SELECT * FROM students

        WHERE

        name LIKE ?

        OR department LIKE ?

        OR year LIKE ?

        LIMIT ? OFFSET ?

        """,

        (*filters, per_page, offset))

    else:
        total = cursor.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        cursor.execute(
            "SELECT * FROM students LIMIT ? OFFSET ?",
            (per_page, offset),
        )

    data = cursor.fetchall()

    conn.close()

    return render_template(
        "student.html",
        students=data,
        page=page,
        per_page=per_page,
        total_pages=_total_pages(total, per_page),
    )


# ---------------- ADD STUDENT ----------------

@route("/add_student")
@roles_required("admin")
def add_student():
    return render_template("add_student.html")


# ---------------- SAVE STUDENT ----------------

@route("/save_student", methods=["POST"])
@roles_required("admin")
def save_student():

    conn = get_connection()

    cursor = conn.cursor()

    try:
        cursor.execute("""

   INSERT INTO students
    (
    register_no,
    name,
    department,
    year,
    study_hours,
    attendance,
    assignment_marks,
    internal_marks,
    cluster,
    recommendation,
    student_phone,
    parent_phone,
    email
    )

VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   
        """,(
        request.form["register_no"],
        request.form["name"],
        request.form["department"],
        request.form["year"],
        request.form["study_hours"],
        request.form["attendance"],
        request.form["assignment"],
        request.form["internal"],

        "Not Predicted",
        "Not Generated",

        request.form["student_phone"],
        request.form["parent_phone"],
        request.form["email"]

        ))
    except sqlite3.IntegrityError:
        conn.close()
        return "Register number already exists.", 409

    conn.commit()

    conn.close()

    logger.info("Admin action=add_student username=%s register_no=%s", session.get("username"), request.form["register_no"])
    return redirect("/students")


# ---------------- EDIT STUDENT ----------------

@route("/edit_student/<int:id>")
@roles_required("admin", "teacher")
def edit_student(id):

    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute("SELECT * FROM students WHERE id=?", (id,))
    student = cursor.fetchone()

    conn.close()

    if student is None:
        return "Student Not Found", 404

    return render_template("edit_student.html", student=student)

# ---------------- UPDATE STUDENT ----------------

@route("/update_student/<int:id>", methods=["POST"])
@roles_required("admin", "teacher")
def update_student(id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE students
    SET
    register_no=?,
    name=?,
    department=?,
    year=?,
    study_hours=?,
    attendance=?,
    assignment_marks=?,
    internal_marks=?,
    student_phone=?,
    parent_phone=?,
    email=?
    WHERE id=?
    """, (
        
        request.form["register_no"],
        request.form["name"],
        request.form["department"],
        request.form["year"],
        request.form["study_hours"],
        request.form["attendance"],
        request.form["assignment"],
        request.form["internal"],
        request.form["student_phone"],
        request.form["parent_phone"],
        request.form["email"],
        id

    ))

    conn.commit()
    conn.close()

    logger.info("Admin action=edit_student username=%s student_id=%s", session.get("username"), id)
    return redirect(url_for("students", message="Student information updated successfully."))

# ---------------- DELETE STUDENT ----------------

@route("/delete_student/<int:id>", methods=["POST"])
@roles_required("admin")
def delete_student(id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM students WHERE id=?",
        (id,)
    )

    if cursor.rowcount == 0:
        conn.close()
        return "Student Not Found", 404

    conn.commit()
    conn.close()

    logger.info("Admin action=delete_student username=%s student_id=%s", session.get("username"), id)
    return redirect("/students")

@route("/add_result")
@roles_required("admin", "teacher")
def add_result():

    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute("""
    SELECT register_no, name
    FROM students
    ORDER BY register_no
    """)

    students = cursor.fetchall()

    cursor.execute("""
    SELECT *
    FROM subjects
    ORDER BY semester, subject_name
    """)

    subjects = cursor.fetchall()

    conn.close()

    return render_template(
        "add_result.html",
        students=students,
        subjects=subjects
    )


@route("/save_result", methods=["POST"])
@roles_required("admin", "teacher")
def save_result():

    register_no = request.form["register_no"]
    semester = request.form["semester"]
    subject_code = request.form["subject_code"]
    try:
        semester = int(request.form["semester"])
        internal, external = parse_marks(
            request.form["internal_mark"],
            request.form["external_mark"],
        )
    except (KeyError, ValueError) as exc:
        return str(exc) or "Invalid result data.", 400

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT subject_name, credits
        FROM subjects
        WHERE subject_code=?
        """,
        (subject_code,)
    )

    row = cursor.fetchone()

    if row is None:
        conn.close()
        return "Subject Not Found", 404

    subject_name = row[0]
    credits = row[1]

    cursor.execute(
        """
        SELECT 1
        FROM semester_results
        WHERE register_no=? AND semester=? AND subject_code=?
        """,
        (register_no, semester, subject_code),
    )
    if cursor.fetchone() is not None:
        conn.close()
        return "Result already exists for this subject and semester.", 409

    total = internal + external
    grade, grade_point, result = calculate_grade(total)

    cursor.execute("""

    INSERT INTO semester_results(

    register_no,
    semester,
    subject_code,
    subject_name,
    internal_mark,
    external_mark,
    total_mark,
    grade,
    grade_point,
    credits,
    result

    )

    VALUES(?,?,?,?,?,?,?,?,?,?,?)

    """,(

    register_no,
    semester,
    subject_code,
    subject_name,
    internal,
    external,
    total,
    grade,
    grade_point,
    credits,
    result

    ))
# ---------------- UPDATE ARREAR COUNT ----------------

    cursor.execute("""

    SELECT COUNT(*)

    FROM semester_results

    WHERE register_no=?

    AND result='Fail'

    """,(register_no,))

    arrear_count = cursor.fetchone()[0]

    cursor.execute("""

    UPDATE students

    SET arrear_count=?

    WHERE register_no=?

    """,(arrear_count, register_no))

    conn.commit()

    conn.close()

    logger.info("Admin action=add_result username=%s register_no=%s subject_code=%s", session.get("username"), register_no, subject_code)
    return redirect("/results")

@route("/edit_result/<int:id>")
@roles_required("admin", "teacher")
def edit_result(id):

    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM semester_results WHERE result_id=?",
        (id,)
    )

    result = cursor.fetchone()

    conn.close()

    if result is None:
        return "Result Not Found", 404

    return render_template(
        "edit_result.html",
        result=result
    )

@route("/update_result/<int:id>", methods=["POST"])
@roles_required("admin", "teacher")
def update_result(id):

    register_no = request.form["register_no"]
    semester = request.form["semester"]
    subject_code = request.form["subject_code"]
    subject_name = request.form["subject_name"]

    try:
        semester = int(request.form["semester"])
        internal, external = parse_marks(
            request.form["internal_mark"],
            request.form["external_mark"],
        )
    except (KeyError, ValueError) as exc:
        return str(exc) or "Invalid result data.", 400

    total = internal + external
    grade, grade_point, result = calculate_grade(total)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT credits FROM subjects WHERE subject_code=?",
        (subject_code,)
    )
    subject = cursor.fetchone()
    credits = subject[0] if subject else 0

    cursor.execute(
        """
        SELECT 1
        FROM semester_results
        WHERE register_no=? AND semester=? AND subject_code=? AND result_id!=?
        """,
        (register_no, semester, subject_code, id),
    )
    if cursor.fetchone() is not None:
        conn.close()
        return "Result already exists for this subject and semester.", 409

    cursor.execute("""
    UPDATE semester_results
    SET
    register_no=?,
    semester=?,
    subject_code=?,
    subject_name=?,
    internal_mark=?,
    external_mark=?,
    total_mark=?,
    grade=?,
    grade_point=?,
    credits=?,
    result=?
    WHERE result_id=?
    """, (

        register_no,
        semester,
        subject_code,
        subject_name,
        internal,
        external,
        total,
        grade,
        grade_point,
        credits,
        result,
        id

    ))

    conn.commit()
    conn.close()

    logger.info("Admin action=edit_result username=%s result_id=%s", session.get("username"), id)
    return redirect("/results")

@route("/delete_result/<int:id>", methods=["POST"])
@roles_required("admin", "teacher")
def delete_result(id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM semester_results WHERE result_id=?",
        (id,)
    )

    if cursor.rowcount == 0:
        conn.close()
        return "Result Not Found", 404

    conn.commit()
    conn.close()

    logger.info("Admin action=delete_result username=%s result_id=%s", session.get("username"), id)
    return redirect("/results")

@route("/gpa/<register_no>/<int:semester>")
@roles_required("admin", "teacher", "student")
def gpa(register_no, semester):

    if session.get("role") == "student":

        identity = student_identity()

        if identity is None:
            return "Forbidden", 403

        _, student_register_no = identity

        if register_no != student_register_no:
            return "Forbidden", 403

    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM semester_results

    WHERE register_no=?
    AND semester=?
    """, (register_no, semester))

    results = cursor.fetchall()

    gpa = compute_gpa(results)
    total_credits = sum(r["credits"] for r in results)

    conn.close()

    return render_template(
        "gpa.html",
        results=results,
        gpa=gpa,
        register_no=register_no,
        semester=semester
    )

# ---------------- PREDICT ----------------

@route("/predict/<int:id>", methods=["POST"])
@roles_required("admin", "teacher")
def predict(id):

    conn = get_row_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM students WHERE id=?", (id,))
    student = cursor.fetchone()

    if student is None:
        conn.close()
        return "Student Not Found"

    try:
        level, recommendation = predict_student_performance(student)
    except ValueError as exc:
        conn.close()
        return str(exc), 400
    except FileNotFoundError as exc:
        conn.close()
        return str(exc), 500

    cursor.execute("""
    UPDATE students
    SET cluster=?, recommendation=?
    WHERE id=?
    """, (level, recommendation, id))

    conn.commit()
    conn.close()

    return redirect("/students")

@route("/results")
@roles_required("admin", "teacher")
def results():

    page, per_page = _pagination_values()
    offset = (page - 1) * per_page
    conn = get_row_connection()

    cursor = conn.cursor()

    total = cursor.execute("SELECT COUNT(*) FROM semester_results").fetchone()[0]
    cursor.execute("""
    SELECT * FROM semester_results
    ORDER BY register_no, semester
    LIMIT ? OFFSET ?
    """, (per_page, offset))

    results = cursor.fetchall()

    conn.close()

    return render_template(
        "results.html",
        results=results,
        page=page,
        per_page=per_page,
        total_pages=_total_pages(total, per_page),
    )

@route("/exam_registration")
@roles_required("admin", "teacher")
def exam_registration():

    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute("SELECT * FROM students")

    students = cursor.fetchall()

    conn.close()

    return render_template(
        "exam_registration.html",
        students=students,
        message=request.args.get("message")
    )


@route("/save_exam_registration", methods=["POST"])
@roles_required("admin", "teacher")
def save_exam_registration():

    register_no = request.form.get("register_no", "").strip()
    semester = request.form.get("semester", "").strip()
    exam_type = request.form.get("exam_type", "").strip()
    exam_fee = request.form.get("exam_fee", "").strip()
    registration_date = request.form.get("registration_date", "").strip()

    if not all((register_no, semester, exam_type, exam_fee, registration_date)):
        return "All exam registration fields are required.", 400

    try:
        semester = int(semester)
        exam_fee = float(exam_fee)
    except ValueError:
        return "Semester and exam fee must be valid numbers.", 400

    if semester < 1 or semester > 8 or exam_fee < 0:
        return "Semester or exam fee is invalid.", 400

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT 1 FROM students WHERE register_no=?",
        (register_no,)
    )

    if cursor.fetchone() is None:
        conn.close()
        return "Student Not Found", 404

    cursor.execute("""
    SELECT 1
    FROM exam_registration
    WHERE register_no=? AND semester=? AND exam_type=?
    """, (register_no, semester, exam_type))

    if cursor.fetchone() is not None:
        conn.close()
        return "Exam registration already exists for this student.", 409

    cursor.execute("""
    INSERT INTO exam_registration(
        register_no,
        semester,
        exam_type,
        exam_fee,
        registration_date,
        amount_paid,
        balance_due,
        payment_status,
        last_payment_date,
        status
    )
    VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        register_no,
        semester,
        exam_type,
        exam_fee,
        registration_date,
        0,
        exam_fee,
        "Unpaid",
        "",
        "Registered"
    ))

    conn.commit()
    conn.close()

    logger.info("Admin action=add_exam_registration username=%s register_no=%s", session.get("username"), register_no)
    return redirect(url_for(
        "exam_registration",
        message="Exam registration saved successfully."
    ))

# ---------------- ACADEMIC SUMMARY ----------------

@route("/academic_summary/<register_no>/<int:semester>")
@roles_required("admin", "teacher", "student")
def academic_summary(register_no, semester):

    if session.get("role") == "student":

        identity = student_identity()

        if identity is None:
            return "Forbidden", 403

        _, student_register_no = identity

        if register_no != student_register_no:
            return "Forbidden", 403

    conn = get_row_connection()

    cursor = conn.cursor()

    # Student Details
    cursor.execute("""
    SELECT *
    FROM students
    WHERE register_no=?
    """, (register_no,))

    student = cursor.fetchone()

    if student is None:
        conn.close()
        return "Student Not Found"

    # Semester Results
    cursor.execute("""
    SELECT *
    FROM semester_results
    WHERE register_no=? AND semester=?
    """, (register_no, semester))

    results = cursor.fetchall()

    summary = compute_summary(results)

    conn.close()

    return render_template(
        "academic_summary.html",
        student=student,
        results=results,
        semester=semester,
        total_credits=summary["total_credits"],
        pass_count=summary["pass_count"],
        fail_count=summary["fail_count"],
        gpa=summary["gpa"],
        percentage=summary["average_marks"],
        average_marks=summary["average_marks"],
    )

# ---------------- SUBJECTS ----------------

@route("/subjects")
@roles_required("admin", "teacher")
def subjects():

    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute("SELECT * FROM subjects ORDER BY semester")

    subjects = cursor.fetchall()

    conn.close()

    return render_template(
        "subjects.html",
        subjects=subjects
    )


# ---------------- ADD SUBJECT ----------------

@route("/add_subject")
@roles_required("admin")
def add_subject():

    return render_template("add_subject.html")


# ---------------- SAVE SUBJECT ----------------

@route("/save_subject", methods=["POST"])
@roles_required("admin")
def save_subject():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""

    INSERT INTO subjects(

    subject_code,
    subject_name,
    semester,
    credits

    )

    VALUES(?,?,?,?)

    """,(

    request.form["subject_code"],
    request.form["subject_name"],
    request.form["semester"],
    request.form["credits"]

    ))

    conn.commit()

    conn.close()

    logger.info("Admin action=add_subject username=%s subject_code=%s", session.get("username"), request.form["subject_code"])
    return redirect("/subjects")

@route("/edit_subject/<int:id>")
@roles_required("admin")
def edit_subject(id):

    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM subjects WHERE subject_id=?",
        (id,)
    )

    subject = cursor.fetchone()

    conn.close()

    if subject is None:
        return "Subject Not Found", 404

    return render_template(
        "edit_subject.html",
        subject=subject
    )

@route("/update_subject/<int:id>", methods=["POST"])
@roles_required("admin")
def update_subject(id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""

    UPDATE subjects

    SET

    subject_code=?,

    subject_name=?,

    semester=?,

    credits=?

    WHERE subject_id=?

    """,(

    request.form["subject_code"],
    request.form["subject_name"],
    request.form["semester"],
    request.form["credits"],
    id

    ))

    conn.commit()

    conn.close()

    logger.info("Admin action=edit_subject username=%s subject_id=%s", session.get("username"), id)
    return redirect("/subjects")

@route("/delete_subject/<int:id>", methods=["POST"])
@roles_required("admin")
def delete_subject(id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM subjects WHERE subject_id=?",
        (id,)
    )

    if cursor.rowcount == 0:
        conn.close()
        return "Subject Not Found", 404

    conn.commit()

    conn.close()

    logger.info("Admin action=delete_subject username=%s subject_id=%s", session.get("username"), id)
    return redirect("/subjects")

# ---------------- ANALYTICS ----------------

@route("/analytics")
@roles_required("admin", "teacher")
def analytics():

    conn = get_row_connection()
    cursor = conn.cursor()

    # Total Students
    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]

    # Performance Counts
    cursor.execute("SELECT COUNT(*) FROM students WHERE cluster='Excellent'")
    excellent = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM students WHERE cluster='Average'")
    average = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM students WHERE cluster='Need Improvement'"
    )
    weak = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM students WHERE cluster='Not Predicted'")
    not_predicted = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "analytics.html",
        total_students=total_students,
        excellent=excellent,
        average=average,
        weak=weak,
        not_predicted=not_predicted
    )


@route("/analytics/data")
@roles_required("admin", "teacher")
def analytics_data():
    conn = get_row_connection()
    rows = conn.execute(
        """
        SELECT study_hours, internal_marks, COALESCE(cluster, 'Not Predicted') AS cluster
        FROM students
        WHERE study_hours IS NOT NULL AND internal_marks IS NOT NULL
        """
    ).fetchall()
    conn.close()
    return jsonify([
        {
            "x": float(row["study_hours"]),
            "y": float(row["internal_marks"]),
            "cluster": row["cluster"],
        }
        for row in rows
    ])


# ---------------- FEES ----------------

@route("/fees")
@roles_required("admin", "student")
def fees():

    conn = get_row_connection()
    cursor = conn.cursor()

    if session.get("role") == "student":
        identity = student_identity()
        if identity is None:
            conn.close()
            return "Forbidden", 403

        _, register_no = identity
        cursor.execute("""
        SELECT
            er.registration_id,
            er.register_no,
            s.name,
            s.department,
            s.year,
            er.semester,
            er.exam_type,
            er.exam_fee,
            er.amount_paid,
            er.balance_due,
            er.payment_status,
            er.registration_date,
            er.last_payment_date,
            (
                SELECT p.payment_id
                FROM payments p
                WHERE p.registration_id = er.registration_id
                ORDER BY p.payment_id DESC
                LIMIT 1
            ) AS last_payment_id
        FROM exam_registration er
        LEFT JOIN students s ON s.register_no = er.register_no
        WHERE er.register_no=?
        ORDER BY er.registration_id DESC
        """, (register_no,))
        registrations = cursor.fetchall()
        conn.close()
        return render_template(
            "fees.html",
            registrations=registrations,
            message=request.args.get("message"),
            student_view=True
        )

    cursor.execute("""
    SELECT
        er.registration_id,
        er.register_no,
        s.name,
        s.department,
        s.year,
        er.semester,
        er.exam_type,
        er.exam_fee,
        er.amount_paid,
        er.balance_due,
        er.payment_status,
        er.registration_date,
        er.last_payment_date,
        (
            SELECT p.payment_id
            FROM payments p
            WHERE p.registration_id = er.registration_id
            ORDER BY p.payment_id DESC
            LIMIT 1
        ) AS last_payment_id
    FROM exam_registration er
    LEFT JOIN students s
        ON s.register_no = er.register_no
    ORDER BY er.registration_id DESC
    """)

    registrations = cursor.fetchall()

    conn.close()

    return render_template(
        "fees.html",
        registrations=registrations,
        message=request.args.get("message"),
        student_view=False
    )


@route("/admin/fees/<int:registration_id>/confirm-upi", methods=["POST"])
@roles_required("admin")
def confirm_upi(registration_id):
    transaction_ref = request.form.get("transaction_ref", "").strip()
    if not transaction_ref:
        return "UPI transaction reference is required.", 400

    conn = get_row_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT registration_id, register_no, balance_due, payment_status
        FROM exam_registration
        WHERE registration_id=?
        """,
        (registration_id,),
    )
    registration = cursor.fetchone()
    if registration is None:
        conn.close()
        return "Exam registration not found.", 404
    if registration["payment_status"] == "Paid" or registration["balance_due"] <= 0:
        conn.close()
        return "Payment is already completed.", 409

    cursor.execute(
        "SELECT 1 FROM payments WHERE transaction_ref=?",
        (transaction_ref,),
    )
    if cursor.fetchone() is not None:
        conn.close()
        return "Transaction reference already exists.", 409

    amount = float(registration["balance_due"])
    payment_date = datetime.now().strftime("%Y-%m-%d")
    try:
        cursor.execute(
            """
            INSERT INTO payments(
                registration_id, register_no, amount, payment_date,
                payment_mode, transaction_ref, status
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                registration_id,
                registration["register_no"],
                amount,
                payment_date,
                "UPI Manual",
                transaction_ref,
                "Success",
            ),
        )
        cursor.execute(
            """
            UPDATE exam_registration
            SET amount_paid=COALESCE(amount_paid, 0) + ?,
                balance_due=0, payment_status='Paid',
                status='Paid', last_payment_date=?
            WHERE registration_id=?
            """,
            (amount, payment_date, registration_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return "Transaction reference already exists.", 409
    conn.close()
    logger.info(
        "Payment event=manual_upi_success admin=%s registration_id=%s transaction_ref=%s",
        session.get("username"),
        registration_id,
        transaction_ref,
    )
    return redirect(url_for("fees", message="UPI payment confirmed."))


@route("/payment/<int:registration_id>")
@roles_required("student")
def payment(registration_id):

    conn = get_row_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        er.registration_id,
        er.register_no,
        s.name,
        s.department,
        s.year,
        er.semester,
        er.exam_type,
        er.exam_fee,
        er.amount_paid,
        er.balance_due,
        er.payment_status,
        er.registration_date
    FROM exam_registration er
    LEFT JOIN students s
        ON s.register_no = er.register_no
    WHERE er.registration_id=?
    """, (registration_id,))

    registration = cursor.fetchone()

    conn.close()

    if registration is None:
        return "Exam registration not found.", 404

    identity = student_identity()
    if identity is None or registration["register_no"] != identity[1]:
        return "Forbidden", 403

    if registration["payment_status"] == "Paid" or registration["balance_due"] <= 0:
        return redirect(url_for(
            "fees",
            message="Payment already completed for this registration."
        ))

    balance_due = float(registration["balance_due"])
    upi_link = ""
    payment_message = request.args.get("message")
    if not UPI_ID:
        payment_message = "Payment details not configured. Contact admin."
    elif balance_due > 0:
        upi_link = "upi://pay?" + urlencode({
            "pa": UPI_ID,
            "pn": UPI_PAYEE_NAME,
            "am": f"{balance_due:.2f}",
            "cu": "INR",
            "tn": "Exam Fee Payment",
        })

    return render_template(
        "payment.html",
        registration=registration,
        message=payment_message,
        upi_id=UPI_ID,
        upi_number=UPI_NUMBER,
        payee_name=UPI_PAYEE_NAME,
        upi_link=upi_link,
        payment_amount=balance_due
    )


@route("/payment/qr/status/<int:registration_id>")
@roles_required("student")
def payment_qr_status(registration_id):

    conn = get_row_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT registration_id, register_no, balance_due, payment_status,
           gateway_order_id, gateway_session_created_at, gateway_qr_id,
           gateway_payment_id
    FROM exam_registration
    WHERE registration_id=?
    """, (registration_id,))
    registration = cursor.fetchone()

    if registration is None:
        conn.close()
        return jsonify({"status": "not_found"}), 404

    identity = student_identity()
    if identity is None or registration["register_no"] != identity[1]:
        conn.close()
        return jsonify({"status": "forbidden"}), 403

    if registration["payment_status"] == "Paid" or registration["gateway_payment_id"]:
        conn.close()
        return jsonify({"status": "paid"})

    try:
        created_at = datetime.fromisoformat(registration["gateway_session_created_at"])
        if (datetime.utcnow() - created_at).total_seconds() >= PAYMENT_SESSION_SECONDS:
            conn.close()
            return jsonify({"status": "expired"}), 410
    except (TypeError, ValueError):
        conn.close()
        return jsonify({"status": "invalid_session"}), 400

    if not registration["gateway_qr_id"]:
        conn.close()
        return jsonify({"status": "pending"})

    client = razorpay_client()
    if client is None:
        conn.close()
        return jsonify({"status": "gateway_unavailable"}), 503

    try:
        qr_id = registration["gateway_qr_id"]
        qr_details = client.get("/v1/payments/qr_codes/" + qr_id)
        notes = qr_details.get("notes") or {}
        if (
            notes.get("registration_id") not in (None, str(registration_id))
            or notes.get("order_id") not in (None, registration["gateway_order_id"])
        ):
            conn.close()
            return jsonify({"status": "invalid_session"}), 400

        payments_response = client.get(
            "/v1/payments/qr_codes/" + qr_id + "/payments"
        )
        qr_payments = payments_response.get("items", [])
        expected_amount = int(round(float(registration["balance_due"]) * 100))
        captured_payment = next(
            (
                item for item in qr_payments
                if item.get("status") == "captured"
                and item.get("amount") == expected_amount
                and item.get("currency") == "INR"
                and item.get("qr_code_id", qr_id) == qr_id
            ),
            None
        )
    except Exception:
        conn.close()
        return jsonify({"status": "pending"})

    if captured_payment is None:
        conn.close()
        return jsonify({"status": "pending"})

    payment_id = captured_payment["id"]
    payment_date = datetime.now().strftime("%Y-%m-%d")
    amount = float(registration["balance_due"])
    transaction_ref = "RZP-QR-" + payment_id

    cursor.execute("""
    INSERT INTO payments(
        registration_id, register_no, amount, payment_date,
        payment_mode, transaction_ref, status, gateway_order_id,
        gateway_payment_id, gateway_signature
    ) VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        registration_id, registration["register_no"], amount, payment_date,
        "Razorpay UPI QR", transaction_ref, "Success",
        registration["gateway_order_id"], payment_id, ""
    ))
    cursor.execute("""
    UPDATE exam_registration
    SET amount_paid = COALESCE(amount_paid, 0) + ?, balance_due=0,
        payment_status='Paid', status='Paid', last_payment_date=?,
        gateway_payment_id=?
    WHERE registration_id=? AND payment_status!='Paid'
    """, (amount, payment_date, payment_id, registration_id))
    conn.commit()
    conn.close()
    logger.info(
        "Payment event=razorpay_qr_success registration_id=%s payment_id=%s",
        registration_id,
        payment_id,
    )
    return jsonify({"status": "paid", "payment_id": payment_id})


@route("/save_payment/<int:registration_id>", methods=["POST"])
@roles_required("student")
def save_payment(registration_id):

    payment_id = request.form.get("razorpay_payment_id", "").strip()
    order_id = request.form.get("razorpay_order_id", "").strip()
    signature = request.form.get("razorpay_signature", "").strip()

    conn = get_row_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT registration_id, register_no, balance_due, payment_status,
            gateway_order_id, gateway_session_created_at, gateway_payment_id
    FROM exam_registration
    WHERE registration_id=?
    """, (registration_id,))
    registration = cursor.fetchone()

    if registration is None:
        conn.close()
        return "Exam registration not found.", 404

    identity = student_identity()
    if identity is None or registration["register_no"] != identity[1]:
        conn.close()
        return "Forbidden", 403

    if registration["payment_status"] == "Paid" or registration["balance_due"] <= 0:
        conn.close()
        return "Payment already completed for this registration.", 409

    if registration["gateway_payment_id"]:
        conn.close()
        return "Payment session has already been completed.", 409

    if not all((payment_id, order_id, signature)):
        conn.close()
        return "Incomplete or unverified payment response.", 400

    if order_id != registration["gateway_order_id"]:
        conn.close()
        return "Invalid payment order.", 400

    try:
        created_at = datetime.fromisoformat(registration["gateway_session_created_at"])
        if (datetime.utcnow() - created_at).total_seconds() >= PAYMENT_SESSION_SECONDS:
            conn.close()
            return redirect(url_for("payment", registration_id=registration_id, message="QR Code Expired. Generate a new payment session."))
    except (TypeError, ValueError):
        conn.close()
        return "Invalid payment session.", 400

    client = razorpay_client()
    if client is None:
        conn.close()
        return "Payment gateway is not configured.", 503

    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature
        })
    except razorpay.errors.SignatureVerificationError:
        conn.close()
        return redirect(url_for("payment", registration_id=registration_id, message="Payment verification failed. Fee remains pending."))

    try:
        expected_amount = int(round(float(registration["balance_due"]) * 100))
        gateway_order = client.order.fetch(order_id)
        gateway_payment = client.payment.fetch(payment_id)
        if (
            gateway_order.get("amount") != expected_amount
            or gateway_order.get("currency") != "INR"
            or gateway_payment.get("order_id") != order_id
            or gateway_payment.get("amount") != expected_amount
            or gateway_payment.get("currency") != "INR"
            or gateway_payment.get("status") != "captured"
        ):
            conn.close()
            return redirect(url_for("payment", registration_id=registration_id, message="Payment could not be verified. Fee remains pending."))
    except Exception:
        conn.close()
        return redirect(url_for("payment", registration_id=registration_id, message="Payment verification failed. Fee remains pending."))

    payment_date = datetime.now().strftime("%Y-%m-%d")
    transaction_ref = "RZP-" + payment_id
    amount = float(registration["balance_due"])

    cursor.execute("""
    INSERT INTO payments(
        registration_id, register_no, amount, payment_date,
        payment_mode, transaction_ref, status, gateway_order_id,
        gateway_payment_id, gateway_signature
    ) VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        registration_id, registration["register_no"], amount, payment_date,
        "Razorpay UPI", transaction_ref, "Success", order_id,
        payment_id, signature
    ))
    receipt_id = cursor.lastrowid

    cursor.execute("""
    UPDATE exam_registration
    SET amount_paid = COALESCE(amount_paid, 0) + ?, balance_due=0,
        payment_status='Paid', status='Paid', last_payment_date=?,
        gateway_payment_id=?
    WHERE registration_id=? AND payment_status!='Paid'
    """, (amount, payment_date, payment_id, registration_id))

    conn.commit()
    conn.close()
    logger.info(
        "Payment event=razorpay_success registration_id=%s payment_id=%s",
        registration_id,
        payment_id,
    )
    return redirect(url_for("receipt", payment_id=receipt_id))


@route("/receipt/<int:payment_id>")
@roles_required("admin", "student")
def receipt(payment_id):

    conn = get_row_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        p.payment_id,
        p.registration_id,
        p.register_no,
        p.amount,
        p.payment_date,
        p.payment_mode,
        p.transaction_ref,
        p.status AS payment_result,
        er.semester,
        er.exam_type,
        er.exam_fee,
        er.registration_date,
        s.name,
        s.department,
        s.year
    FROM payments p
    LEFT JOIN exam_registration er
        ON er.registration_id = p.registration_id
    LEFT JOIN students s
        ON s.register_no = p.register_no
    WHERE p.payment_id=?
    """, (payment_id,))

    payment_data = cursor.fetchone()

    conn.close()

    if payment_data is None:
        return "Payment receipt not found.", 404

    if session.get("role") == "student":
        identity = student_identity()
        if identity is None or payment_data["register_no"] != identity[1]:
            return "Forbidden", 403

    return render_template(
        "receipt.html",
        payment=payment_data
    )


@route("/receipt/<int:payment_id>.pdf")
@roles_required("admin", "student")
def receipt_pdf(payment_id):
    conn = get_row_connection()
    payment_data = conn.execute(
        """
        SELECT
            p.payment_id, p.registration_id, p.register_no, p.amount,
            p.payment_date, p.payment_mode, p.transaction_ref,
            p.status AS payment_result, er.semester, er.exam_type,
            er.exam_fee, er.registration_date, s.name, s.department, s.year
        FROM payments p
        LEFT JOIN exam_registration er ON er.registration_id = p.registration_id
        LEFT JOIN students s ON s.register_no = p.register_no
        WHERE p.payment_id=?
        """,
        (payment_id,),
    ).fetchone()
    conn.close()
    if payment_data is None:
        return "Payment receipt not found.", 404

    if session.get("role") == "student":
        identity = student_identity()
        if identity is None or payment_data["register_no"] != identity[1]:
            return "Forbidden", 403

    return _pdf_response(
        "Payment Receipt",
        [
            ("Payment ID", payment_data["payment_id"]),
            ("Registration ID", payment_data["registration_id"]),
            ("Register No", payment_data["register_no"]),
            ("Name", payment_data["name"]),
            ("Amount", payment_data["amount"]),
            ("Payment Date", payment_data["payment_date"]),
            ("Payment Mode", payment_data["payment_mode"]),
            ("Transaction Reference", payment_data["transaction_ref"]),
            ("Status", payment_data["payment_result"]),
        ],
        f"receipt_{payment_id}.pdf",
    )


# ---------------- TEACHER MANAGEMENT ----------------

@route("/teacher_management")
@roles_required("admin")
def teacher_management():
    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, username, role FROM login WHERE role='teacher' ORDER BY id"
    )

    teachers = cursor.fetchall()

    conn.close()

    return render_template("teacher_management.html", teachers=teachers)

# ---------------- FORGOT PASSWORD ----------------
@route("/forgot_password")
def forgot_password():

    return render_template("forgot_password.html")

# ---------------- CHANGE PASSWORD ----------------

@route("/change_password", methods=["POST"])
def change_password():

    username = request.form["username"]
    old_password = request.form["old_password"]
    new_password = request.form["new_password"]
    confirm_password = request.form["confirm_password"]

    if new_password != confirm_password:
        return "New Password and Confirm Password do not match."

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM login WHERE username=? AND role IN ('admin', 'teacher', 'student')",
        (username,)
    )

    user = cursor.fetchone()

    if user:
        stored_password = user["password"]
        password_matches = (
            check_password_hash(stored_password, old_password)
            if stored_password.startswith(("scrypt:", "pbkdf2:"))
            else stored_password == old_password
        )

        if not password_matches:
            conn.close()
            return """
            <h2>Old Password Incorrect <svg width="18" height="18" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></h2>

            <a href="/forgot_password">Try Again</a>
            """

        cursor.execute(
            "UPDATE login SET password=? WHERE username=? AND role=?",
            (generate_password_hash(new_password), username, user["role"])
        )

        conn.commit()
        conn.close()

        return """
        <h2>Password Changed Successfully <svg width="18" height="18" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></h2>

        <a href="/">Login Again</a>
        """

    conn.close()

    return """
    <h2>Old Password Incorrect <svg width="18" height="18" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></h2>

    <a href="/forgot_password">Try Again</a>
    """
# ---------------- PROFILE ----------------

@route("/profile/<int:id>")
@roles_required("admin", "teacher", "student")
def profile(id):

    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM students WHERE id=?",
        (id,)
    )

    student = cursor.fetchone()
    # Check Exam Fee

    if student is None:
        conn.close()
        return "Student Not Found", 404

    if session.get("role") == "student":

        identity = student_identity()

        if identity is None:
            conn.close()
            return "Forbidden", 403

        student_id, _ = identity

        if id != student_id:
            conn.close()
            return "Forbidden", 403

    explanation = None
    if student["cluster"] and student["cluster"] != "Not Predicted":
        try:
            explanation = explain_cluster(student)
        except (FileNotFoundError, ValueError):
            explanation = None

    conn.close()

    return render_template(
        "profile.html",
        student=student,
        explanation=explanation,
    )
# ---------------- GENERATE HALL TICKET ----------------

@route("/generate_hallticket/<int:id>", methods=["POST"])
@roles_required("admin", "teacher")
def generate_hallticket(id):

    conn = get_row_connection()

    cursor = conn.cursor()

    # Student Details
    cursor.execute(
        "SELECT * FROM students WHERE id=?",
        (id,)
    )

    student = cursor.fetchone()

    if student is None:
        conn.close()
        return "Student Not Found", 404

    cursor.execute("""
    SELECT COUNT(*) AS pending_count
    FROM exam_registration
    WHERE register_no=?
    AND (
        COALESCE(payment_status, 'Unpaid') != 'Paid'
        OR COALESCE(balance_due, 0) > 0
    )
    """, (student["register_no"],))

    pending = cursor.fetchone()

    if pending["pending_count"] > 0:
        conn.close()
        return """
        <h2>Hall Ticket Cannot Be Generated</h2>
        <h3>Pending Exam Registration Fee Payment</h3>
        <a href="/students">Go Back</a>
        """

    hall_ticket_no = (
        "HT"
        + str(datetime.now().year)
        + student["register_no"]
    )

    generated_date = datetime.now().strftime("%d-%m-%Y")

    cursor.execute("""

    UPDATE students

    SET

    hall_ticket_status=?,

    hall_ticket_no=?,

    hall_ticket_generated_date=?

    WHERE id=?

    """,(

    "Generated",

    hall_ticket_no,

    generated_date,

    id

    ))

    conn.commit()

    conn.close()

    logger.info("Admin action=generate_hallticket username=%s student_id=%s", session.get("username"), id)
    return redirect("/students")

# ---------------- HALL TICKET ----------------

@route("/hall_ticket/<int:id>")
@roles_required("admin", "teacher", "student")
def hall_ticket(id):

    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM students WHERE id=?",
        (id,)
    )

    student = cursor.fetchone()

    conn.close()

    if student is None:
        return "Student Not Found", 404

    if session.get("role") == "student":

        identity = student_identity()

        if identity is None:
            conn.close()
            return "Forbidden", 403

        student_id, _ = identity

        if id != student_id:
            conn.close()
            return "Forbidden", 403

    return render_template(
        "hall_ticket.html",
        student=student
    )


def _pdf_response(title, lines, filename):
    if canvas is None or A4 is None:
        return "PDF support is not installed.", 503

    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=A4)
    _, height = A4
    document.setTitle(title)
    document.setFont("Helvetica-Bold", 16)
    document.drawString(50, height - 60, title)
    document.setFont("Helvetica", 11)
    y = height - 95
    for label, value in lines:
        document.drawString(50, y, f"{label}: {value}")
        y -= 22
        if y < 50:
            document.showPage()
            y = height - 60
    document.save()
    output.seek(0)
    return send_file(
        output,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@route("/hall_ticket/<int:id>.pdf")
@roles_required("admin", "teacher", "student")
def hall_ticket_pdf(id):
    conn = get_row_connection()
    student = conn.execute(
        "SELECT * FROM students WHERE id=?",
        (id,),
    ).fetchone()
    conn.close()
    if student is None:
        return "Student Not Found", 404

    if session.get("role") == "student":
        identity = student_identity()
        if identity is None or identity[0] != id:
            return "Forbidden", 403

    return _pdf_response(
        "Hall Ticket",
        [
            ("Register No", student["register_no"]),
            ("Name", student["name"]),
            ("Department", student["department"]),
            ("Year", student["year"]),
            ("Hall Ticket No", student["hall_ticket_no"]),
            ("Generated Date", student["hall_ticket_generated_date"]),
            ("Status", student["hall_ticket_status"]),
        ],
        f"hall_ticket_{id}.pdf",
    )


# ---------------- LOGOUT ----------------

@route("/logout")
def logout():

    session.clear()

    return redirect(url_for("index"))


# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(debug=DEBUG)
