from datetime import datetime
import os
import uuid
import sqlite3
import math
from urllib.parse import urlencode

from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash, generate_password_hash
import razorpay

import database as _database
from config import DEBUG, SECRET_KEY, UPI_ID, UPI_NUMBER, UPI_PAYEE
from services.grades import calculate_grade
from services.prediction import predict_student_performance
from utils.auth import login_required, roles_required, student_identity
from utils.database import get_connection, get_row_connection

app = Flask(__name__)

app.secret_key = SECRET_KEY

PAYMENT_SESSION_SECONDS = 5 * 60


def _parse_float(form, field, label, minimum=None, maximum=None):
    """Read and validate a numeric form value."""
    raw = form.get(field, "").strip()
    if raw == "":
        raise ValueError(f"{label} is required.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a valid number.")
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must not exceed {maximum}.")
    return value


def _refresh_arrear_count(conn, register_no):
    """Recalculate the student's current failed-subject count."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM semester_results WHERE register_no=? AND result='Fail'",
        (register_no,),
    )
    arrear_count = cursor.fetchone()[0]
    cursor.execute(
        "UPDATE students SET arrear_count=? WHERE register_no=?",
        (arrear_count, register_no),
    )


def razorpay_client():
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")

    if not key_id or not key_secret:
        return None

    return razorpay.Client(auth=(key_id, key_secret))


# ---------------- HOME ----------------

@app.route("/")
def index():
    return redirect(url_for("student_login"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        return authenticate_login("admin")
    return render_template(
        "login.html",
        login_role="admin",
        login_title="Admin Login",
        login_action=url_for("admin_login")
    )


@app.route("/teacher/login", methods=["GET", "POST"])
def teacher_login():
    if request.method == "POST":
        return authenticate_login("teacher")
    return render_template(
        "login.html",
        login_role="teacher",
        login_title="Teacher Login",
        login_action=url_for("teacher_login")
    )


@app.route("/student/login", methods=["GET", "POST"])
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

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM login WHERE username=? AND role=?",
        (username, role)
    )

    user = cursor.fetchone()
    if user is not None:
        stored_password = user["password"]
        valid_password = False
        try:
            valid_password = check_password_hash(stored_password, password)
        except (ValueError, TypeError):
            valid_password = False

        # Backward compatibility for an existing local database.
        # Successful legacy logins are upgraded to a password hash.
        if not valid_password and stored_password == password:
            valid_password = True
            cursor.execute(
                "UPDATE login SET password=? WHERE id=?",
                (generate_password_hash(password), user["id"]),
            )
            conn.commit()

        if not valid_password:
            user = None

    if user:

        session["username"] = username
        session["role"] = user["role"]
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
    return "Invalid Login", 401


@app.route("/login", methods=["POST"])
def login():
    return "Use the role-specific login page.", 400


# ---------------- ADMIN ----------------

@app.route("/admin")
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


@app.route("/admin/students")
@roles_required("admin")
def admin_students():

    search = request.args.get("search", "")

    conn = get_row_connection()
    cursor = conn.cursor()

    if search:
        cursor.execute("""
        SELECT * FROM students
        WHERE name LIKE ?
           OR department LIKE ?
           OR year LIKE ?
        ORDER BY register_no
        """, (
            "%" + search + "%",
            "%" + search + "%",
            "%" + search + "%",
        ))
    else:
        cursor.execute("SELECT * FROM students ORDER BY register_no")

    students = cursor.fetchall()
    conn.close()

    return render_template(
        "student.html",
        students=students,
        show_back_to_dashboard=True,
    )


@app.route("/admin/teachers")
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


@app.route("/admin/fees/collected")
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


@app.route("/admin/fees/pending")
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


@app.route("/admin/link_student_login", methods=["POST"])
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
    return "Student login linked successfully.", 200


# ---------------- TEACHER ----------------

@app.route("/teacher")
@roles_required("admin", "teacher")
def teacher():
    return render_template("teacher_dashboard.html")


# ---------------- STUDENT ----------------

@app.route("/students")
@roles_required("admin", "teacher", "student")
def students():

    search = request.args.get("search", "")

    if session.get("role") == "student":

        identity = student_identity()

        if identity is None:
            return "Forbidden", 403

        student_id, student_register_no = identity

        conn = get_row_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM students WHERE id=? AND register_no=? AND login_id IS NOT NULL",
            (student_id, student_register_no)
        )

        data = cursor.fetchall()

        conn.close()

        if not data:
            return "Forbidden", 403

        return render_template("student.html", students=data)

    conn = get_row_connection()

    cursor = conn.cursor()

    if search:

        cursor.execute("""

        SELECT * FROM students

        WHERE

        name LIKE ?

        OR department LIKE ?

        OR year LIKE ?

        """,

        (

        "%" + search + "%",

        "%" + search + "%",

        "%" + search + "%"

        ))

    else:

        cursor.execute("SELECT * FROM students")

    data = cursor.fetchall()

    conn.close()

    return render_template("student.html",

                           students=data)


# ---------------- ADD STUDENT ----------------

@app.route("/add_student")
@roles_required("admin")
def add_student():
    return render_template("add_student.html")


# ---------------- SAVE STUDENT ----------------

@app.route("/save_student", methods=["POST"])
@roles_required("admin")
def save_student():
    register_no = request.form.get("register_no", "").strip()
    name = request.form.get("name", "").strip()
    department = request.form.get("department", "").strip()
    year = request.form.get("year", "").strip()
    student_phone = request.form.get("student_phone", "").strip()
    parent_phone = request.form.get("parent_phone", "").strip()
    email = request.form.get("email", "").strip()

    if not all((register_no, name, department, year, student_phone, parent_phone, email)):
        return "All student fields are required.", 400

    try:
        study_hours = _parse_float(request.form, "study_hours", "Study hours", 0)
        attendance = _parse_float(request.form, "attendance", "Attendance", 0, 100)
        assignment = _parse_float(request.form, "assignment", "Assignment marks", 0, 100)
        internal = _parse_float(request.form, "internal", "Internal marks", 0, 100)
    except ValueError as exc:
        return str(exc), 400

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO students(
            register_no, name, department, year, study_hours, attendance,
            assignment_marks, internal_marks, cluster, recommendation,
            student_phone, parent_phone, email
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            register_no, name, department, year, study_hours, attendance,
            assignment, internal, "Not Predicted", "Not Generated",
            student_phone, parent_phone, email
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return "A student with this register number already exists.", 409
    finally:
        conn.close()

    return redirect(url_for("students"))


# ---------------- EDIT STUDENT ----------------

@app.route("/edit_student/<int:id>")
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

@app.route("/update_student/<int:id>", methods=["POST"])
@roles_required("admin", "teacher")
def update_student(id):
    register_no = request.form.get("register_no", "").strip()
    name = request.form.get("name", "").strip()
    department = request.form.get("department", "").strip()
    year = request.form.get("year", "").strip()
    student_phone = request.form.get("student_phone", "").strip()
    parent_phone = request.form.get("parent_phone", "").strip()
    email = request.form.get("email", "").strip()

    if not all((register_no, name, department, year, student_phone, parent_phone, email)):
        return "All student fields are required.", 400

    try:
        study_hours = _parse_float(request.form, "study_hours", "Study hours", 0)
        attendance = _parse_float(request.form, "attendance", "Attendance", 0, 100)
        assignment = _parse_float(request.form, "assignment", "Assignment marks", 0, 100)
        internal = _parse_float(request.form, "internal", "Internal marks", 0, 100)
    except ValueError as exc:
        return str(exc), 400

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM students WHERE id=?", (id,))
        if cursor.fetchone() is None:
            return "Student Not Found", 404

        cursor.execute("SELECT 1 FROM students WHERE register_no=? AND id!=?", (register_no, id))
        if cursor.fetchone() is not None:
            return "Another student already uses this register number.", 409

        cursor.execute("""
        UPDATE students
        SET register_no=?, name=?, department=?, year=?, study_hours=?, attendance=?,
            assignment_marks=?, internal_marks=?, student_phone=?, parent_phone=?, email=?
        WHERE id=?
        """, (
            register_no, name, department, year, study_hours, attendance,
            assignment, internal, student_phone, parent_phone, email, id
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return "Could not update the student record.", 409
    finally:
        conn.close()

    return redirect(url_for("students", message="Student information updated successfully."))


# ---------------- DELETE STUDENT ----------------

@app.route("/delete_student/<int:id>")
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

    return redirect("/students")

@app.route("/add_result")
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


@app.route("/save_result", methods=["POST"])
@roles_required("admin", "teacher")
def save_result():
    register_no = request.form.get("register_no", "").strip()
    subject_code = request.form.get("subject_code", "").strip()

    try:
        semester = int(request.form.get("semester", ""))
    except (TypeError, ValueError):
        return "Semester must be a valid number.", 400

    if not register_no or not subject_code:
        return "Student and subject are required.", 400
    if semester < 1 or semester > 8:
        return "Semester must be between 1 and 8.", 400

    try:
        internal = _parse_float(request.form, "internal_mark", "Internal mark", 0)
        external = _parse_float(request.form, "external_mark", "External mark", 0)
    except ValueError as exc:
        return str(exc), 400

    total = internal + external
    if total > 100:
        return "Internal mark + external mark must not exceed 100.", 400

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM students WHERE register_no=?", (register_no,))
        if cursor.fetchone() is None:
            return "Student Not Found", 404

        cursor.execute(
            "SELECT subject_name, semester, credits FROM subjects WHERE subject_code=?",
            (subject_code,),
        )
        subject = cursor.fetchone()
        if subject is None:
            return "Subject Not Found", 404
        if int(subject[1]) != semester:
            return "Selected subject does not belong to the selected semester.", 400

        cursor.execute("""
        SELECT 1 FROM semester_results
        WHERE register_no=? AND semester=? AND subject_code=?
        """, (register_no, semester, subject_code))
        if cursor.fetchone() is not None:
            return "A result already exists for this student, semester, and subject.", 409

        grade, grade_point, result = calculate_grade(total)
        cursor.execute("""
        INSERT INTO semester_results(
            register_no, semester, subject_code, subject_name, internal_mark,
            external_mark, total_mark, grade, grade_point, credits, result
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (
            register_no, semester, subject_code, subject[0], internal, external,
            total, grade, grade_point, subject[2], result
        ))

        _refresh_arrear_count(conn, register_no)
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        return f"Could not save result: {exc}", 409
    finally:
        conn.close()

    return redirect(url_for("results"))


@app.route("/edit_result/<int:id>")
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

@app.route("/update_result/<int:id>", methods=["POST"])
@roles_required("admin", "teacher")
def update_result(id):
    register_no = request.form.get("register_no", "").strip()
    subject_code = request.form.get("subject_code", "").strip()

    try:
        semester = int(request.form.get("semester", ""))
    except (TypeError, ValueError):
        return "Semester must be a valid number.", 400

    if not register_no or not subject_code:
        return "Student and subject are required.", 400
    if semester < 1 or semester > 8:
        return "Semester must be between 1 and 8.", 400

    try:
        internal = _parse_float(request.form, "internal_mark", "Internal mark", 0)
        external = _parse_float(request.form, "external_mark", "External mark", 0)
    except ValueError as exc:
        return str(exc), 400

    total = internal + external
    if total > 100:
        return "Internal mark + external mark must not exceed 100.", 400

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT register_no FROM semester_results WHERE result_id=?", (id,))
        existing = cursor.fetchone()
        if existing is None:
            return "Result Not Found", 404

        cursor.execute("SELECT 1 FROM students WHERE register_no=?", (register_no,))
        if cursor.fetchone() is None:
            return "Student Not Found", 404

        cursor.execute(
            "SELECT subject_name, semester, credits FROM subjects WHERE subject_code=?",
            (subject_code,),
        )
        subject = cursor.fetchone()
        if subject is None:
            return "Subject Not Found", 404
        if int(subject[1]) != semester:
            return "Selected subject does not belong to the selected semester.", 400

        cursor.execute("""
        SELECT 1 FROM semester_results
        WHERE register_no=? AND semester=? AND subject_code=? AND result_id!=?
        """, (register_no, semester, subject_code, id))
        if cursor.fetchone() is not None:
            return "Another result already exists for this student, semester, and subject.", 409

        grade, grade_point, result = calculate_grade(total)
        cursor.execute("""
        UPDATE semester_results
        SET register_no=?, semester=?, subject_code=?, subject_name=?,
            internal_mark=?, external_mark=?, total_mark=?, grade=?,
            grade_point=?, credits=?, result=?
        WHERE result_id=?
        """, (
            register_no, semester, subject_code, subject[0], internal, external,
            total, grade, grade_point, subject[2], result, id
        ))

        _refresh_arrear_count(conn, existing[0])
        if existing[0] != register_no:
            _refresh_arrear_count(conn, register_no)
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("results"))


