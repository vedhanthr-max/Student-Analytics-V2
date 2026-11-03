from flask import Blueprint

blueprint = Blueprint("auth", __name__)
ENDPOINTS = {
    "index",
    "admin_login",
    "teacher_login",
    "student_login",
    "login",
    "forgot_password",
    "change_password",
    "logout",
}
