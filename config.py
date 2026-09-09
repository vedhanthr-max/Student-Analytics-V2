"""Application configuration loaded from environment variables."""

import os
import secrets

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE = os.getenv("DATABASE_PATH", "database/student.db")
MODEL_PATH = os.getenv("MODEL_PATH", "models/kmeans_model.pkl")
SCALER_PATH = os.getenv("SCALER_PATH", "models/scaler.pkl")

# Never commit a real secret key. Set SECRET_KEY in your environment for a stable key.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
DEBUG = os.getenv("FLASK_DEBUG", "0").lower() in {"1", "true", "yes", "on"}

# Temporary direct UPI configuration. Keep real payment details outside Git.
UPI_ID = os.getenv("UPI_ID", "")
UPI_NUMBER = os.getenv("UPI_NUMBER", "")
UPI_PAYEE = os.getenv("UPI_PAYEE", "")
