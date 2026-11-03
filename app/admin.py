from flask import Blueprint

blueprint = Blueprint("admin", __name__)
ENDPOINTS = {
    "admin",
    "admin_students",
    "import_students",
    "import_results",
    "admin_teachers",
    "admin_fees_collected",
    "admin_fees_pending",
    "link_student_login",
    "add_student",
    "save_student",
    "edit_student",
    "update_student",
    "delete_student",
    "teacher_management",
}
