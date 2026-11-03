"""Application configuration."""

import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE = os.environ.get(
    "STUDENT_DB_PATH",
    os.path.join(BASE_DIR, "database", "student.db"),
)
MODEL_PATH = os.path.join(BASE_DIR, "models", "kmeans_model.pkl")
SCALER_PATH = os.path.join(BASE_DIR, "models", "scaler.pkl")

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("FLASK_DEBUG") == "1"

UPI_ID = os.environ.get("UPI_ID", "")
UPI_NUMBER = os.environ.get("UPI_NUMBER", "")
UPI_PAYEE_NAME = os.environ.get("UPI_PAYEE_NAME", "")
