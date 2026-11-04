"""Database connection helpers."""

import sqlite3

import config


def get_connection(timeout=30):
    """Return a SQLite connection to the application database."""
    conn = sqlite3.connect(config.DATABASE, timeout=timeout)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get_row_connection(timeout=30):
    """Return a SQLite connection with Row factory for dict-like access."""
    conn = get_connection(timeout=timeout)
    conn.row_factory = sqlite3.Row
    return conn
