
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("campuspass.db")


def initialize_database():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS students (
                student_number TEXT PRIMARY KEY,
                university TEXT NOT NULL,
                student_email TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS passes (
                student_number TEXT PRIMARY KEY,
                claimant_email TEXT NOT NULL
            )
        """)

        students = [
            ("9000001", "UNB", "alice@example.test"),
            ("9000002", "UNB", "bob@example.test"),
            ("9000003", "UNB", "charlie@example.test"),
            ("8000001", "STU", "david@example.test")
        ]

        conn.executemany(
            "INSERT OR IGNORE INTO students VALUES (?, ?, ?)",
            students
        )


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

