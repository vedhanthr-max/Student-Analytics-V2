from flask import Blueprint

blueprint = Blueprint("teacher", __name__)
ENDPOINTS = {
    "teacher",
    "add_result",
    "save_result",
    "edit_result",
    "update_result",
    "delete_result",
    "gpa",
    "predict",
    "results",
    "exam_registration",
    "save_exam_registration",
    "academic_summary",
    "subjects",
    "add_subject",
    "save_subject",
    "edit_subject",
    "update_subject",
    "delete_subject",
}
