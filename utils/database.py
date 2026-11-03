"""Database connection helpers."""

import sqlite3

from config import DATABASE


def get_connection():
    """Return a SQLite connection to the application database."""
    return sqlite3.connect(DATABASE)


def get_row_connection():
    """Return a SQLite connection with Row factory for dict-like access."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    return conn
