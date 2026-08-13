# QOrder — Hướng dẫn chạy project (Windows / PowerShell)

Backend FastAPI + PostgreSQL + Redis + MinIO, frontend React (Vite). Tài liệu này
đã được chạy thử thực tế trên máy Windows: `docker compose` → `alembic` → `seed` →
`uvicorn` + `npm run dev`, và kiểm chứng vòng realtime (gửi order → nhận event
`order.created` qua WebSocket).

---

## 1. Yêu cầu môi trường

| Thành phần | Phiên bản đã test |
|---|---|
| Python | 3.12.5 |
| Node.js / npm | 24.19.0 / 12.0.2 |
| Docker Desktop | 29.6.1 (compose v5.3.0), daemon phải đang chạy |

### Lưu ý về Python trên Windows

Lệnh `python` trong PATH thường là **stub của Microsoft Store** — gọi vào sẽ mở
Store chứ không chạy Python. Python thật nằm ở:

```
%LOCALAPPDATA%\Programs\Python\Python312\python.exe
```

Vì vậy lần tạo virtualenv phải gọi bằng đường dẫn đầy đủ (xem bước 2.2). Sau khi
activate venv thì `python` trỏ đúng vào venv, dùng bình thường.

---

## 2. Chạy lần đầu

### 2.1. Khởi động PostgreSQL + Redis + MinIO

```powershell
cd c:\Users\luucu\1.PTIT\goi-mon
docker compose up -d
```

Kiểm tra:

```powershell
docker ps --format "{{.Names}}`t{{.Status}}"
# qorder-redis      Up ... (healthy)
# qorder-postgres   Up ... (healthy)
# qorder-minio      Up ... (healthy)
```

### 2.2. Tạo virtualenv & cài dependencies

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Nếu PowerShell chặn script activate:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2.3. Tạo schema & dữ liệu mẫu

```powershell
alembic upgrade head
python -m qorder_api.seed
```

`alembic upgrade head` tạo 10 bảng + 5 enum + các constraint/index (gồm unique
partial index `uq_one_open_session_per_table`).

`seed` là idempotent — chạy lại lần nữa sẽ báo `Seed skipped` chứ không tạo trùng.
Kết quả mong đợi:

```
Seed complete:
  restaurant slug = bia-hoi-demo
  admin login     = admin@qorder.local / admin1234
  staff PIN       = 1234
  tables          = 1, 2, VIP-1
  menu items      = 4 (incl. 2 drinks with prep_time_minutes=0)
```

### 2.4. Cài package frontend

```powershell
cd frontend
npm install
cd ..
```

---

## 3. Chạy hàng ngày

Cần **2 terminal** (thêm terminal 0 nếu Docker chưa chạy).

**Terminal A — backend**

```powershell
cd c:\Users\luucu\1.PTIT\goi-mon
.\.venv\Scripts\Activate.ps1
uvicorn qorder_api.main:app --reload --port 8000
```

Chờ tới dòng `Application startup complete.`

**Terminal B — frontend**

```powershell
cd c:\Users\luucu\1.PTIT\goi-mon\frontend
npm run dev
```

Chờ tới dòng `Local: http://localhost:5173/`

---

## 4. Truy cập

Luôn mở app qua **port 5173** (Vite), không phải 8000 — xem mục 5 để hiểu lý do.

| Màn hình | URL |
|---|---|
| Khách (quét QR) | `http://localhost:5173/bia-hoi-demo/t/{qr_token}` |
| Bếp | http://localhost:5173/bia-hoi-demo/kitchen |
| Admin | http://localhost:5173/admin/menu |
| API docs (Swagger) | http://localhost:8000/docs |
| Healthcheck | http://localhost:8000/health |
| MinIO Console | http://localhost:9001 (login `minioadmin` / `minioadmin`) |

### Tài khoản (từ seed)

| Vai trò | Thông tin |
|---|---|
| Restaurant slug | `bia-hoi-demo` |
| Admin | `admin@qorder.local` / `admin1234` |
| Staff (PIN chung) | `1234` |

### Lấy `qr_token` của từng bàn

URL của khách cần `qr_token` (token random, không phải số bàn):

```powershell
docker exec qorder-postgres psql -U qorder -d qorder -c "SELECT table_number, qr_token FROM tables ORDER BY table_number"
```

Rồi ghép: `http://localhost:5173/bia-hoi-demo/t/<qr_token>`

---

## 5. Cấu hình môi trường

**Không cần tạo file `.env` nào để chạy local.** `qorder_api/config.py` đã có
default khớp sẵn với `docker-compose.yml`:

```
DATABASE_URL = postgresql+asyncpg://qorder:qorder@localhost:5432/qorder
REDIS_URL    = redis://localhost:6379/0
```

Chỉ tạo `.env` ở root khi cần đổi `JWT_SECRET`, trỏ DB khác, hoặc cấu hình máy in
/ Google Sheets. Tham khảo `.env.example`.

### ⚠️ Đừng copy `frontend/.env.example`

