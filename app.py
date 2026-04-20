"""
Biểu mẫu PNJ 1305 — App lưu trữ, tìm kiếm, download biểu mẫu / chứng từ / văn bản.

Phase 1 (Library):
    - Upload docx/xlsx/pdf (admin only)
    - List + search không dấu theo title + tags
    - Download file gốc
    - Edit/delete (admin only)

Auth: shared DB /opt/pnj-shared/pnj-auth.db (module shared_auth).

Chạy local:
    python app.py
    → http://127.0.0.1:5053

Production (VPS):
    APPLICATION_ROOT=/bk/bieu-mau gunicorn -b 127.0.0.1:5053 -w 2 app:app
"""
import os
import sqlite3
import unicodedata
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, flash, g, jsonify, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

import config
import shared_auth

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
HERE = Path(__file__).parent
DB_PATH = HERE / "bieu-mau.db"
UPLOAD_DIR = HERE / config.UPLOAD_FOLDER_NAME
UPLOAD_DIR.mkdir(exist_ok=True)

# Truyền PNJ_AUTH_DB_PATH sang shared_auth (khi local dev khác default)
shared_auth.DB_PATH = config.PNJ_AUTH_DB_PATH


class PrefixMiddleware:
    """Strip APPLICATION_ROOT prefix khỏi PATH_INFO, set SCRIPT_NAME.
    Giống pattern /bk/thudoi/ — nginx proxy_pass giữ prefix, Flask match routes gốc.
    """
    def __init__(self, app, prefix):
        self.app = app
        self.prefix = prefix.rstrip("/")

    def __call__(self, environ, start_response):
        if not self.prefix:
            return self.app(environ, start_response)
        path = environ.get("PATH_INFO", "")
        if path == self.prefix or path.startswith(self.prefix + "/"):
            environ["PATH_INFO"] = path[len(self.prefix):] or "/"
            environ["SCRIPT_NAME"] = self.prefix
        return self.app(environ, start_response)


