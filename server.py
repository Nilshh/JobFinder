from flask import Flask, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import os
import json
import sqlite3
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

APP_ID  = os.environ.get("ADZUNA_APP_ID",  "")
APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", ""))
APP_URL   = os.environ.get("APP_URL", "http://localhost:8080")

_dir     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(_dir, "data"))
DB_PATH  = os.path.join(DATA_DIR, "jobfinder.db")


# ── Database ──────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                email         TEXT,
                created_at    TEXT DEFAULT (datetime('now'))
            )
        """)
        # Migration: email column for existing installations
        try:
            db.execute("ALTER TABLE users ADD COLUMN email TEXT")
        except Exception:
            pass
        db.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                user_id     INTEGER PRIMARY KEY,
                saved       TEXT NOT NULL DEFAULT '{}',
                ignored     TEXT NOT NULL DEFAULT '[]',
                jira_config TEXT NOT NULL DEFAULT '{}',
                updated_at  TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token      TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        # Indexes
        db.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_reset_tokens_user ON password_reset_tokens(user_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_reset_tokens_expires ON password_reset_tokens(expires_at)")

init_db()


# ── Helpers ──────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 204
        if "user_id" not in session:
            return jsonify({"error": "Nicht angemeldet"}), 401
        return f(*args, **kwargs)
    return decorated

def _parse(r):
    """Safely parse Jira response – falls back to text if body isn't JSON."""
    try:
        return jsonify(r.json()), r.status_code
    except ValueError:
        print(f"[jira] Non-JSON response HTTP {r.status_code}: {r.text[:300]}")
        return jsonify({
            "errorMessages": [f"Unerwartete Antwort vom Server (HTTP {r.status_code})"],
            "detail": r.text[:300]
        }), r.status_code

def send_reset_email(to_email, reset_url):
    if not SMTP_HOST or not SMTP_USER:
        raise ValueError(
            "SMTP nicht konfiguriert – bitte SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env setzen"
        )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "JobPipeline – Passwort zurücksetzen"
    msg["From"]    = SMTP_FROM
    msg["To"]      = to_email
    body = f"""
<div style="font-family:'Segoe UI',sans-serif;max-width:480px;margin:0 auto;background:#0a0a0f;color:#f0f0f5;border-radius:14px;padding:32px 28px;">
  <div style="font-size:22px;font-weight:900;margin-bottom:4px;background:linear-gradient(135deg,#ff4d6d,#ffd166);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">JobPipeline</div>
  <h3 style="margin:0 0 16px;color:#f0f0f5;font-size:18px;">Passwort zurücksetzen</h3>
  <p style="color:#9090a0;line-height:1.6;margin-bottom:24px;">Du hast eine Anfrage zum Zurücksetzen deines Passworts gestellt. Klicke auf den Button, um ein neues Passwort zu vergeben.</p>
  <div style="text-align:center;margin-bottom:28px;">
    <a href="{reset_url}" style="background:linear-gradient(135deg,#ff4d6d,#c9184a);color:#fff;padding:13px 28px;border-radius:10px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block;">Passwort zurücksetzen</a>
  </div>
  <p style="color:#6b6b80;font-size:12px;line-height:1.6;">Dieser Link ist <strong style="color:#9090a0;">1 Stunde</strong> gültig. Falls du kein Passwort-Reset angefordert hast, ignoriere diese E-Mail.</p>
  <p style="color:#6b6b80;font-size:11px;word-break:break-all;">Link: {reset_url}</p>
</div>"""
    msg.attach(MIMEText(body, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.sendmail(SMTP_FROM, to_email, msg.as_string())


# ── CORS ──────────────────────────────────────────────────────────

@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "")
    response.headers["Access-Control-Allow-Origin"]      = origin if origin else "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Headers"]     = "Content-Type, Authorization, X-Jira-Domain"
    response.headers["Access-Control-Allow-Methods"]     = "GET, POST, DELETE, OPTIONS"
    return response


# ── Auth ──────────────────────────────────────────────────────────

