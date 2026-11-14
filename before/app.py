
from flask import Flask, render_template, request
from database import initialize_database, get_connection

app = Flask(__name__)
initialize_database()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/claim", methods=["POST"])
def claim_pass():
    email = request.form.get("email", "").strip().lower()
    university = request.form.get("university", "")
    student_number = request.form.get("student_number", "").strip()

    if not email or not university or not student_number:
        return "<h2>Missing information.</h2>", 400

    with get_connection() as conn:
        student = conn.execute(
            """
            SELECT student_number
            FROM students
            WHERE student_number = ? AND university = ?
            """,
            (student_number, university)
        ).fetchone()

        if not student:
            return "<h2>Invalid student number.</h2>"

        existing_pass = conn.execute(
            "SELECT 1 FROM passes WHERE student_number = ?",
            (student_number,)
        ).fetchone()

        if existing_pass:
            return "<h2>This bus pass has already been claimed.</h2>"

        # INTENTIONAL VULNERABILITY:
        # No verification that the email belongs to the student.
        conn.execute(
            """
            INSERT INTO passes (student_number, claimant_email)
            VALUES (?, ?)
            """,
            (student_number, email)
        )

    return """
        <h2>Bus Pass Claimed Successfully!</h2>
        <p>Your student bus pass has been activated.</p>
        <a href="/">Return to CampusPass</a>
    """


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
