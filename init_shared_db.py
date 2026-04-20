"""
Seed shared auth DB — chạy 1 lần trên VPS để tạo DB + user ban đầu.
Idempotent: chạy lại sẽ upsert (reset password + metadata).

Usage:
    PNJ_AUTH_DB_PATH=/opt/pnj-shared/pnj-auth.db python3 init_shared_db.py
"""
import os
import sys

# Cho phép chạy từ bất cứ đâu — thêm thư mục chứa file này vào sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import shared_auth

SEED_USERS = [
    # (username, password, full_name, role, user_type)
    ("admin", "xinlayEOFFICE#002", "Admin", "admin", "staff"),
    ("sp1305", "Pnj@1305", "SP 1305", "user", "staff"),
]


def main():
    print(f"DB path: {shared_auth.DB_PATH}")
    shared_auth.init_schema()
    print("Schema OK.")

    for username, password, full_name, role, user_type in SEED_USERS:
        shared_auth.upsert_user(username, password, full_name, role, user_type)
        print(f"  + upserted: {username} ({role}/{user_type})")

    print("\nCurrent users:")
    for u in shared_auth.list_users():
        print(f"  {u['id']:>3}  {u['username']:<12}  role={u['role']:<6} type={u['user_type']:<6} active={u['active']}")


if __name__ == "__main__":
    main()