@app.route("/auth/register", methods=["POST", "OPTIONS"])
def auth_register():
    if request.method == "OPTIONS":
        return "", 204
    data     = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    email    = (data.get("email")    or "").strip().lower()
    if not username or not password:
        return jsonify({"error": "Benutzername und Passwort erforderlich"}), 400
    if len(username) < 3:
        return jsonify({"error": "Benutzername muss mindestens 3 Zeichen lang sein"}), 400
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen lang sein"}), 400
    if email and "@" not in email:
        return jsonify({"error": "Ungültige E-Mail-Adresse"}), 400
    pw_hash = generate_password_hash(password)
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
                [username, pw_hash, email or None]
            )
            user = db.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE", [username]
            ).fetchone()
            db.execute("INSERT INTO user_data (user_id) VALUES (?)", [user["id"]])
        session.permanent = True
        session["user_id"]  = user["id"]
        session["username"] = username
        return jsonify({"ok": True, "username": username})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Benutzername bereits vergeben"}), 409


@app.route("/auth/login", methods=["POST", "OPTIONS"])
def auth_login():
    if request.method == "OPTIONS":
        return "", 204
    data     = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    with get_db() as db:
        user = db.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", [username]
        ).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Ungültiger Benutzername oder Passwort"}), 401
    session.permanent = True
    session["user_id"]  = user["id"]
    session["username"] = user["username"]
    return jsonify({"ok": True, "username": user["username"]})


@app.route("/auth/logout", methods=["POST", "OPTIONS"])
def auth_logout():
    if request.method == "OPTIONS":
        return "", 204
    session.clear()
    return jsonify({"ok": True})


@app.route("/auth/me")
def auth_me():
    if "user_id" not in session:
        return jsonify({"user": None})
    return jsonify({"user": {"id": session["user_id"], "username": session["username"]}})


@app.route("/auth/forgot", methods=["POST", "OPTIONS"])
def auth_forgot():
    if request.method == "OPTIONS":
        return "", 204
    data  = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "E-Mail-Adresse erforderlich"}), 400

    with get_db() as db:
        # Clean up expired tokens opportunistically
        db.execute(
            "DELETE FROM password_reset_tokens WHERE expires_at < ?",
            [datetime.now(timezone.utc).isoformat()]
        )
        user = db.execute(
            "SELECT * FROM users WHERE lower(email) = ?", [email]
        ).fetchone()

    if user:
        if not SMTP_HOST:
            return jsonify({"error": "E-Mail-Versand nicht konfiguriert (SMTP_HOST fehlt in .env)"}), 500
        token      = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with get_db() as db:
            db.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", [user["id"]])
            db.execute(
                "INSERT INTO password_reset_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
                [token, user["id"], expires_at]
            )
        reset_url = f"{APP_URL}/?reset={token}"
        try:
            send_reset_email(email, reset_url)
        except Exception as e:
            print(f"[forgot] E-Mail-Fehler: {e}")
            return jsonify({"error": f"E-Mail konnte nicht gesendet werden: {e}"}), 500

    # Always return success to prevent user enumeration
    return jsonify({"ok": True})


@app.route("/auth/reset", methods=["POST", "OPTIONS"])
def auth_reset():
    if request.method == "OPTIONS":
        return "", 204
    data     = request.get_json(force=True)
    token    = (data.get("token")    or "").strip()
    password = (data.get("password") or "")
    if not token or not password:
        return jsonify({"error": "Token und Passwort erforderlich"}), 400
    if len(password) < 8:
        return jsonify({"error": "Passwort muss mindestens 8 Zeichen lang sein"}), 400

    with get_db() as db:
        row = db.execute(
            "SELECT * FROM password_reset_tokens WHERE token = ?", [token]
        ).fetchone()
    if not row:
        return jsonify({"error": "Ungültiger oder bereits verwendeter Reset-Link"}), 400
    if row["expires_at"] < datetime.now(timezone.utc).isoformat():
        with get_db() as db:
            db.execute("DELETE FROM password_reset_tokens WHERE token = ?", [token])
        return jsonify({"error": "Dieser Reset-Link ist abgelaufen (1 Stunde)"}), 400

    pw_hash = generate_password_hash(password)
    with get_db() as db:
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", [pw_hash, row["user_id"]])
        db.execute("DELETE FROM password_reset_tokens WHERE token = ?", [token])
    return jsonify({"ok": True})


# ── User Data ─────────────────────────────────────────────────────

@app.route("/user/data", methods=["GET"])
@login_required
def get_user_data():
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM user_data WHERE user_id = ?", [session["user_id"]]
        ).fetchone()
    if not row:
        return jsonify({"saved": {}, "ignored": [], "jira": {}})
    return jsonify({
        "saved":   json.loads(row["saved"]),
        "ignored": json.loads(row["ignored"]),
        "jira":    json.loads(row["jira_config"])
    })