File đó set `VITE_API_BASE_URL=http://localhost:8000`, khiến frontend gọi thẳng
cross-origin sang port 8000. Backend (`qorder_api/main.py`) **chưa mount
`CORSMiddleware`**, nên browser sẽ block toàn bộ request.

Để trống biến này (không có file `frontend/.env`) thì mọi request đi qua proxy của
Vite dev server → same-origin → chạy tốt. Các prefix được proxy sang `:8000` khai
báo trong `frontend/vite.config.ts`: `/t`, `/auth`, `/admin/*`, `/tables`,
`/kitchen`, và `/ws` (WebSocket, có `ws: true`).

> Khi deploy production sẽ phải xử lý khác: hoặc mount `CORSMiddleware` ở backend,
> hoặc đặt reverse proxy (nginx/Caddy) phía trước cho cả API và static build.

---

## 5b. MinIO — lưu trữ ảnh QR (S3-compatible)

QR code của mỗi bàn được render thành PNG và upload lên **MinIO** (S3-compatible
object storage). Frontend hiển thị ảnh qua URL public — không cần token, `<img>` và
`<a download>` hoạt động bình thường.

### Thông tin kết nối MinIO

| | Giá trị |
|---|---|
| S3 API endpoint | http://localhost:9000 |
| Web Console | http://localhost:9001 |
| Access Key | `minioadmin` |
| Secret Key | `minioadmin` |
| Bucket | `qorder-assets` (tự tạo khi seed/tạo bàn lần đầu) |

### Cách hoạt động

- Khi chạy `python -m qorder_api.seed` hoặc admin tạo bàn / bấm "🔄 QR mới",
  backend render QR PNG → upload lên MinIO tại key `qr/{table_id}.png`.
- Bucket có **public-read policy** — browser fetch trực tiếp qua
  `http://localhost:9000/qorder-assets/qr/{table_id}.png` mà không cần auth.
- URL được lưu vào cột `tables.qr_image_url` trong PostgreSQL.
- Frontend admin đọc `qr_image_url` từ API response để hiển thị và download.

### Cấu hình (trong `.env` hoặc biến môi trường)

```env
S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=qorder-assets
S3_PUBLIC_URL=http://localhost:9000
```

Mặc định trong `config.py` đã khớp với `docker-compose.yml`, không cần tạo `.env`
khi chạy local. Khi deploy production, đổi sang AWS S3 / Cloudflare R2 chỉ cần thay
các biến trên — code không đổi (boto3 tương thích mọi S3-compatible endpoint).

### Xem file trực tiếp trong MinIO Console

Mở http://localhost:9001 → login `minioadmin` / `minioadmin` → bucket
`qorder-assets` → folder `qr/` → thấy các file PNG.

### Test QR image accessible

```powershell
$url = (docker exec qorder-postgres psql -U qorder -d qorder -t -A -c "SELECT qr_image_url FROM tables WHERE table_number='1'").Trim()
curl.exe -s -o NUL -w "HTTP %{http_code}, size=%{size_download} bytes`n" $url
# → HTTP 200, size=892 bytes
```

---

## 6. Kiểm tra nhanh hệ thống có chạy đúng

```powershell
# Backend sống
curl.exe -s http://localhost:8000/health
# → {"status":"ok"}

# Proxy Vite → backend hoạt động
$tok = (docker exec qorder-postgres psql -U qorder -d qorder -t -A -c "SELECT qr_token FROM tables WHERE table_number='1'").Trim()
curl.exe -s -o NUL -w "%{http_code}`n" "http://localhost:5173/t/$tok"
# → 200

# Đăng nhập staff (xác nhận hash PIN đúng)
curl.exe -s -o NUL -w "%{http_code}`n" -X POST "http://localhost:5173/auth/staff/login" `
  -H "Content-Type: application/json" `
  -d '{\"restaurant_slug\":\"bia-hoi-demo\",\"pin\":\"1234\"}'
