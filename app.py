import hashlib
import hmac
import os
import secrets
import smtplib
import time
from contextlib import closing
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for

from database import get_connection, initialize_database, insert_otp_request

if not os.environ.get("VERCEL"):
    load_dotenv()

configured_secret_key = os.environ.get("CAMPUSPASS_SECRET_KEY")
if os.environ.get("VERCEL") and not configured_secret_key:
    raise RuntimeError("CAMPUSPASS_SECRET_KEY must be configured on Vercel")

app = Flask(__name__)
app.secret_key = configured_secret_key or secrets.token_hex(32)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=10)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("VERCEL"))

initialize_database()
OTP_LIFETIME_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
MAX_FAILED_ATTEMPTS = 5
MAX_OTP_REQUESTS = 20
LOCKOUT_SECONDS = 600
UNB_CODE = "UNB"
UNB_EMAIL_DOMAIN = "@unb.ca"


def csrf_token():
    token = session.get("csrf_token")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def csrf_is_valid():
    submitted = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    return bool(expected) and hmac.compare_digest(submitted, expected)


def otp_digest(challenge_id, code):
    key = app.secret_key.encode("utf-8")
    message = f"{challenge_id}:{code}".encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def smtp_settings():
    host = os.environ.get("CAMPUSPASS_SMTP_HOST")
    sender = os.environ.get("CAMPUSPASS_SMTP_FROM")
    username = os.environ.get("CAMPUSPASS_SMTP_USERNAME")
    password = os.environ.get("CAMPUSPASS_SMTP_PASSWORD")
    if not host or not sender:
        raise ValueError(
            "CAMPUSPASS_SMTP_HOST and CAMPUSPASS_SMTP_FROM must be configured"
        )
    sender_email = parseaddr(sender)[1]
    sender_local, separator, sender_domain = sender_email.rpartition("@")
    sender_domain = sender_domain.lower()
    if (
        not separator
        or not sender_local
        or not sender_domain
        or any(character.isspace() for character in sender_local)
        or any(character.isspace() for character in sender_domain)
        or sender_domain in {"example.com", "example.net", "example.org"}
        or sender_domain.endswith(".test")
    ):
        raise ValueError(
            "CAMPUSPASS_SMTP_FROM must be a real sender address verified "
            "with the SMTP provider"
        )
    if bool(username) != bool(password):
        raise ValueError(
            "CAMPUSPASS_SMTP_USERNAME and CAMPUSPASS_SMTP_PASSWORD "
            "must be configured together"
        )
    return host, int(os.environ.get("CAMPUSPASS_SMTP_PORT", "587")), sender, username, password


def send_otp_email(recipient, code):
    host, port, sender, username, password = smtp_settings()
    message = EmailMessage()
    message["Subject"] = "Your CampusPass verification code"
    sender_name, sender_email = parseaddr(sender)
    message["From"] = formataddr((sender_name, sender_email))
    message["To"] = recipient
    message.set_content(
        f"Your CampusPass verification code is {code}.\n\n"
        f"It expires in {OTP_LIFETIME_SECONDS // 60} minutes. "
        "If you did not request this code, you can ignore this email."
    )

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=10) as smtp:
            if username:
                smtp.login(username, password)
            refused = smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls()
            if username:
                smtp.login(username, password)
            refused = smtp.send_message(message)
    if refused:
        raise smtplib.SMTPRecipientsRefused(refused)


def record_failure(conn, client_ip, current_time):
    conn.execute(
        """
        INSERT INTO failed_attempts (client_ip, attempted_at)
        VALUES (?, ?)
        """,
        (client_ip, current_time)
    )