@app.route("/delete_result/<int:id>")
@roles_required("admin", "teacher")
def delete_result(id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT register_no FROM semester_results WHERE result_id=?", (id,))
        row = cursor.fetchone()
        if row is None:
            return "Result Not Found", 404

        register_no = row[0]
        cursor.execute("DELETE FROM semester_results WHERE result_id=?", (id,))
        _refresh_arrear_count(conn, register_no)
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("results"))


@app.route("/gpa/<register_no>/<int:semester>")
@roles_required("admin", "teacher", "student")
def gpa(register_no, semester):

    if semester < 1 or semester > 8:
        return "Semester must be between 1 and 8.", 400

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

    total_points = 0
    total_credits = 0

    for r in results:

        total_points += r["grade_point"] * r["credits"]
        total_credits += r["credits"]

    if total_credits == 0:
        gpa = 0
    else:
        gpa = round(total_points / total_credits, 2)

    conn.close()

    return render_template(
        "gpa.html",
        results=results,
        gpa=gpa,
        register_no=register_no,
        semester=semester
    )

# ---------------- PREDICT ----------------

@app.route("/predict/<int:id>")
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

@app.route("/results")
@roles_required("admin", "teacher")
def results():

    conn = get_row_connection()

    cursor = conn.cursor()

    cursor.execute("""
    SELECT * FROM semester_results
    ORDER BY register_no, semester
    """)

    results = cursor.fetchall()

    conn.close()

    return render_template(
        "results.html",
        results=results
    )

