"""
PNJ Shared Auth — module dùng chung cho các app PNJ (phieu-ck, ctkm, thu-doi, bieu-mau...).

DB path: env `PNJ_AUTH_DB_PATH`, default `/opt/pnj-shared/pnj-auth.db` (VPS).
Local dev: set PNJ_AUTH_DB_PATH trỏ tới file .db trong thư mục app.

Schema:
    users(id, username UNIQUE COLLATE NOCASE, password_hash, full_name,
          role {admin|user}, user_type {staff|member}, created_at, active)

Mỗi app tự quản lý session, chỉ import `authenticate()` / `get_user()`.
"""
import os
import sqlite3
from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = os.environ.get("PNJ_AUTH_DB_PATH", "/opt/pnj-shared/pnj-auth.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema():
    """Tạo bảng users nếu chưa có. Idempotent."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True) if os.path.dirname(DB_PATH) else None
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            user_type TEXT NOT NULL DEFAULT 'staff',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()


def authenticate(username, password):
    """Return user dict nếu đúng, None nếu sai. Username case-insensitive."""
    if not username or not password:
        return None
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND active = 1",
        (username.strip(),),
    ).fetchone()
    conn.close()
    if row and check_password_hash(row["password_hash"], password):
        return dict(row)
    return None


def get_user(user_id):
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM users WHERE id = ? AND active = 1", (user_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_username(username):
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND active = 1",
        (username.strip(),),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(username, password, full_name=None, role="user", user_type="staff"):
    conn = _conn()
    conn.execute(
        "INSERT INTO users (username, password_hash, full_name, role, user_type) VALUES (?, ?, ?, ?, ?)",
        (username.strip(), generate_password_hash(password), full_name, role, user_type),
    )
    conn.commit()
    conn.close()


def upsert_user(username, password, full_name=None, role="user", user_type="staff"):
    """Insert nếu chưa có, update password/metadata nếu đã có. Dùng để seed hoặc reset."""
    conn = _conn()
    existing = conn.execute(
        "SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username.strip(),)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE users SET password_hash=?, full_name=?, role=?, user_type=?, active=1 WHERE id=?",
            (generate_password_hash(password), full_name, role, user_type, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO users (username, password_hash, full_name, role, user_type) VALUES (?, ?, ?, ?, ?)",
            (username.strip(), generate_password_hash(password), full_name, role, user_type),
        )
    conn.commit()
    conn.close()


def set_password(username, new_password):
    conn = _conn()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = ? COLLATE NOCASE",
        (generate_password_hash(new_password), username.strip()),
    )
    conn.commit()
    conn.close()


def list_users():
    conn = _conn()
    rows = conn.execute(
        "SELECT id, username, full_name, role, user_type, active, created_at FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
