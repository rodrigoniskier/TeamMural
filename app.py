import mimetypes
import os
import secrets
import sqlite3
import time
import uuid
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from PIL import Image, UnidentifiedImageError
from storage import connect as storage_connect
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
PORTFOLIO_DEMO = os.environ.get("PORTFOLIO_DEMO") == "1"
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "teammural.db"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", BASE_DIR / "uploads"))
MAX_UPLOAD_MB = max(1, int(os.environ.get("MAX_UPLOAD_MB", "25")))
MAX_MESSAGE_LENGTH = 5000
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 8

app = Flask(__name__)
if os.environ.get("VERCEL") and (not os.environ.get("SECRET_KEY") or not DATABASE_URL):
    raise RuntimeError("Persistent DATABASE_URL and SECRET_KEY are required on Vercel")
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(48)
app.config.update(
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
)

if not PORTFOLIO_DEMO: UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_login_attempts = {}


def db_connect():
    return storage_connect(DATABASE_URL, DATABASE_PATH)


def init_db():
    with db_connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('admin', 'member')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'group' CHECK(kind IN ('group', 'direct')),
                dm_key TEXT UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS channel_members (
                channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                PRIMARY KEY (channel_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                body TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'text' CHECK(kind IN ('text', 'image', 'video', 'audio', 'file')),
                stored_name TEXT,
                original_name TEXT,
                mime_type TEXT,
                size_bytes INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        general = conn.execute(
            "SELECT id FROM channels WHERE name = ? AND kind = 'group'", ("General",)
        ).fetchone()
        if not general:
            conn.execute("INSERT INTO channels (name, kind) VALUES (?, 'group')", ("General",))

        admin_email = (os.environ.get("TEAMMURAL_ADMIN_EMAIL") or "").strip().lower()
        admin_password = os.environ.get("TEAMMURAL_ADMIN_PASSWORD") or ""
        admin_name = (os.environ.get("TEAMMURAL_ADMIN_NAME") or "Workspace Admin").strip()
        if admin_email and len(admin_password) >= 12:
            exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (admin_email,)).fetchone()
            if not exists:
                cursor = conn.execute(
                    "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
                    (admin_name, admin_email, generate_password_hash(admin_password)),
                )
                general_id = conn.execute(
                    "SELECT id FROM channels WHERE name = 'General' AND kind = 'group'"
                ).fetchone()["id"]
                conn.execute(
                    "INSERT OR IGNORE INTO channel_members (channel_id, user_id) VALUES (?, ?)",
                    (general_id, cursor.lastrowid),
                )


init_db()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db_connect() as conn:
        return conn.execute(
            "SELECT id, name, email, role, active FROM users WHERE id = ? AND active = 1",
            (user_id,),
        ).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("login"))
        if user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.context_processor
def inject_csrf():
    return {"csrf_token": csrf_token, "me": current_user(), "portfolio_demo": PORTFOLIO_DEMO}


def require_csrf():
    provided = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    expected = session.get("csrf_token")
    if not provided or not expected or not secrets.compare_digest(provided, expected):
        abort(400, "Invalid CSRF token")


def client_key():
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded or request.remote_addr or "unknown"


def login_allowed():
    key = client_key()
    now = time.time()
    bucket = [ts for ts in _login_attempts.get(key, []) if now - ts < LOGIN_WINDOW_SECONDS]
    _login_attempts[key] = bucket
    return len(bucket) < LOGIN_MAX_ATTEMPTS


def record_login_failure():
    _login_attempts.setdefault(client_key(), []).append(time.time())


def clear_login_failures():
    _login_attempts.pop(client_key(), None)


def classify_file(mime_type):
    mime_type = (mime_type or "").lower()
    safe_images = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"}
    if mime_type in safe_images:
        return "image"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type.startswith("audio/"):
        return "audio"
    return "file"


def storage_name(original_name):
    safe = secure_filename(original_name or "file")[:140] or "file"
    path = Path(safe)
    return f"{uuid.uuid4().hex}_{path.stem[:100]}{path.suffix[:20]}"


def validate_image(path):
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        return False


def authorized_channel(conn, user_id, channel_id):
    return conn.execute(
        "SELECT c.* FROM channels c JOIN channel_members cm ON cm.channel_id = c.id "
        "WHERE c.id = ? AND cm.user_id = ?",
        (channel_id, user_id),
    ).fetchone()