# → 200
```

Kiểm tra realtime (WebSocket qua proxy):

```powershell
$env:TOK = (docker exec qorder-postgres psql -U qorder -d qorder -t -A -c "SELECT qr_token FROM tables WHERE table_number='1'").Trim()
node -e "const ws=new WebSocket('ws://localhost:5173/ws/t/'+process.env.TOK); const t=setTimeout(()=>{console.log('TIMEOUT');process.exit(1)},8000); ws.onopen=()=>{console.log('WS OPEN -> OK');clearTimeout(t);ws.close();process.exit(0)}; ws.onerror=()=>{console.log('WS ERROR');process.exit(1)};"
# → WS OPEN -> OK
```

Cách xem trực quan nhất: mở màn khách và màn bếp cạnh nhau, gọi 1 món ở màn khách
→ card phải hiện ngay trên màn bếp mà không cần refresh.

---

## 7. Lệnh quản lý

```powershell
docker compose logs -f postgres     # xem log DB
docker compose logs -f redis
docker compose logs -f minio        # xem log MinIO
docker compose stop                 # tạm dừng
docker compose down                 # xoá container, GIỮ dữ liệu (volume)
docker compose down -v              # xoá cả dữ liệu → phải chạy lại 2.3
```

Truy cập DB trực tiếp:

```powershell
docker exec -it qorder-postgres psql -U qorder -d qorder
```

Dừng backend / frontend: `Ctrl+C` ở terminal tương ứng.

---

## 8. Xử lý sự cố

| Triệu chứng | Nguyên nhân & cách xử lý |
|---|---|
| `python` mở Microsoft Store | Stub của Store che PATH. Dùng full path ở bước 2.2, hoặc activate venv trước. |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| Backend lỗi kết nối DB khi khởi động | Container chưa `healthy`. Chờ vài giây rồi kiểm tra `docker ps`. |
| Frontend trắng trang / mọi API fail, console báo CORS | Đang tồn tại `frontend/.env`. Xoá nó đi rồi restart `npm run dev`. |
| Realtime không cập nhật, món mới không tự hiện | Kiểm tra `frontend/vite.config.ts` còn entry `"/ws"` với `ws: true`. Thiếu là WS không được proxy. |
| `seed` lỗi `password cannot be longer than 72 bytes` | Xung đột `passlib` 1.7.4 với `bcrypt >= 5`. `seed.py` phải hash qua `qorder_api.auth.passwords`, không dùng `passlib.CryptContext`. |
| Đăng nhập trả 401 dù PIN/password đúng | DB chưa seed, hoặc seed bằng đường hash khác với đường verify. Chạy lại `python -m qorder_api.seed` trên DB sạch. |
| Port 5432 / 6379 / 8000 / 5173 đã bị dùng | Tìm process chiếm port bằng `netstat -ano \| findstr :5432`, hoặc đổi port mapping trong `docker-compose.yml`. |
| Ảnh QR không hiện (trước khi seed/tạo bàn lần đầu) | MinIO bucket chưa tồn tại. Chạy `python -m qorder_api.seed` hoặc tạo bàn qua admin — bucket tự tạo. |
| Ảnh QR trả 403 Forbidden | Bucket policy chưa set public-read. Xoá bucket trong MinIO Console rồi chạy lại seed hoặc regenerate QR (tự set lại policy). |

---

## 8b. Test quét QR bằng điện thoại (qua mạng LAN)

Mặc định QR encode URL `http://localhost:3000/...` — điện thoại không truy cập được
vì `localhost` trỏ về chính nó. Để test bằng điện thoại thật:

**1. Điện thoại và máy tính phải cùng mạng WiFi.**

**2. Tìm IP LAN của máy tính:**

```powershell
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -eq 'Dhcp' -or $_.PrefixOrigin -eq 'Manual' } | Select-Object -First 1).IPAddress
# → ví dụ: 192.168.1.100
```

**3. Tạo file `.env` ở root project** (nếu chưa có):

```env
BASE_URL=http://192.168.1.100:5173
```

(thay IP thật của bạn)

**4. Chạy Vite với `--host`** để lắng nghe trên LAN:

```powershell
cd frontend
npx vite --host
# Output: Network: http://192.168.1.100:5173/
```

**5. Regenerate QR** để encode URL mới (chứa IP LAN thay vì localhost):

- Vào Admin → bấm "🔄 QR mới" cho từng bàn, hoặc:

```powershell
# Xoá data cũ và seed lại
docker compose down -v
docker compose up -d
.\.venv\Scripts\Activate.ps1
alembic upgrade head
python -m qorder_api.seed
```

**6. Quét QR bằng điện thoại** — URL sẽ là `http://192.168.1.100:5173/bia-hoi-demo/t/...`

> Khi deploy lên server thật, `BASE_URL` sẽ là domain public và QR hoạt động ngay
> mà không cần thủ thuật này.

---

## 9. Tính năng chưa hoàn thiện (không phải lỗi cài đặt)

Các mục dưới đây sẽ lỗi khi click thử — đã biết, thuộc phần code còn thiếu:

- **Admin → Phiên abandoned**: backend chưa có `GET /admin/sessions`.
- **Admin → Báo cáo**: backend chưa có `POST /admin/reports/sync`.
- **Bếp → panel Thanh toán** luôn hiện "Không có bàn nào": `GET /kitchen/board`
  chưa trả `table_session_id`.
- **Bếp → WS reconnect thất bại vĩnh viễn** sau khi mất kết nối: ticket WS là
  one-shot (`GETDEL`) nhưng client tái dùng ticket cũ. Bấm nút 🔄 để tải lại.
- **Chế độ tắt PIN màn bếp** (`kitchen_screen_requires_pin=false`) chưa dùng được:
  `/kitchen/*` vẫn bắt buộc JWT ở cấp router.
- **In bill**: `PrintingService` đã viết nhưng chưa được endpoint nào gọi, và
  `python-escpos` / `weasyprint` không nằm trong `requirements.txt`.
