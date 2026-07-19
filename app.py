from flask import Flask, render_template, request, redirect, url_for, session
print("APP LOADED SUCCESSFULLY 🚀")
import sqlite3
import joblib
import pandas as pd

app = Flask(__name__)
model = joblib.load("models/kmeans_model.pkl")
scaler = joblib.load("models/scaler.pkl")
app.secret_key = "studentanalytics"


# ---------------- HOME ----------------

@app.route("/")
def index():
    return render_template("login.html")


# ---------------- LOGIN ----------------

@app.route("/login", methods=["POST"])
def login():

    username = request.form["username"]
    password = request.form["password"]
    role = request.form["role"]

    conn = sqlite3.connect("database/student.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM login WHERE username=? AND password=? AND role=?",
        (username, password, role)
    )

    user = cursor.fetchone()
    conn.close()

    if user:

        session["username"] = username
        session["role"] = role

        if role == "admin":
            return redirect(url_for("admin"))

        elif role == "teacher":
            return redirect(url_for("teacher"))

        else:
            return redirect(url_for("student"))

    return "Invalid Login"


# ---------------- ADMIN ----------------

@app.route("/admin")
def admin():
    return render_template("admin_dashboard.html")


# ---------------- TEACHER ----------------

@app.route("/teacher")
def teacher():
    return render_template("teacher_dashboard.html")


# ---------------- STUDENT ----------------

@app.route("/students")
def students():

    search = request.args.get("search", "")

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row

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
def add_student():
    return render_template("add_student.html")


# ---------------- SAVE STUDENT ----------------

@app.route("/save_student", methods=["POST"])
def save_student():

    conn = sqlite3.connect("database/student.db")

    cursor = conn.cursor()

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

    conn.commit()

    conn.close()

    return redirect("/students")


# ---------------- EDIT STUDENT ----------------

@app.route("/edit_student/<int:id>")
def edit_student(id):

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("SELECT * FROM students WHERE id=?", (id,))
    student = cursor.fetchone()

    conn.close()

    return render_template("edit_student.html", student=student)

# ---------------- UPDATE STUDENT ----------------

@app.route("/update_student/<int:id>", methods=["POST"])
def update_student(id):

    conn = sqlite3.connect("database/student.db")
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
    email=?,
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

    return redirect("/students")

# ---------------- DELETE STUDENT ----------------

@app.route("/delete_student/<int:id>")
def delete_student(id):

    conn = sqlite3.connect("database/student.db")
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM students WHERE id=?",
        (id,)
    )

    conn.commit()
    conn.close()

    return redirect("/students")

@app.route("/add_result")
def add_result():

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row

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
def save_result():

    register_no = request.form["register_no"]
    semester = request.form["semester"]
    subject_code = request.form["subject_code"]
    conn = sqlite3.connect("database/student.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT subject_name
        FROM subjects
        WHERE subject_code=?
        """,
        (subject_code,)
    )

    row = cursor.fetchone()

    subject_name = row[0]

    conn.close()

    internal = float(request.form["internal_mark"])
    external = float(request.form["external_mark"])

    total = internal + external

    # Grade Calculation

    if total >= 90:
        grade = "O"
        grade_point = 10
        result = "Pass"

    elif total >= 80:
        grade = "A+"
        grade_point = 9
        result = "Pass"

    elif total >= 70:
        grade = "A"
        grade_point = 8
        result = "Pass"

    elif total >= 60:
        grade = "B+"
        grade_point = 7
        result = "Pass"

    elif total >= 50:
        grade = "B"
        grade_point = 6
        result = "Pass"

    elif total >= 45:
        grade = "C"
        grade_point = 5
        result = "Pass"

    else:
        grade = "RA"
        grade_point = 0
        result = "Fail"

    conn = sqlite3.connect("database/student.db")

    cursor = conn.cursor()

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
    result

    )

    VALUES(?,?,?,?,?,?,?,?,?,?)

    """,(

    register_no,
    semester,
    subject_code,
    subject_name,
    internal,
    external,
    total,
    grade,
    result

    ))

    conn.commit()

    conn.close()

    return redirect("/results")

@app.route("/edit_result/<int:id>")
def edit_result(id):

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM semester_results WHERE result_id=?",
        (id,)
    )

    result = cursor.fetchone()

    conn.close()

    return render_template(
        "edit_result.html",
        result=result
    )

@app.route("/update_result/<int:id>", methods=["POST"])
def update_result(id):

    register_no = request.form["register_no"]
    semester = request.form["semester"]
    subject_code = request.form["subject_code"]
    subject_name = request.form["subject_name"]

    internal = float(request.form["internal_mark"])
    external = float(request.form["external_mark"])

    total = internal + external

    if total >= 90:
        grade = "O"
        result = "Pass"
    elif total >= 80:
        grade = "A+"
        result = "Pass"
    elif total >= 70:
        grade = "A"
        result = "Pass"
    elif total >= 60:
        grade = "B+"
        result = "Pass"
    elif total >= 50:
        grade = "B"
        result = "Pass"
    elif total >= 45:
        grade = "C"
        result = "Pass"
    else:
        grade = "RA"
        result = "Fail"

    conn = sqlite3.connect("database/student.db")
    cursor = conn.cursor()

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
        result,
        id

    ))

    conn.commit()
    conn.close()

    return redirect("/results")

