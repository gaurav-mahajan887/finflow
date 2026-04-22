import os
import re
import bcrypt

# ── Detect DB ────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

USE_POSTGRES = bool(DATABASE_URL)


# ── Connection helpers ───────────────────────────────────────
def _get_pg_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def _get_sqlite_conn():
    import sqlite3
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base, "finflow_users.db")
    return sqlite3.connect(db_path)


def _conn():
    return _get_pg_conn() if USE_POSTGRES else _get_sqlite_conn()


# ── DB init ──────────────────────────────────────────────────
def init_db():
    if USE_POSTGRES:
        sql = """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(80) UNIQUE NOT NULL,
            email VARCHAR(200) UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created TIMESTAMP DEFAULT NOW()
        );
        """
    else:
        sql = """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created TEXT DEFAULT (datetime('now'))
        );
        """

    try:
        con = _conn()
        cur = con.cursor()
        cur.execute(sql)
        con.commit()
        con.close()
        print(f"[auth] DB init OK — using {'PostgreSQL' if USE_POSTGRES else 'SQLite'}")
    except Exception as e:
        print(f"[auth] DB init error: {e}")


# ── Password hashing (SECURE) ────────────────────────────────
def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def _verify(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode())


# ── Validation ───────────────────────────────────────────────
def validate_signup(username: str, email: str, password: str) -> list:
    errors = []
    if len(username) < 3:
        errors.append("Username must be at least 3 characters.")
    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        errors.append("Username: letters, numbers and underscores only.")
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        errors.append("Please enter a valid email address.")
    if len(password) < 6:
        errors.append("Password must be at least 6 characters.")
    return errors


# ── Signup ───────────────────────────────────────────────────
def signup_user(username: str, email: str, password: str) -> dict:
    errors = validate_signup(username, email, password)
    if errors:
        return {"ok": False, "error": errors[0]}

    try:
        con = _conn()
        cur = con.cursor()

        query = (
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)"
            if USE_POSTGRES else
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)"
        )

        cur.execute(
            query,
            (username.strip(), email.strip().lower(), _hash(password))
        )

        con.commit()
        con.close()

        return {"ok": True, "username": username.strip()}

    except Exception as e:
        err = str(e).lower()
        if "email" in err:
            return {"ok": False, "error": "Email already registered."}
        if "username" in err or "unique" in err:
            return {"ok": False, "error": "Username already taken."}
        return {"ok": False, "error": "Signup failed. Try again."}


# ── Login ────────────────────────────────────────────────────
def login_user(identifier: str, password: str) -> dict:
    try:
        con = _conn()
        cur = con.cursor()

        query = (
            "SELECT username, password FROM users WHERE username=%s OR email=%s"
            if USE_POSTGRES else
            "SELECT username, password FROM users WHERE username=? OR email=?"
        )

        cur.execute(query, (identifier.strip(), identifier.strip().lower()))
        row = cur.fetchone()
        con.close()

        if row and _verify(password, row[1]):
            return {"ok": True, "username": row[0]}

        return {"ok": False, "error": "Invalid username/email or password."}

    except Exception as e:
        return {"ok": False, "error": str(e)}