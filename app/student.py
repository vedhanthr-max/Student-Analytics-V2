from flask import Blueprint

blueprint = Blueprint("student", __name__)
ENDPOINTS = {
    "students",
    "profile",
    "generate_hallticket",
    "hall_ticket",
    "hall_ticket_pdf",
}