@app.route("/delete_result/<int:id>")
def delete_result(id):

    conn = sqlite3.connect("database/student.db")

    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM semester_results WHERE result_id=?",
        (id,)
    )

    conn.commit()
    conn.close()

    return redirect("/results")

@app.route("/gpa/<register_no>/<int:semester>")
def gpa(register_no, semester):

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row

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
def predict(id):

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM students WHERE id=?", (id,))
    student = cursor.fetchone()

    if student is None:
        conn.close()
        return "Student Not Found"

    data = [[
        student["study_hours"],
        student["attendance"],
        student["assignment_marks"],
        student["internal_marks"]
    ]]

    scaled_data = scaler.transform(data)

    cluster = int(model.predict(scaled_data)[0])

    if cluster == 0:
        level = "Excellent"
        recommendation = "Keep up the great work."

    elif cluster == 1:
        level = "Good"
        recommendation = "Practice consistently."

    elif cluster == 2:
        level = "Average"
        recommendation = "Increase study hours and attendance."

    else:
        level = "Need Improvement"
        recommendation = "Meet your mentor and improve your study plan."
    
    
    cursor.execute("""
    UPDATE students
    SET cluster=?, recommendation=?
    WHERE id=?
    """, (level, recommendation, id))

    conn.commit()
    conn.close()

    return redirect("/students")

@app.route("/results")
def results():

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row

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

# ---------------- ACADEMIC SUMMARY ----------------

@app.route("/academic_summary/<register_no>/<int:semester>")
def academic_summary(register_no, semester):

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    # Student Details
    cursor.execute("""
    SELECT *
    FROM students
    WHERE register_no=?
    """, (register_no,))

    student = cursor.fetchone()

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

    for r in results:

        total_credits += r["credits"]
        total_points += r["credits"] * r["grade_point"]

        if r["result"] == "Pass":
            pass_count += 1
        else:
            fail_count += 1

    if total_credits == 0:
        gpa = 0
    else:
        gpa = round(total_points / total_credits, 2)

    conn.close()

    return render_template(
        "academic_summary.html",
        student=student,
        results=results,
        semester=semester,
        total_credits=total_credits,
        pass_count=pass_count,
        fail_count=fail_count,
        gpa=gpa
    )

# ---------------- SUBJECTS ----------------

@app.route("/subjects")
def subjects():

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row

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
def add_subject():

    return render_template("add_subject.html")


# ---------------- SAVE SUBJECT ----------------

@app.route("/save_subject", methods=["POST"])
def save_subject():

    conn = sqlite3.connect("database/student.db")

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

    return redirect("/subjects")

@app.route("/edit_subject/<int:id>")
def edit_subject(id):

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM subjects WHERE subject_id=?",
        (id,)
    )

    subject = cursor.fetchone()

    conn.close()

    return render_template(
        "edit_subject.html",
        subject=subject
    )

@app.route("/update_subject/<int:id>", methods=["POST"])
def update_subject(id):

    conn = sqlite3.connect("database/student.db")

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

    return redirect("/subjects")

@app.route("/delete_subject/<int:id>")
def delete_subject(id):

    conn = sqlite3.connect("database/student.db")

    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM subjects WHERE subject_id=?",
        (id,)
    )

    conn.commit()

    conn.close()

    return redirect("/subjects")

# ---------------- ANALYTICS ----------------

@app.route("/analytics")
def analytics():

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Total Students
    cursor.execute("SELECT COUNT(*) FROM students")
    total_students = cursor.fetchone()[0]

    # Performance Counts
    cursor.execute("SELECT COUNT(*) FROM students WHERE cluster='Excellent'")
    excellent = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM students WHERE cluster='Good'")
    good = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM students WHERE cluster='Average'")
    average = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM students WHERE cluster='Need Improvement'")
    weak = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "analytics.html",
        total_students=total_students,
        excellent=excellent,
        good=good,
        average=average,
        weak=weak
    )


# ---------------- FEES ----------------

@app.route("/fees")
def fees():
    return "<h1>Fees Management Page</h1>"


# ---------------- TEACHER MANAGEMENT ----------------

@app.route("/teacher_management")
def teacher_management():
    return "<h1>Teacher Management Page</h1>"

# ---------------- FORGOT PASSWORD ----------------
@app.route("/forgot_password")
def forgot_password():

    return render_template("forgot_password.html")

# ---------------- CHANGE PASSWORD ----------------

@app.route("/change_password", methods=["POST"])
def change_password():

    username = request.form["username"]
    old_password = request.form["old_password"]
    new_password = request.form["new_password"]
    confirm_password = request.form["confirm_password"]

    if new_password != confirm_password:
        return "New Password and Confirm Password do not match."

    conn = sqlite3.connect("database/student.db")
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM login WHERE username=? AND password=?",
        (username, old_password)
    )

    user = cursor.fetchone()

    if user:

        cursor.execute(
            "UPDATE login SET password=? WHERE username=?",
            (new_password, username)
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
def profile(id):

    conn = sqlite3.connect("database/student.db")
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM students WHERE id=?",
        (id,)
    )

    student = cursor.fetchone()

    conn.close()

    return render_template(
        "profile.html",
        student=student
    )

# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("index"))


# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(debug=True)