@app.route("/exam_registration")
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


@app.route("/save_exam_registration", methods=["POST"])
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
        "Paid" if exam_fee == 0 else "Unpaid",
        datetime.now().strftime("%Y-%m-%d") if exam_fee == 0 else "",
        "Paid" if exam_fee == 0 else "Registered"
    ))

    conn.commit()
    conn.close()

    return redirect(url_for(
        "exam_registration",
        message="Exam registration saved successfully."
    ))

# ---------------- STUDENT DASHBOARD / SUPPORT PAGES ----------------

@app.route("/student_dashboard")
@roles_required("student")
def student_dashboard():
    identity = student_identity()
    if identity is None:
        return "Forbidden", 403

    conn = get_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE id=? AND register_no=?", identity)
        student = cursor.fetchone()
    finally:
        conn.close()

    if student is None:
        return "Student Not Found", 404
    return render_template("student_dashboard.html", student=student)


@app.route("/recommendation/<int:id>")
@roles_required("admin", "teacher", "student")
def recommendation(id):
    conn = get_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE id=?", (id,))
        student = cursor.fetchone()
    finally:
        conn.close()

    if student is None:
        return "Student Not Found", 404

    if session.get("role") == "student":
        identity = student_identity()
        if identity is None or id != identity[0]:
            return "Forbidden", 403

    return render_template("recommendation.html", student=student)


