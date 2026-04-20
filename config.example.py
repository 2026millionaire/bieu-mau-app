"""Copy thành config.py và chỉnh theo môi trường."""
import os

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-local-bieu-mau-change-in-prod")

# Path DB auth shared (set bởi systemd Environment trên VPS)
# Mặc định ở VPS: /opt/pnj-shared/pnj-auth.db
# Local dev: set PNJ_AUTH_DB_PATH trỏ tới file test
PNJ_AUTH_DB_PATH = os.environ.get("PNJ_AUTH_DB_PATH", "/opt/pnj-shared/pnj-auth.db")

# File upload
MAX_CONTENT_LENGTH = 3 * 1024 * 1024  # 3 MB
ALLOWED_EXTENSIONS = {"docx", "xlsx", "pdf"}
UPLOAD_FOLDER_NAME = "uploads"  # relative tới thư mục app
