"""
Users + login + saved jobs -> SQLite (stdlib, koi extra install nahi).
- Password pbkdf2-sha256 se hash hota hai (plain text kabhi store nahi).
- Login pe ek random session token milta hai (client Authorization header mein bhejta hai).
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    c = _conn()
    c.executescript("""
      CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        pw_hash TEXT NOT NULL,
        pw_salt TEXT NOT NULL,
        created REAL);
      CREATE TABLE IF NOT EXISTS sessions(
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created REAL);
      CREATE TABLE IF NOT EXISTS saved(
        user_id INTEGER NOT NULL,
        job_id TEXT NOT NULL,
        job_json TEXT NOT NULL,
        created REAL,
        PRIMARY KEY(user_id, job_id));
      CREATE TABLE IF NOT EXISTS profiles(
        user_id INTEGER PRIMARY KEY,
        resume TEXT,
        filename TEXT,
        updated REAL);
    """)
    c.commit()
    c.close()


def set_resume(uid, text, filename=""):
    c = _conn()
    c.execute("INSERT OR REPLACE INTO profiles(user_id,resume,filename,updated) VALUES(?,?,?,?)",
              (uid, text, filename, time.time()))
    c.commit()
    c.close()


def get_resume(uid):
    c = _conn()
    r = c.execute("SELECT resume, filename FROM profiles WHERE user_id=?", (uid,)).fetchone()
    c.close()
    return (r["resume"], r["filename"]) if r else ("", "")


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(),
                               bytes.fromhex(salt), 100_000).hex()


def _new_session(uid):
    token = secrets.token_urlsafe(32)
    c = _conn()
    c.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)",
              (token, uid, time.time()))
    c.commit()
    c.close()
    return token


def signup(email, password):
    email = (email or "").strip().lower()
    if "@" not in email or len(password or "") < 4:
        raise ValueError("Enter a valid email and a password of at least 4 characters")
    salt = secrets.token_hex(16)
    c = _conn()
    try:
        cur = c.execute(
            "INSERT INTO users(email,pw_hash,pw_salt,created) VALUES(?,?,?,?)",
            (email, _hash(password, salt), salt, time.time()))
        uid = cur.lastrowid
        c.commit()
    except sqlite3.IntegrityError:
        c.close()
        raise ValueError("This email is already registered — please log in")
    c.close()
    return _new_session(uid), email


def login(email, password):
    email = (email or "").strip().lower()
    c = _conn()
    u = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    c.close()
    if not u or not hmac.compare_digest(u["pw_hash"], _hash(password, u["pw_salt"])):
        raise ValueError("Wrong email or password")
    return _new_session(u["id"]), email


def user_for_token(token):
    if not token:
        return None
    c = _conn()
    row = c.execute("""SELECT u.id, u.email FROM sessions s
                       JOIN users u ON u.id = s.user_id WHERE s.token=?""",
                    (token,)).fetchone()
    c.close()
    return dict(row) if row else None


def logout(token):
    c = _conn()
    c.execute("DELETE FROM sessions WHERE token=?", (token,))
    c.commit()
    c.close()


def list_saved(uid):
    c = _conn()
    rows = c.execute("SELECT job_json FROM saved WHERE user_id=? ORDER BY created DESC",
                     (uid,)).fetchall()
    c.close()
    return [json.loads(r["job_json"]) for r in rows]


def save_job(uid, job):
    jid = str(job.get("id") or job.get("url") or job.get("title") or "")
    if not jid:
        return
    c = _conn()
    c.execute("INSERT OR REPLACE INTO saved(user_id,job_id,job_json,created) VALUES(?,?,?,?)",
              (uid, jid, json.dumps(job), time.time()))
    c.commit()
    c.close()


def unsave_job(uid, job_id):
    c = _conn()
    c.execute("DELETE FROM saved WHERE user_id=? AND job_id=?", (uid, job_id))
    c.commit()
    c.close()


def ensure_default(email="demo@jobhunt.local", password="demo123"):
    """Default demo account bana do (agar pehle se nahi hai) taake seedha login ho."""
    try:
        signup(email, password)
    except ValueError:
        pass  # pehle se maujood

