
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("campuspass.db")
LEGACY_DEMO_STUDENT_NUMBERS = ("9000001", "9000002", "9000003", "8000001")


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

        placeholders = ", ".join("?" for _ in LEGACY_DEMO_STUDENT_NUMBERS)
        conn.execute(
            f"DELETE FROM passes WHERE student_number IN ({placeholders})",
            LEGACY_DEMO_STUDENT_NUMBERS
        )
        conn.execute(
            f"DELETE FROM students WHERE student_number IN ({placeholders})",
            LEGACY_DEMO_STUDENT_NUMBERS
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO students
                (student_number, university, student_email)
            VALUES (?, ?, ?)
            """,
            ("3776295", "UNB", "hadi.akbar@unb.ca")
        )


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