@app.route("/semester_results/<register_no>/<int:semester>")
@roles_required("admin", "teacher", "student")
def semester_results(register_no, semester):
    if semester < 1 or semester > 8:
        return "Semester must be between 1 and 8.", 400

    if session.get("role") == "student":
        identity = student_identity()
        if identity is None or register_no != identity[1]:
            return "Forbidden", 403

    conn = get_row_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE register_no=?", (register_no,))
        student = cursor.fetchone()
        if student is None:
            return "Student Not Found", 404

        cursor.execute("""
        SELECT * FROM semester_results
        WHERE register_no=? AND semester=?
        ORDER BY subject_code
        """, (register_no, semester))
        results = cursor.fetchall()
    finally:
        conn.close()

    total_credits = sum((r["credits"] or 0) for r in results)
    total_points = sum((r["credits"] or 0) * (r["grade_point"] or 0) for r in results)
    gpa_value = round(total_points / total_credits, 2) if total_credits else 0
    return render_template(
        "semester_results.html",
        student=student,
        results=results,
        semester=semester,
        total_credits=total_credits,
        gpa=gpa_value,
    )


@app.route("/payment_history")
@roles_required("admin", "student")
def payment_history():
    conn = get_row_connection()
    try:
        cursor = conn.cursor()
        if session.get("role") == "student":
            identity = student_identity()
            if identity is None:
                return "Forbidden", 403
            cursor.execute("""
            SELECT p.*, er.semester, er.exam_type
            FROM payments p
            LEFT JOIN exam_registration er ON er.registration_id=p.registration_id
            WHERE p.register_no=?
            ORDER BY p.payment_id DESC
            """, (identity[1],))
        else:
            cursor.execute("""
            SELECT p.*, er.semester, er.exam_type
            FROM payments p
            LEFT JOIN exam_registration er ON er.registration_id=p.registration_id
            ORDER BY p.payment_id DESC
            """)
        payments = cursor.fetchall()
    finally:
        conn.close()

    return render_template("history.html", payments=payments)


# ---------------- ACADEMIC SUMMARY ----------------

@app.route("/academic_summary/<register_no>/<int:semester>")
@roles_required("admin", "teacher", "student")
def academic_summary(register_no, semester):

    if semester < 1 or semester > 8:
        return "Semester must be between 1 and 8.", 400

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

    total_credits = 0
    total_points = 0
    pass_count = 0
    fail_count = 0
    total_marks = 0

    for r in results:

        total_credits += r["credits"]
        total_points += r["credits"] * r["grade_point"]
        total_marks += r["total_mark"]

        if r["result"] == "Pass":
            pass_count += 1
        else:
            fail_count += 1

    if total_credits == 0:
        gpa = 0
    else:
        gpa = round(total_points / total_credits, 2)

    if len(results) == 0:
        percentage = 0
    else:
        percentage = round(total_marks / len(results), 2)

    conn.close()

    return render_template(
        "academic_summary.html",
        student=student,
        results=results,
        semester=semester,
        total_credits=total_credits,
        pass_count=pass_count,
        fail_count=fail_count,
        gpa=gpa,
        percentage=percentage
    )

# ---------------- SUBJECTS ----------------

@app.route("/subjects")
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

@app.route("/add_subject")
@roles_required("admin")
def add_subject():

    return render_template("add_subject.html")


# ---------------- SAVE SUBJECT ----------------

@app.route("/save_subject", methods=["POST"])
@roles_required("admin")
def save_subject():
    subject_code = request.form.get("subject_code", "").strip()
    subject_name = request.form.get("subject_name", "").strip()

    if not subject_code or not subject_name:
        return "Subject code and subject name are required.", 400

    try:
        semester = int(request.form.get("semester", ""))
        credits = int(request.form.get("credits", ""))
    except (TypeError, ValueError):
        return "Semester and credits must be valid numbers.", 400

    if not 1 <= semester <= 8:
        return "Semester must be between 1 and 8.", 400
    if credits < 1:
        return "Credits must be at least 1.", 400

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO subjects(subject_code, subject_name, semester, credits) VALUES(?,?,?,?)",
            (subject_code, subject_name, semester, credits),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return "A subject with this code already exists.", 409
    finally:
        conn.close()

    return redirect(url_for("subjects"))


@app.route("/edit_subject/<int:id>")
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

@app.route("/update_subject/<int:id>", methods=["POST"])
@roles_required("admin")
def update_subject(id):
    subject_code = request.form.get("subject_code", "").strip()
    subject_name = request.form.get("subject_name", "").strip()
    if not subject_code or not subject_name:
        return "Subject code and subject name are required.", 400

    try:
        semester = int(request.form.get("semester", ""))
        credits = int(request.form.get("credits", ""))
    except (TypeError, ValueError):
        return "Semester and credits must be valid numbers.", 400

    if not 1 <= semester <= 8:
        return "Semester must be between 1 and 8.", 400
    if credits < 1:
        return "Credits must be at least 1.", 400

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM subjects WHERE subject_id=?", (id,))
        if cursor.fetchone() is None:
            return "Subject Not Found", 404
        cursor.execute("""
        UPDATE subjects SET subject_code=?, subject_name=?, semester=?, credits=?
        WHERE subject_id=?
        """, (subject_code, subject_name, semester, credits, id))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        return "A subject with this code already exists.", 409
    finally:
        conn.close()

    return redirect(url_for("subjects"))


@app.route("/delete_subject/<int:id>")
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

    return redirect("/subjects")

# ---------------- ANALYTICS ----------------

@app.route("/analytics")
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


# ---------------- FEES ----------------

@app.route("/fees")
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


@app.route("/payment/<int:registration_id>")
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
    if balance_due > 0:
        if not UPI_ID:
            return "UPI payment is not configured. Set UPI_ID in the environment.", 503
        upi_link = "upi://pay?" + urlencode({
            "pa": UPI_ID,
            "pn": UPI_PAYEE,
            "am": f"{balance_due:.2f}",
            "cu": "INR",
            "tn": "Exam Fee Payment",
        })

    return render_template(
        "payment.html",
        registration=registration,
        message=request.args.get("message"),
        upi_id=UPI_ID,
        upi_number=UPI_NUMBER,
        payee_name=UPI_PAYEE,
        upi_link=upi_link,
        payment_amount=balance_due
    )


@app.route("/payment/qr/status/<int:registration_id>")
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
    return jsonify({"status": "paid", "payment_id": payment_id})


@app.route("/save_payment/<int:registration_id>", methods=["POST"])
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
    return redirect(url_for("receipt", payment_id=receipt_id))


@app.route("/receipt/<int:payment_id>")
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


# ---------------- TEACHER MANAGEMENT ----------------

@app.route("/teacher_management")
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
@app.route("/forgot_password")
def forgot_password():

    return render_template("forgot_password.html")

# ---------------- CHANGE PASSWORD ----------------

@app.route("/change_password", methods=["POST"])
@login_required
def change_password():

    username = session.get("username")
    old_password = request.form.get("old_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if len(new_password) < 8:
        return "New password must contain at least 8 characters.", 400

    if new_password != confirm_password:
        return "New Password and Confirm Password do not match.", 400

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM login WHERE username=?", (username,))
    user = cursor.fetchone()

    if user is not None:
        stored_password = user["password"]
        try:
            valid_old_password = check_password_hash(stored_password, old_password)
        except (ValueError, TypeError):
            valid_old_password = stored_password == old_password

        if valid_old_password:
            cursor.execute(
                "UPDATE login SET password=? WHERE username=?",
                (generate_password_hash(new_password), username)
            )
            conn.commit()
            conn.close()
            return """
            <h2>Password Changed Successfully ✅</h2>
            <a href="/">Login Again</a>
            """

    conn.close()
    return """
    <h2>Old Password Incorrect ❌</h2>

    <a href="/forgot_password">Try Again</a>
    """
# ---------------- PROFILE ----------------

@app.route("/profile/<int:id>")
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

    conn.close()

    return render_template(
        "profile.html",
        student=student
    )
# ---------------- GENERATE HALL TICKET ----------------

@app.route("/generate_hallticket/<int:id>")
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

    if student["exam_fee"] > 0:
        conn.close()
        return """
        <h2>Hall Ticket Cannot Be Generated</h2>
        <h3>Pending Exam Fee</h3>
        <a href="/students">Go Back</a>
        """

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

    return redirect("/students")

# ---------------- HALL TICKET ----------------

@app.route("/hall_ticket/<int:id>")
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

# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("index"))


# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(debug=DEBUG)
