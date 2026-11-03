"""Application configuration."""

import os
import secrets
import logging

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "database", "student.db")

DATABASE = os.environ.get("STUDENT_DB_PATH") or DEFAULT_DB_PATH
MODEL_PATH = os.path.join(BASE_DIR, "models", "kmeans_model.pkl")
SCALER_PATH = os.path.join(BASE_DIR, "models", "scaler.pkl")

SECRET_KEY = os.environ.get("SECRET_KEY")
DEBUG = os.environ.get("FLASK_DEBUG") == "1"

UPI_ID = os.environ.get("UPI_ID", "")
UPI_NUMBER = os.environ.get("UPI_NUMBER", "")
UPI_PAYEE_NAME = os.environ.get("UPI_PAYEE_NAME", "")


def get_secret_key(debug=None):
    """Return the configured key or generate one for development."""
    if debug is None:
        debug = os.environ.get("FLASK_DEBUG") == "1"
    secret_key = os.environ.get("SECRET_KEY")
    if secret_key:
        return secret_key
    if debug:
        logging.getLogger("student_analytics").warning(
            "SECRET_KEY is empty; sessions reset on restart."
        )
        return secrets.token_hex(32)
    raise RuntimeError("SECRET_KEY must be set in production.")
