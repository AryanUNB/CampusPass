import os
import sqlite3
from contextlib import closing
from pathlib import Path

DB_PATH = Path(__file__).with_name("campuspass.db")
LEGACY_DEMO_STUDENT_NUMBERS = ("9000001", "9000002", "9000003", "8000001")


class DatabaseConnection:
    def __init__(self, connection, postgres=False):
        self.connection = connection
        self.postgres = postgres

    def execute(self, query, parameters=()):
        if self.postgres:
            query = query.replace("?", "%s")
        return self.connection.execute(query, parameters)

    def close(self):
        self.connection.close()

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return self.connection.__exit__(exc_type, exc_value, traceback)


def get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        import psycopg
        from psycopg.rows import dict_row

        connection = psycopg.connect(
            database_url,
            connect_timeout=10,
            row_factory=dict_row
        )
        return DatabaseConnection(connection, postgres=True)

    if os.environ.get("VERCEL"):
        raise RuntimeError("DATABASE_URL must be configured on Vercel")

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return DatabaseConnection(connection)


def initialize_database():
    with closing(get_connection()) as conn:
        with conn:
            request_id_type = (
                "BIGSERIAL PRIMARY KEY"
                if conn.postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
            )
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
                    claimant_email TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0
                )
            """)

            if conn.postgres:
                conn.execute("""
                    ALTER TABLE passes
                    ADD COLUMN IF NOT EXISTS verified INTEGER NOT NULL DEFAULT 0
                """)
            else:
                pass_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(passes)")
                }
                if "verified" not in pass_columns:
                    conn.execute("""
                        ALTER TABLE passes
                        ADD COLUMN verified INTEGER NOT NULL DEFAULT 0
                    """)

            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS failed_attempts (
                    id {request_id_type},
                    client_ip TEXT NOT NULL,
                    attempted_at DOUBLE PRECISION NOT NULL
                )
            """)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS otp_requests (
                    id {request_id_type},
                    client_ip TEXT NOT NULL,
                    student_number TEXT NOT NULL,
                    requested_at DOUBLE PRECISION NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS otp_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    student_number TEXT NOT NULL,
                    email TEXT NOT NULL,
                    university TEXT NOT NULL,
                    otp_hash TEXT NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0
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
                INSERT INTO students (student_number, university, student_email)
                VALUES (?, ?, ?)
                ON CONFLICT(student_number) DO NOTHING
                """,
                ("3776295", "UNB", "hadi.akbar@unb.ca")
            )


def insert_otp_request(conn, client_ip, student_number, requested_at):
    parameters = (client_ip, student_number, requested_at)
    if conn.postgres:
        cursor = conn.execute(
            """
            INSERT INTO otp_requests (client_ip, student_number, requested_at)
            VALUES (?, ?, ?)
            RETURNING id
            """,
            parameters
        )
        return cursor.fetchone()["id"]

    cursor = conn.execute(
        """
        INSERT INTO otp_requests (client_ip, student_number, requested_at)
        VALUES (?, ?, ?)
        """,
        parameters
    )
    return cursor.lastrowid
