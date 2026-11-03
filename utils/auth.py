"""Authentication helpers and route protection."""

from functools import wraps

from flask import redirect, session, url_for


def login_required(f):
    """Redirect unauthenticated users to the login page."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function


def roles_required(*allowed_roles):
    """Allow access only to logged-in users with one of the given roles."""

    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            role = session.get("role")
            if role not in allowed_roles:
                return "Forbidden", 403
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def student_identity():
    """Return the linked student identity for a logged-in student, if any."""

    if session.get("role") != "student":
        return None

    student_id = session.get("student_id")
    student_register_no = session.get("student_register_no")

    if student_id is None or not student_register_no:
        return None

    return student_id, student_register_no