app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
app.config["SESSION_COOKIE_NAME"] = "session_bieumau"  # tránh đụng cookie app khác
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
_prefix = os.environ.get("APPLICATION_ROOT", "").strip()
if _prefix:
    app.wsgi_app = PrefixMiddleware(app.wsgi_app, _prefix)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS forms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            title_norm TEXT NOT NULL,
            description TEXT DEFAULT '',
            filename TEXT NOT NULL,
            orig_filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            size INTEGER NOT NULL,
            uploaded_by TEXT,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_forms_title_norm ON forms(title_norm);
        CREATE INDEX IF NOT EXISTS idx_forms_uploaded_at ON forms(uploaded_at DESC);

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name_norm TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tags_name_norm ON tags(name_norm);

        CREATE TABLE IF NOT EXISTS form_tags (
            form_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (form_id, tag_id),
            FOREIGN KEY (form_id) REFERENCES forms(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()


init_db()


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------
def normalize(s):
    """Lowercase, bỏ dấu tiếng Việt, chuẩn hoá space → dùng cho search."""
    if not s:
        return ""
    s = s.strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d")
    return " ".join(s.split())


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


def parse_tags(raw):
    """'Thu đổi, Biên bản , pnj' → ['Thu đổi', 'Biên bản', 'pnj'] (unique)."""
    if not raw:
        return []
    seen = set()
    out = []
    for t in raw.split(","):
        t = t.strip()
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def upsert_tags_for_form(db, form_id, tag_names):
    db.execute("DELETE FROM form_tags WHERE form_id = ?", (form_id,))
    for name in tag_names:
        name_norm = normalize(name)
        existing = db.execute(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        if existing:
            tag_id = existing["id"]
        else:
            cur = db.execute(
                "INSERT INTO tags (name, name_norm) VALUES (?, ?)", (name, name_norm)
            )
            tag_id = cur.lastrowid
        db.execute(
            "INSERT OR IGNORE INTO form_tags (form_id, tag_id) VALUES (?, ?)",
            (form_id, tag_id),
        )


def get_form_tags(db, form_id):
    rows = db.execute(
        "SELECT t.name FROM tags t JOIN form_tags ft ON t.id=ft.tag_id "
        "WHERE ft.form_id = ? ORDER BY t.name",
        (form_id,),
    ).fetchall()
    return [r["name"] for r in rows]


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return shared_auth.get_user(uid)


def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not session.get("user_id"):
            nxt = request.script_root + request.path
            return redirect(url_for("login", next=nxt))
        return f(*args, **kwargs)
    return wrap


def admin_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not session.get("user_id"):
            nxt = request.script_root + request.path
            return redirect(url_for("login", next=nxt))
        if session.get("role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrap


@app.context_processor
def inject_globals():
    return {
        "current_username": session.get("username"),
        "current_role": session.get("role"),
        "is_admin": session.get("role") == "admin",
    }


# ---------------------------------------------------------------------------
# Routes — Auth
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = request.form.get("password") or ""
        user = shared_auth.authenticate(u, p)
        if user:
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["user_type"] = user["user_type"]
            nxt = request.args.get("next") or url_for("index")
            return redirect(nxt)
        error = "Sai tài khoản hoặc mật khẩu"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Routes — Library
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    q_norm = normalize(q)
    db = get_db()

    if q_norm:
        like = f"%{q_norm}%"
        rows = db.execute("""
            SELECT DISTINCT f.* FROM forms f
            LEFT JOIN form_tags ft ON ft.form_id = f.id
            LEFT JOIN tags t ON t.id = ft.tag_id
            WHERE f.title_norm LIKE ? OR t.name_norm LIKE ?
            ORDER BY f.uploaded_at DESC
        """, (like, like)).fetchall()
    else:
        rows = db.execute("SELECT * FROM forms ORDER BY uploaded_at DESC").fetchall()

    forms = []
    for r in rows:
        d = dict(r)
        d["tags"] = get_form_tags(db, r["id"])
        d["size_kb"] = round(r["size"] / 1024, 1)
        forms.append(d)

    return render_template("index.html", forms=forms, q=q)


@app.route("/upload", methods=["GET", "POST"])
@admin_required
def upload():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        tags_raw = request.form.get("tags") or ""
        file = request.files.get("file")

        if not title:
            flash("Thiếu tên biểu mẫu.", "error")
            return render_template("upload.html", title=title, description=description, tags=tags_raw)
        if not file or not file.filename:
            flash("Chưa chọn file.", "error")
            return render_template("upload.html", title=title, description=description, tags=tags_raw)
        if not allowed_file(file.filename):
            flash(f"File type không hỗ trợ. Chỉ {', '.join(sorted(config.ALLOWED_EXTENSIONS))}.", "error")
            return render_template("upload.html", title=title, description=description, tags=tags_raw)

        orig_name = secure_filename(file.filename) or file.filename
        ext = orig_name.rsplit(".", 1)[1].lower()
        new_name = f"{uuid.uuid4().hex}.{ext}"
        dest = UPLOAD_DIR / new_name
        file.save(dest)
        size = dest.stat().st_size

        db = get_db()
        cur = db.execute(
            "INSERT INTO forms (title, title_norm, description, filename, orig_filename, file_type, size, uploaded_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, normalize(title), description, new_name, orig_name, ext, size, session.get("username")),
        )
        form_id = cur.lastrowid
        upsert_tags_for_form(db, form_id, parse_tags(tags_raw))
        db.commit()

        flash(f"Đã lưu: {title}", "success")
        return redirect(url_for("index"))

    return render_template("upload.html", title="", description="", tags="")


@app.route("/edit/<int:form_id>", methods=["GET", "POST"])
@admin_required
def edit(form_id):
    db = get_db()
    row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
    if not row:
        abort(404)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        tags_raw = request.form.get("tags") or ""

        if not title:
            flash("Thiếu tên biểu mẫu.", "error")
        else:
            db.execute(
                "UPDATE forms SET title = ?, title_norm = ?, description = ? WHERE id = ?",
                (title, normalize(title), description, form_id),
            )
            upsert_tags_for_form(db, form_id, parse_tags(tags_raw))
            db.commit()
            flash("Đã cập nhật.", "success")
            return redirect(url_for("index"))

    tags_str = ", ".join(get_form_tags(db, form_id))
    return render_template("edit.html", form=dict(row), tags=tags_str)


@app.route("/delete/<int:form_id>", methods=["POST"])
@admin_required
def delete(form_id):
    db = get_db()
    row = db.execute("SELECT filename FROM forms WHERE id = ?", (form_id,)).fetchone()
    if not row:
        abort(404)
    # xoá file vật lý
    try:
        (UPLOAD_DIR / row["filename"]).unlink()
    except FileNotFoundError:
        pass
    db.execute("DELETE FROM forms WHERE id = ?", (form_id,))  # form_tags tự cascade
    db.commit()
    flash("Đã xoá.", "success")
    return redirect(url_for("index"))


@app.route("/download/<int:form_id>")
@login_required
def download(form_id):
    db = get_db()
    row = db.execute(
        "SELECT filename, orig_filename FROM forms WHERE id = ?", (form_id,)
    ).fetchone()
    if not row:
        abort(404)
    return send_from_directory(
        UPLOAD_DIR, row["filename"],
        as_attachment=True, download_name=row["orig_filename"],
    )


@app.route("/health")
def health():
    return jsonify({"ok": True, "app": "bieu-mau", "time": datetime.utcnow().isoformat()})


@app.errorhandler(413)
def too_large(e):
    flash(f"File vượt quá giới hạn {config.MAX_CONTENT_LENGTH // 1024 // 1024}MB.", "error")
    return redirect(url_for("upload"))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5053, debug=True)
