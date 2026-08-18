# QOrder — Hướng dẫn chạy project

Backend FastAPI + PostgreSQL + Redis + MinIO, frontend React (Vite).

---

## 1. Yêu cầu

| Thành phần | Phiên bản |
|---|---|
| Python | 3.12+ |
| Node.js / npm | 20+ / 10+ |
| Docker Desktop | daemon đang chạy |

---

## 2. Chạy lần đầu

### 2.1. Khởi động infrastructure

```powershell
docker compose up -d
```

Kiểm tra cả 3 container healthy:

```powershell
docker ps --format "{{.Names}}`t{{.Status}}"
# qorder-postgres   Up (healthy)
# qorder-redis      Up (healthy)
# qorder-minio      Up (healthy)
```

### 2.2. Backend

```powershell
# Tạo venv (lần đầu)
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv

# Activate
.\.venv\Scripts\Activate.ps1

# Cài dependencies
pip install -r requirements.txt

# Migration + seed data
alembic upgrade head
python -m qorder_api.seed
```

> Nếu PowerShell chặn activate: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

Seed output mong đợi:

```
Seed complete:
  restaurant slug = bia-hoi-demo
  admin login     = admin@qorder.local / admin1234
  staff PIN       = 1234
  tables          = 1, 2, VIP-1
  menu items      = 4 (incl. 2 drinks with prep_time_minutes=0)
```

### 2.3. Frontend

```powershell
cd frontend
npm install
cd ..
```

---

## 3. Chạy hàng ngày

**Terminal A — backend:**

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn qorder_api.main:app --reload --port 8000
```

**Terminal B — frontend:**

```powershell
cd frontend
npm run dev
```

---

## 4. Truy cập

Luôn mở qua **port 5173** (Vite proxy). Không dùng 8000 trực tiếp.

| Màn hình | URL |
|---|---|
| Khách (quét QR) | `http://localhost:5173/bia-hoi-demo/t/{qr_token}` |
| Bếp | http://localhost:5173/bia-hoi-demo/kitchen |
| Admin | http://localhost:5173/admin/menu |
| Swagger API | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 (`minioadmin` / `minioadmin`) |

### Tài khoản

| Vai trò | Thông tin |
|---|---|
| Admin | `admin@qorder.local` / `admin1234` |
| Staff PIN | `1234` |
| Restaurant slug | `bia-hoi-demo` |

### Lấy qr_token

```powershell
docker exec qorder-postgres psql -U qorder -d qorder -c "SELECT table_number, qr_token FROM tables ORDER BY table_number"
```

---

## 5. Cấu hình

**Không cần tạo `.env` để chạy local.** `config.py` có default khớp `docker-compose.yml`:

```
DATABASE_URL = postgresql+asyncpg://qorder:qorder@localhost:5432/qorder
REDIS_URL    = redis://localhost:6379/0
S3_ENDPOINT_URL = http://localhost:9000
S3_PUBLIC_URL   = http://localhost:9000
```

### ⚠️ Không tạo `frontend/.env`

File đó gây CORS. Để trống → request đi qua Vite proxy → không lỗi.

---

## 6. MinIO (S3-compatible storage)

Dùng cho: ảnh QR bàn, ảnh món ăn (thumbnail 400×400 + large 1000px, WebP).

| | Giá trị |
|---|---|
| S3 API | http://localhost:9000 |
| Console | http://localhost:9001 |
| Bucket | `qorder-assets` (tự tạo lần đầu upload) |

Ảnh được set public-read policy → browser fetch trực tiếp, không cần auth.

---

## 7. Test nhanh

```powershell
# Health
curl.exe -s http://localhost:8000/health

# Đăng nhập staff
curl.exe -s -o NUL -w "%{http_code}`n" -X POST "http://localhost:5173/auth/staff/login" `
  -H "Content-Type: application/json" `
  -d '{\"restaurant_slug\":\"bia-hoi-demo\",\"pin\":\"1234\"}'
# → 200
```

Test realtime: mở màn khách + màn bếp cạnh nhau, gọi 1 món → card hiện ngay trên bếp.

---

## 8. Test bằng điện thoại (LAN)

1. Cùng WiFi
2. Tìm IP: `(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -eq 'Dhcp' } | Select-Object -First 1).IPAddress`
3. Tạo `.env` ở root:
   ```env
   BASE_URL=http://192.168.x.x:5173
   S3_PUBLIC_URL=http://192.168.x.x:9000
   ```
4. Chạy Vite với `--host`: `cd frontend && npx vite --host`
5. Regenerate QR (Admin → 🔄 QR mới) để encode URL mới
6. Quét QR bằng điện thoại

---

## 9. Lệnh quản lý

```powershell
docker compose stop           # tạm dừng
docker compose down           # xoá container, GIỮ data
docker compose down -v        # xoá cả data → chạy lại migration + seed
docker exec -it qorder-postgres psql -U qorder -d qorder  # truy cập DB
```

---

## 10. Xử lý sự cố

| Vấn đề | Fix |
|---|---|
| `python` mở Microsoft Store | Dùng full path hoặc activate venv trước |
| Frontend trắng / CORS | Xoá `frontend/.env`, restart Vite |
| Backend 500 "column does not exist" | Chưa chạy `alembic upgrade head` |
| Ảnh không hiện | MinIO chưa chạy, hoặc `S3_PUBLIC_URL` sai khi test qua LAN |
| Upload ảnh 500 | Restart backend (bucket cache bị stale sau docker down) |
| Realtime không cập nhật | Kiểm tra `vite.config.ts` có entry `/ws` với `ws: true` |
| Đăng nhập 401 dù đúng PIN | DB chưa seed hoặc seed bằng lib hash khác. Reset: `docker compose down -v` → chạy lại từ đầu |

---

## 11. Tính năng chưa hoàn thiện

- **Admin → Phiên abandoned**: backend chưa có `GET /admin/sessions`
- **Admin → Báo cáo**: chưa có `POST /admin/reports/sync`
- **Bếp → Thanh toán**: `GET /kitchen/board` chưa trả `table_session_id`
- **Bếp → WS reconnect**: ticket one-shot, mất kết nối phải reload trang
- **Tắt PIN màn bếp**: router vẫn bắt JWT dù `kitchen_screen_requires_pin=false`
- **In bill**: `PrintingService` viết rồi nhưng chưa nối endpoint