def failure_count(conn, client_ip, current_time):
    conn.execute(
        "DELETE FROM failed_attempts WHERE attempted_at < ?",
        (current_time - LOCKOUT_SECONDS,)
    )
    return conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM failed_attempts
        WHERE client_ip = ?
        """,
        (client_ip,)
    ).fetchone()["total"]


def render_home(message=None, message_type="info"):
    verified_until = session.get("verified_until", 0)
    student_number = session.get("verified_student_number")
    if not student_number or verified_until <= time.time():
        session.pop("verified_student_number", None)
        session.pop("verified_until", None)
        student_number = None

    pass_active = False
    if student_number:
        with closing(get_connection()) as conn:
            existing_pass = conn.execute(
                """
                SELECT verified
                FROM passes
                WHERE student_number = ?
                """,
                (student_number,)
            ).fetchone()
        pass_active = bool(existing_pass and existing_pass["verified"] == 1)

    return render_template(
        "index.html",
        csrf_token=csrf_token(),
        message=message,
        message_type=message_type,
        otp_pending=bool(session.get("challenge_id")),
        verified_student_number=student_number,
        pass_active=pass_active,
        flashes=flash_messages()
    )


def flash_messages():
    from flask import get_flashed_messages

    return get_flashed_messages(with_categories=True)


@app.route("/")
def home():
    return render_home()


def has_admin_access():
    return bool(
        session.get("admin_authenticated")
        and session.get("admin_expires", 0) > time.time()
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if has_admin_access():
        return redirect(url_for("admin_dashboard"))

    if request.method == "GET":
        return render_template(
            "admin_login.html",
            csrf_token=csrf_token(),
            message=None
        )

    if not csrf_is_valid():
        return render_template(
            "admin_login.html",
            csrf_token=csrf_token(),
            message="Please reload the page and try again."
        ), 400

    client_ip = request.remote_addr or "unknown"
    current_time = time.time()
    with closing(get_connection()) as conn:
        with conn:
            if failure_count(conn, client_ip, current_time) >= MAX_FAILED_ATTEMPTS:
                return render_template(
                    "admin_login.html",
                    csrf_token=csrf_token(),
                    message="Too many attempts. Please try again after ten minutes."
                ), 429

    configured_email = os.environ.get("CAMPUSPASS_ADMIN_EMAIL", "").strip().lower()
    configured_password = os.environ.get("CAMPUSPASS_ADMIN_PASSWORD", "")
    submitted_email = request.form.get("email", "").strip().lower()
    submitted_password = request.form.get("password", "")
    valid_email = bool(configured_email) and hmac.compare_digest(
        submitted_email.encode("utf-8"),
        configured_email.encode("utf-8")
    )
    valid_password = bool(configured_password) and hmac.compare_digest(
        submitted_password.encode("utf-8"),
        configured_password.encode("utf-8")
    )

    if not configured_email or not configured_password:
        app.logger.error("Admin login credentials are not configured")
        return render_template(
            "admin_login.html",
            csrf_token=csrf_token(),
            message="Admin login is not configured."
        ), 503

    if not valid_email or not valid_password:
        with closing(get_connection()) as conn:
            with conn:
                record_failure(conn, client_ip, current_time)
        return render_template(
            "admin_login.html",
            csrf_token=csrf_token(),
            message="Email or password is incorrect."
        ), 401

    session.clear()
    session.permanent = True
    session["admin_authenticated"] = True
    session["admin_expires"] = current_time + app.config[
        "PERMANENT_SESSION_LIFETIME"
    ].total_seconds()
    flash("Signed in to administration.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin")
def admin_dashboard():
    if not has_admin_access():
        flash("Sign in to access the admin dashboard.", "error")
        return redirect(url_for("admin_login"))

    with closing(get_connection()) as conn:
        students = conn.execute(
            """
            SELECT s.student_number, s.student_email,
                   CASE WHEN p.verified = 1 THEN 1 ELSE 0 END AS pass_active
            FROM students AS s
            LEFT JOIN passes AS p
              ON p.student_number = s.student_number
            WHERE s.university = ?
            ORDER BY s.student_number
            """,
            (UNB_CODE,)
        ).fetchall()
    return render_template(
        "admin.html",
        csrf_token=csrf_token(),
        students=students,
        flashes=flash_messages()
    )


@app.route("/admin/students", methods=["POST"])
def admin_add_student():
    if not csrf_is_valid():
        return render_template(
            "admin_login.html",
            csrf_token=csrf_token(),
            message="Please reload the page and try again."
        ), 400
    if not has_admin_access():
        return redirect(url_for("admin_login"))

    email = request.form.get("student_email", "").strip().lower()
    student_number = request.form.get("student_number", "").strip()
    if (
        len(email) > 254
        or not email.endswith(UNB_EMAIL_DOMAIN)
        or not student_number.isdigit()
        or len(student_number) != 7
    ):
        flash("Enter a valid UNB email and seven-digit student ID.", "error")
        return redirect(url_for("admin_dashboard"))

    with closing(get_connection()) as conn:
        with conn:
            existing = conn.execute(
                """
                SELECT 1
                FROM students
                WHERE student_number = ? OR student_email = ?
                """,
                (student_number, email)
            ).fetchone()
            if existing is not None:
                flash("That student ID or email is already in the database.", "error")
                return redirect(url_for("admin_dashboard"))
            conn.execute(
                """
                INSERT INTO students (student_number, university, student_email)
                VALUES (?, ?, ?)
                """,
                (student_number, UNB_CODE, email)
            )

    flash("Student added successfully.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reset-claims", methods=["POST"])
def admin_reset_claims():
    if not csrf_is_valid():
        return render_template(
            "admin_login.html",
            csrf_token=csrf_token(),
            message="Please reload the page and try again."
        ), 400
    if not has_admin_access():
        return redirect(url_for("admin_login"))

    with closing(get_connection()) as conn:
        with conn:
            result = conn.execute(
                "UPDATE passes SET verified = 0 WHERE verified = 1"
            )
    flash(f"Reset claim status for {result.rowcount} bus pass(es).", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/students/<student_number>/reset-claim", methods=["POST"])
def admin_reset_student_claim(student_number):
    if not csrf_is_valid():
        return redirect(url_for("admin_login"))
    if not has_admin_access():
        return redirect(url_for("admin_login"))

    with closing(get_connection()) as conn:
        with conn:
            student = conn.execute(
                """
                SELECT 1
                FROM students
                WHERE student_number = ? AND university = ?
                """,
                (student_number, UNB_CODE)
            ).fetchone()
            if student is None:
                flash("Student record was not found.", "error")
                return redirect(url_for("admin_dashboard"))

            result = conn.execute(
                """
                UPDATE passes
                SET verified = 0
                WHERE student_number = ? AND verified = 1
                """,
                (student_number,)
            )

    if result.rowcount:
        flash(f"Reset bus-pass claim for student {student_number}.", "success")
    else:
        flash(f"Student {student_number} has no active claim to reset.", "info")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/students/<student_number>/delete", methods=["POST"])
def admin_delete_student(student_number):
    if not csrf_is_valid():
        return redirect(url_for("admin_login"))
    if not has_admin_access():
        return redirect(url_for("admin_login"))

    with closing(get_connection()) as conn:
        with conn:
            student = conn.execute(
                """
                SELECT 1
                FROM students
                WHERE student_number = ? AND university = ?
                """,
                (student_number, UNB_CODE)
            ).fetchone()
            if student is None:
                flash("Student record was not found.", "error")
                return redirect(url_for("admin_dashboard"))

            conn.execute(
                "DELETE FROM passes WHERE student_number = ?",
                (student_number,)
            )
            conn.execute(
                "DELETE FROM otp_challenges WHERE student_number = ?",
                (student_number,)
            )
            conn.execute(
                """
                DELETE FROM students
                WHERE student_number = ? AND university = ?
                """,
                (student_number, UNB_CODE)
            )

    flash(f"Deleted student {student_number} and associated claim data.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    if not csrf_is_valid():
        return redirect(url_for("admin_login"))
    session.clear()
    flash("Signed out of administration.", "info")
    return redirect(url_for("home"))


@app.route("/request-otp", methods=["POST"])
def request_otp():
    if not csrf_is_valid():
        return render_home("Please reload the page and try again.", "error"), 400

    session.pop("challenge_id", None)
    email = request.form.get("email", "").strip().lower()
    student_number = request.form.get("student_number", "").strip()
    client_ip = request.remote_addr or "unknown"
    current_time = time.time()

    try:
        smtp_settings()
    except (ValueError, TypeError):
        app.logger.exception("CampusPass SMTP configuration is invalid")
        return render_home(
            "Email verification is not configured. Please contact the administrator.",
            "error"
        ), 503

    with closing(get_connection()) as conn:
        with conn:
            if failure_count(conn, client_ip, current_time) >= MAX_FAILED_ATTEMPTS:
                return render_home(
                    "Too many attempts. Please try again after ten minutes.",
                    "error"
                ), 429

            if (
                not email
                or len(email) > 254
                or not email.endswith(UNB_EMAIL_DOMAIN)
                or not student_number.isdigit()
                or len(student_number) != 7
            ):
                record_failure(conn, client_ip, current_time)
                return render_home(
                    "This student ID and email combination was not found in "
                    "our database. Please contact the university for assistance.",
                    "error"
                )

            student = conn.execute(
                """
                SELECT student_email
                FROM students
                WHERE student_number = ?
                  AND student_email = ?
                  AND university = ?
                """,
                (student_number, email, UNB_CODE)
            ).fetchone()

            if student is None:
                record_failure(conn, client_ip, current_time)
                return render_home(
                    "This student ID and email combination was not found in "
                    "our database. Please contact the university for assistance.",
                    "error"
                )

            conn.execute(
                "DELETE FROM otp_requests WHERE requested_at < ?",
                (current_time - LOCKOUT_SECONDS,)
            )
            request_count = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM otp_requests
                WHERE client_ip = ? OR student_number = ?
                """,
                (client_ip, student_number)
            ).fetchone()["total"]
            if request_count >= MAX_OTP_REQUESTS:
                return render_home(
                    "Too many code requests. Please try again after ten minutes.",
                    "error"
                ), 429

            challenge_id = secrets.token_urlsafe(24)
            code = f"{secrets.randbelow(1_000_000):06d}"
            conn.execute(
                "DELETE FROM otp_challenges WHERE student_number = ?",
                (student_number,)
            )
            conn.execute(
                """
                INSERT INTO otp_challenges
                (challenge_id, student_number, email, university,
                 otp_hash, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    challenge_id,
                    student_number,
                    email,
                    UNB_CODE,
                    otp_digest(challenge_id, code),
                    current_time + OTP_LIFETIME_SECONDS
                )
            )
            otp_request_id = insert_otp_request(
                conn, client_ip, student_number, current_time
            )

    try:
        send_otp_email(student["student_email"], code)
    except (smtplib.SMTPException, OSError, ValueError, TypeError):
        with closing(get_connection()) as conn:
            with conn:
                conn.execute(
                    "DELETE FROM otp_challenges WHERE challenge_id = ?",
                    (challenge_id,)
                )
                conn.execute(
                    "DELETE FROM otp_requests WHERE id = ?",
                    (otp_request_id,)
                )
        app.logger.exception("Failed to send CampusPass OTP email")
        return render_home(
            "We could not send the verification email. Please try again later.",
            "error"
        ), 502

    session["challenge_id"] = challenge_id
    return render_home(
        "A verification code has been sent to your UNB student email.",
        "info"
    )


@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    if not csrf_is_valid():
        return render_home("Please reload the page and try again.", "error"), 400

    challenge_id = session.get("challenge_id")
    code = request.form.get("otp", "").strip()
    client_ip = request.remote_addr or "unknown"
    current_time = time.time()

    with closing(get_connection()) as conn:
        with conn:
            if failure_count(conn, client_ip, current_time) >= MAX_FAILED_ATTEMPTS:
                return render_home(
                    "Too many attempts. Please try again after ten minutes.",
                    "error"
                ), 429

            challenge = None
            if isinstance(challenge_id, str):
                challenge = conn.execute(
                    """
                    SELECT student_number, email, university, otp_hash,
                           expires_at, attempts
                    FROM otp_challenges
                    WHERE challenge_id = ?
                    """,
                    (challenge_id,)
                ).fetchone()

            if (
                challenge is None
                or challenge["expires_at"] <= current_time
                or challenge["attempts"] >= OTP_MAX_ATTEMPTS
                or len(code) != 6
                or not code.isdigit()
                or not hmac.compare_digest(
                    challenge["otp_hash"], otp_digest(challenge_id, code)
                )
            ):
                if challenge is not None:
                    attempts = challenge["attempts"] + 1
                    if attempts >= OTP_MAX_ATTEMPTS:
                        conn.execute(
                            "DELETE FROM otp_challenges WHERE challenge_id = ?",
                            (challenge_id,)
                        )
                        session.pop("challenge_id", None)
                    else:
                        conn.execute(
                            """
                            UPDATE otp_challenges
                            SET attempts = ?
                            WHERE challenge_id = ?
                            """,
                            (attempts, challenge_id)
                        )
                record_failure(conn, client_ip, current_time)
                return render_home(
                    "That code is invalid or expired. Request a new code and try again.",
                    "error"
                ), 403

            conn.execute(
                "DELETE FROM otp_challenges WHERE challenge_id = ?",
                (challenge_id,)
            )

    session.clear()
    session.permanent = True
    session["verified_student_number"] = challenge["student_number"]
    session["verified_until"] = current_time + app.config[
        "PERMANENT_SESSION_LIFETIME"
    ].total_seconds()
    flash("Email verified. You can now check or claim your pass.", "success")
    return redirect(url_for("home"))


@app.route("/claim", methods=["POST"])
def claim_pass():
    if not csrf_is_valid():
        return render_home("Please reload the page and try again.", "error"), 400

    student_number = session.get("verified_student_number")
    if (
        not student_number
        or session.get("verified_until", 0) <= time.time()
    ):
        session.clear()
        return render_home("Verify your student email before claiming a pass.", "error"), 401

    with closing(get_connection()) as conn:
        with conn:
            student = conn.execute(
                """
                SELECT student_email
                FROM students
                WHERE student_number = ?
                  AND university = ?
                """,
                (student_number, UNB_CODE)
            ).fetchone()
            if student is None:
                session.clear()
                return render_home(
                    "Student details could not be verified. Please start again.",
                    "error"
                ), 403

            result = conn.execute(
                """
                INSERT INTO passes (student_number, claimant_email, verified)
                VALUES (?, ?, 1)
                ON CONFLICT(student_number) DO UPDATE SET
                    claimant_email = excluded.claimant_email,
                    verified = 1
                WHERE passes.verified = 0
                """,
                (student_number, student["student_email"])
            )

    if result.rowcount:
        flash("Your bus pass has been claimed successfully.", "success")
    else:
        flash("Your bus pass has already been claimed.", "info")
    return redirect(url_for("home"))


@app.route("/logout", methods=["POST"])
def logout():
    if not csrf_is_valid():
        return render_home("Please reload the page and try again.", "error"), 400
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("home"))


@app.route("/start-over", methods=["POST"])
def start_over():
    if not csrf_is_valid():
        return render_home("Please reload the page and try again.", "error"), 400
    challenge_id = session.pop("challenge_id", None)
    if isinstance(challenge_id, str):
        with closing(get_connection()) as conn:
            with conn:
                conn.execute(
                    "DELETE FROM otp_challenges WHERE challenge_id = ?",
                    (challenge_id,)
                )
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )
