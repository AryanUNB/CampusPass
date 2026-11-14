
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash

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

        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                student_number TEXT UNIQUE
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

        demo_accounts = [
            ("alice@example.test", "AliceDemo2026!", "9000001"),
            ("bob@example.test", "BobDemo2026!", "9000002"),
            ("charlie@example.test", "CharlieDemo2026!", "9000003"),
            ("david@example.test", "DavidDemo2026!", "8000001"),
            ("attacker@example.test", "AttackerDemo2026!", None)
        ]

        for email, password, student_number in demo_accounts:
            conn.execute(
                """
                INSERT OR IGNORE INTO accounts
                (email, password_hash, student_number)
                VALUES (?, ?, ?)
                """,
                (
                    email,
                    generate_password_hash(password),
                    student_number
                )
            )


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