def direct_channel(conn, user_a, user_b):
    left, right = sorted((int(user_a), int(user_b)))
    key = f"{left}:{right}"
    channel = conn.execute("SELECT * FROM channels WHERE dm_key = ?", (key,)).fetchone()
    if channel:
        return channel
    cursor = conn.execute(
        "INSERT INTO channels (name, kind, dm_key) VALUES (?, 'direct', ?)",
        ("Direct message", key),
    )
    channel_id = cursor.lastrowid
    conn.execute("INSERT INTO channel_members (channel_id, user_id) VALUES (?, ?)", (channel_id, left))
    conn.execute("INSERT INTO channel_members (channel_id, user_id) VALUES (?, ?)", (channel_id, right))
    return conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,)).fetchone()


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "microphone=(), camera=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    if request.is_secure or os.environ.get("FORCE_HTTPS") == "1":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    return jsonify({"error": f"File exceeds the {MAX_UPLOAD_MB} MB limit."}), 413


@app.get("/healthz")
def healthz():
    try:
        with db_connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return jsonify({"status": "ok"})
    except sqlite3.Error:
        return jsonify({"status": "error"}), 503


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("home"))
    error = None
    if request.method == "POST":
        require_csrf()
        if not login_allowed():
            return render_template("login.html", error="Too many attempts. Try again later."), 429
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        with db_connect() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE email = ? AND active = 1", (email,)
            ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            clear_login_failures()
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True
            return redirect(url_for("home"))
        record_login_failure()
        error = "Invalid email or password."
    return render_template("login.html", error=error)


@app.post("/logout")
@login_required
def logout():
    require_csrf()
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def home():
    user = current_user()
    with db_connect() as conn:
        channels = conn.execute(
            "SELECT c.id, c.name, c.kind, c.dm_key FROM channels c "
            "JOIN channel_members cm ON cm.channel_id = c.id WHERE cm.user_id = ? ORDER BY c.kind, c.name",
            (user["id"],),
        ).fetchall()
        users = conn.execute(
            "SELECT id, name, email FROM users WHERE active = 1 AND id <> ? ORDER BY name",
            (user["id"],),
        ).fetchall()
    return render_template("index.html", channels=channels, users=users, max_upload_mb=MAX_UPLOAD_MB)


@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    if PORTFOLIO_DEMO: abort(403)
    error = None
    success = None
    if request.method == "POST":
        require_csrf()
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        role = request.form.get("role") or "member"
        if not name or "@" not in email or len(password) < 12 or role not in {"admin", "member"}:
            error = "Use a valid name/email and a password with at least 12 characters."
        else:
            try:
                with db_connect() as conn:
                    cursor = conn.execute(
                        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                        (name, email, generate_password_hash(password), role),
                    )
                    general_id = conn.execute(
                        "SELECT id FROM channels WHERE name = 'General' AND kind = 'group'"
                    ).fetchone()["id"]
                    conn.execute(
                        "INSERT OR IGNORE INTO channel_members (channel_id, user_id) VALUES (?, ?)",
                        (general_id, cursor.lastrowid),
                    )
                success = "User created."
            except sqlite3.IntegrityError:
                error = "Email already exists."
    with db_connect() as conn:
        users = conn.execute(
            "SELECT id, name, email, role, active, created_at FROM users ORDER BY name"
        ).fetchall()
    return render_template("admin_users.html", users=users, error=error, success=success)


@app.post("/api/direct/<int:user_id>")
@login_required
def create_direct(user_id):
    require_csrf()
    me = current_user()
    if user_id == me["id"]:
        return jsonify({"error": "Invalid recipient."}), 400
    with db_connect() as conn:
        other = conn.execute("SELECT id FROM users WHERE id = ? AND active = 1", (user_id,)).fetchone()
        if not other:
            return jsonify({"error": "User not found."}), 404
        channel = direct_channel(conn, me["id"], user_id)
    return jsonify({"channel_id": channel["id"]})


@app.get("/api/messages/<int:channel_id>")
@login_required
def messages(channel_id):
    me = current_user()
    with db_connect() as conn:
        if not authorized_channel(conn, me["id"], channel_id):
            return jsonify({"error": "Forbidden."}), 403
        rows = conn.execute(
            "SELECT m.id, m.channel_id, m.user_id, u.name AS author, m.body, m.kind, "
            "m.stored_name, m.original_name, m.mime_type, m.size_bytes, m.created_at "
            "FROM messages m JOIN users u ON u.id = m.user_id "
            "WHERE m.channel_id = ? ORDER BY m.id ASC LIMIT 500",
            (channel_id,),
        ).fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        item["created_at"]=str(item["created_at"])
        result.append(item)
    return jsonify(result)


