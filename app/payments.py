from flask import Blueprint

blueprint = Blueprint("payments", __name__)
ENDPOINTS = {
    "fees",
    "confirm_upi",
    "payment",
    "payment_qr_status",
    "save_payment",
    "receipt",
    "receipt_pdf",
}