@app.route("/user/data", methods=["POST", "OPTIONS"])
@login_required
def save_user_data():
    data = request.get_json(force=True)
    with get_db() as db:
        db.execute("""
            INSERT INTO user_data (user_id, saved, ignored, jira_config)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                saved       = excluded.saved,
                ignored     = excluded.ignored,
                jira_config = excluded.jira_config,
                updated_at  = datetime('now')
        """, [
            session["user_id"],
            json.dumps(data.get("saved",   {})),
            json.dumps(data.get("ignored", [])),
            json.dumps(data.get("jira",    {}))
        ])
    return jsonify({"ok": True})


# ── Jobs (Adzuna proxy) ──────────────────────────────────────────

@app.route("/jobs")
def jobs():
    title    = request.args.get("what", "")
    location = request.args.get("where", "")
    radius   = request.args.get("distance", "50")
    country  = request.args.get("country", "de")
    params = {
        "app_id":           APP_ID,
        "app_key":          APP_KEY,
        "results_per_page": 20,
        "what":             title,
        "distance":         radius,
        "content-type":     "application/json",
    }
    if location:
        params["where"] = location
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    try:
        r = requests.get(url, params=params, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Jira ──────────────────────────────────────────────────────────

@app.route("/jira/test", methods=["GET", "OPTIONS"])
def jira_test():
    if request.method == "OPTIONS":
        return "", 204
    domain = request.headers.get("X-Jira-Domain", "").strip()
    auth   = request.headers.get("Authorization", "")
    print(f"[jira/test] domain={domain!r} auth_present={bool(auth)}")
    if not domain or not auth:
        return jsonify({"errorMessages": ["Fehlende Header: X-Jira-Domain oder Authorization"]}), 400
    url = f"https://{domain}/rest/api/3/myself"
    try:
        r = requests.get(
            url, headers={"Authorization": auth, "Accept": "application/json"}, timeout=10
        )
        print(f"[jira/test] HTTP {r.status_code}")
        return _parse(r)
    except Exception as e:
        print(f"[jira/test] Exception: {e}")
        return jsonify({"errorMessages": [str(e)]}), 500


@app.route("/jira/fields", methods=["GET", "OPTIONS"])
def jira_fields():
    if request.method == "OPTIONS":
        return "", 204
    domain    = request.headers.get("X-Jira-Domain", "").strip()
    auth      = request.headers.get("Authorization", "")
    project   = request.args.get("project", "")
    issuetype = request.args.get("issuetype", "")
    print(f"[jira/fields] domain={domain!r} project={project!r} issuetype={issuetype!r}")
    if not domain or not auth or not project:
        return jsonify({"error": "Fehlende Parameter"}), 400
    if issuetype:
        url = f"https://{domain}/rest/api/3/issue/createmeta/{project}/issuetypes/{issuetype}"
    else:
        url = f"https://{domain}/rest/api/3/issue/createmeta/{project}/issuetypes"
    try:
        r = requests.get(
            url, headers={"Authorization": auth, "Accept": "application/json"}, timeout=10
        )
        print(f"[jira/fields] HTTP {r.status_code}")
        return _parse(r)
    except Exception as e:
        print(f"[jira/fields] Exception: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/jira/issue", methods=["POST", "OPTIONS"])
def jira_issue():
    if request.method == "OPTIONS":
        return "", 204
    domain = request.headers.get("X-Jira-Domain", "").strip()
    auth   = request.headers.get("Authorization", "")
    print(f"[jira/issue] domain={domain!r} auth_present={bool(auth)}")
    if not domain or not auth:
        return jsonify({"errorMessages": ["Fehlende Header: X-Jira-Domain oder Authorization"]}), 400
    url = f"https://{domain}/rest/api/3/issue"
    try:
        r = requests.post(
            url,
            json=request.get_json(force=True),
            headers={
                "Authorization": auth,
                "Content-Type":  "application/json",
                "Accept":        "application/json",
            },
            timeout=15,
        )
        print(f"[jira/issue] HTTP {r.status_code}")
        if r.status_code >= 400:
            print(f"[jira/issue] Error body: {r.text[:500]}")
        return _parse(r)
    except Exception as e:
        print(f"[jira/issue] Exception: {e}")
        return jsonify({"errorMessages": [str(e)]}), 500


if __name__ == "__main__":
    print("✅ JobPipeline Server läuft auf http://localhost:5500")
    app.run(host="0.0.0.0", port=5500, debug=False)