@app.post("/api/messages/<int:channel_id>")
@login_required
def send_message(channel_id):
    require_csrf()
    me = current_user()
    payload = request.get_json(silent=True) or {}
    body = str(payload.get("body") or "").strip()
    if PORTFOLIO_DEMO:
        if session.get("message_count",0)>=20:
            return jsonify({"error":"Limite da sessão atingido. Reentre na demonstração."}),429
        session["message_count"]=session.get("message_count",0)+1
    if not body or len(body) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": "Message is empty or too long."}), 400
    with db_connect() as conn:
        if not authorized_channel(conn, me["id"], channel_id):
            return jsonify({"error": "Forbidden."}), 403
        if PORTFOLIO_DEMO and conn.execute("SELECT COUNT(*) AS total FROM messages").fetchone()["total"] >= 300:
            return jsonify({"error":"Limite de mensagens da demonstração atingido."}),429
        cursor = conn.execute(
            "INSERT INTO messages (channel_id, user_id, body, kind) VALUES (?, ?, ?, 'text')",
            (channel_id, me["id"], body),
        )
    return jsonify({"id": cursor.lastrowid}), 201


@app.post("/api/upload/<int:channel_id>")
@login_required
def upload(channel_id):
    if PORTFOLIO_DEMO: return jsonify({"error":"Novos uploads estão desabilitados na demonstração."}),403
    require_csrf()
    me = current_user()
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file selected."}), 400
    with db_connect() as conn:
        if not authorized_channel(conn, me["id"], channel_id):
            return jsonify({"error": "Forbidden."}), 403

    original_name = Path(file.filename).name[:255]
    stored_name = storage_name(original_name)
    path = UPLOAD_DIR / stored_name
    mime = (file.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream").split(";")[0]
    kind = classify_file(mime)
    try:
        file.save(path)
        if kind == "image" and not validate_image(path):
            kind = "file"
            mime = "application/octet-stream"
        size = path.stat().st_size
        with db_connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (channel_id, user_id, body, kind, stored_name, original_name, mime_type, size_bytes) "
                "VALUES (?, ?, '', ?, ?, ?, ?, ?)",
                (channel_id, me["id"], kind, stored_name, original_name, mime, size),
            )
        return jsonify({"id": cursor.lastrowid, "kind": kind}), 201
    except (OSError, sqlite3.Error):
        path.unlink(missing_ok=True)
        app.logger.exception("Upload failed")
        return jsonify({"error": "Upload failed."}), 500


def file_record(stored_name, user_id):
    safe_name = Path(stored_name).name
    if safe_name != stored_name:
        return None
    with db_connect() as conn:
        return conn.execute(
            "SELECT m.*, cm.user_id AS member_id FROM messages m "
            "JOIN channel_members cm ON cm.channel_id = m.channel_id "
            "WHERE m.stored_name = ? AND cm.user_id = ? LIMIT 1",
            (safe_name, user_id),
        ).fetchone()


@app.get("/media/<stored_name>")
@login_required
def media(stored_name):
    me = current_user()
    record = file_record(stored_name, me["id"])
    if not record or record["kind"] not in {"image", "video", "audio"}:
        abort(404)
    return send_from_directory(
        UPLOAD_DIR, stored_name,
        mimetype=record["mime_type"] or "application/octet-stream",
        conditional=True, max_age=3600,
    )


@app.get("/download/<stored_name>")
@login_required
def download(stored_name):
    me = current_user()
    record = file_record(stored_name, me["id"])
    if not record:
        abort(404)
    return send_from_directory(
        UPLOAD_DIR, stored_name,
        as_attachment=True,
        download_name=record["original_name"] or "attachment",
        mimetype="application/octet-stream",
        conditional=True, max_age=0,
    )


@app.post("/demo/enter")
def demo_enter():
    if not PORTFOLIO_DEMO: abort(404)
    require_csrf()
    with db_connect() as conn:
        user=conn.execute("SELECT id FROM users WHERE email = ? AND role = 'member'",("mariana@example.invalid",)).fetchone()
    if not user: return "Demonstração em preparação.",503
    session.clear()
    session["user_id"]=user["id"]
    session["csrf_token"]=secrets.token_urlsafe(32)
    return redirect(url_for("home"))

@app.get("/demo/attachment")
@login_required
def demo_attachment():
    if not PORTFOLIO_DEMO: abort(404)
    from flask import Response
    return Response("ROTEIRO DA REUNIÃO — MATERIAL FICTÍCIO\n\n1. Revisar entregas da semana\n2. Identificar impedimentos\n3. Definir responsáveis e próximos passos\n",mimetype="text/plain",headers={"Content-Disposition":"attachment; filename=roteiro-reuniao.txt"})

@app.errorhandler(500)
def server_error(error):
    return jsonify({"error":"Não foi possível concluir a operação. Tente novamente."}),500

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
