# Deploy bieu-mau-app

## Lần đầu (trên VPS)

```bash
# 1. Clone
cd /opt
git clone https://github.com/2026millionaire/bieu-mau-app.git
cd bieu-mau-app
git config --global --add safe.directory /opt/bieu-mau-app

# 2. Venv + install
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. Shared auth DB (nếu chưa có)
# Giả định /opt/pnj-shared/pnj-auth.db đã được tạo từ project shared.

# 4. Systemd
cp deploy/bieu-mau-app.service /etc/systemd/system/
# ⚠️ Sửa SECRET_KEY trong file này trước khi enable
systemctl daemon-reload
systemctl enable --now bieu-mau-app
systemctl status bieu-mau-app

# 5. Nginx
# Edit /etc/nginx/sites-enabled/phieuck
# Thêm block trong deploy/nginx-location.conf — ở ROOT domain (không phải dưới /bk/)
nginx -t && systemctl reload nginx

# 6. Test
curl https://dangkhoa.io.vn/bieu-mau/health
```

## Update

```bash
cd /opt/bieu-mau-app
git pull
systemctl restart bieu-mau-app
```
