
import time
from contextlib import closing

from flask import Flask, render_template, render_template_string, request
from werkzeug.security import check_password_hash

from database import initialize_database, get_connection

app = Flask(__name__)

# Initialize fictional student and account records.
initialize_database()

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 600

# Upgrade the existing database without deleting our earlier test data.
with closing(get_connection()) as conn:
    columns = [
        row["name"]
        for row in conn.execute("PRAGMA table_info(passes)")
    ]

    if "verified" not in columns:
        conn.execute("""
            ALTER TABLE passes
            ADD COLUMN verified INTEGER NOT NULL DEFAULT 0
        """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS failed_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_ip TEXT NOT NULL,
            attempted_at REAL NOT NULL
        )
    """)

    conn.commit()


def show_result(title, message, status=200):
    return render_template_string("""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>CampusPass | Security Result</title>
            <style>
                body {
                    margin: 0;
                    min-height: 100vh;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    font-family: Arial, sans-serif;
                    background: linear-gradient(
                        135deg, #102b52, #2466a3
                    );
                }

                .card {
                    background: white;
                    padding: 40px;
                    border-radius: 16px;
                    text-align: center;
                    width: 420px;
                    max-width: 85%;
                    box-shadow: 0 12px 35px #0003;
                }

                h2 {
                    color: #173f74;
                }

                p {
                    color: #555;
                    line-height: 1.6;
                }

                a {
                    display: inline-block;
                    margin-top: 20px;
                    padding: 12px 24px;
                    background: #1764ad;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                }

                a:hover {
                    background: #104d87;
                }
            </style>
        </head>
        <body>
            <main class="card">
                <h2>{{ title }}</h2>
                <p>{{ message }}</p>
                <a href="/">Return to CampusPass</a>
            </main>
        </body>
        </html>
    """, title=title, message=message), status


def record_failure(conn, client_ip):
    conn.execute(
        """
        INSERT INTO failed_attempts (client_ip, attempted_at)
        VALUES (?, ?)
        """,
        (client_ip, time.time())
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/claim", methods=["POST"])
def claim_pass():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    university = request.form.get("university", "")
    student_number = request.form.get(
        "student_number", ""
    ).strip()

    client_ip = request.remote_addr or "unknown"
    current_time = time.time()

    generic_error = (
        "Unable to verify your request. "
        "Check your account credentials and student information."
    )

    with closing(get_connection()) as conn:
        with conn:

            # Remove expired failed-attempt records.
            conn.execute(
                """
                DELETE FROM failed_attempts
                WHERE attempted_at < ?
                """,
                (current_time - LOCKOUT_SECONDS,)
            )

            # Rate limiting: maximum five failed attempts
            # per client IP within ten minutes.
            failures = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM failed_attempts
                WHERE client_ip = ?
                """,
                (client_ip,)
            ).fetchone()["total"]

            if failures >= MAX_FAILED_ATTEMPTS:
                return show_result(
                    "Temporarily Blocked",
                    "Too many failed attempts. "
                    "Please try again after ten minutes.",
                    429
                )

            # Validate submitted form fields.
            if (
                not email
                or not password
                or university not in ("UNB", "STU")
                or not student_number.isdigit()
                or len(student_number) != 7
                or len(email) > 254
                or len(password) > 256
            ):
                record_failure(conn, client_ip)

                return show_result(
                    "Verification Failed",
                    generic_error,
                    403
                )

            # Verify the fictional account password.
            account = conn.execute(
                """
                SELECT email, password_hash, student_number
                FROM accounts
                WHERE email = ?
                """,
                (email,)
            ).fetchone()

            if (
                account is None
                or not check_password_hash(
                    account["password_hash"], password
                )
            ):
                record_failure(conn, client_ip)

                return show_result(
                    "Verification Failed",
                    generic_error,
                    403
                )

            # Authorization: the authenticated account
            # must belong to the requested student.
            student = conn.execute(
                """
                SELECT student_number
                FROM students
                WHERE student_number = ?
                  AND university = ?
                  AND student_email = ?
                """,
                (student_number, university, email)
            ).fetchone()

            if (
                student is None
                or account["student_number"] != student_number
            ):
                record_failure(conn, client_ip)

                return show_result(
                    "Verification Failed",
                    generic_error,
                    403
                )

            # Check whether the pass already exists.
            existing_pass = conn.execute(
                """
                SELECT claimant_email, verified
                FROM passes
                WHERE student_number = ?
                """,
                (student_number,)
            ).fetchone()

            if existing_pass:

                if existing_pass["verified"] == 1:

                    if existing_pass["claimant_email"] == email:
                        return show_result(
                            "Pass Already Active",
                            "Your verified bus pass "
                            "is already active."
                        )

                    return show_result(
                        "Verification Failed",
                        generic_error,
                        409
                    )

                # Recover a legacy unverified pass.
                # Only the authenticated rightful student
                # can replace a vulnerable claim.
                conn.execute(
                    """
                    UPDATE passes
                    SET claimant_email = ?,
                        verified = 1
                    WHERE student_number = ?
                      AND verified = 0
                    """,
                    (email, student_number)
                )

            else:
                # Create a new verified student bus pass.
                conn.execute(
                    """
                    INSERT INTO passes
                    (student_number, claimant_email, verified)
                    VALUES (?, ?, 1)
                    """,
                    (student_number, email)
                )

    return show_result(
        "Bus Pass Verified Successfully!",
        "Your identity has been verified and "
        "your student bus pass is now active."
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )
