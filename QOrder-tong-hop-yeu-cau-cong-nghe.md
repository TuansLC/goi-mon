# QOrder — Tổng hợp yêu cầu & công nghệ

## 1. Bối cảnh & mục tiêu

- **Giai đoạn 1**: Xây dựng, vận hành thử cho **1 quán ăn**.
- **Giai đoạn 2 (định hướng)**: Phát triển thành **sản phẩm SaaS multi-tenant** cho nhiều quán sử dụng.
- Vì vậy, kiến trúc và schema cần thiết kế **multi-tenant ngay từ MVP**, dù chưa cần dùng tới ở giai đoạn 1.

## 2. Yêu cầu chức năng (functional requirements)

| # | Yêu cầu | Ghi chú |
|---|---|---|
| 1 | Quản lý dữ liệu quán (menu, bàn, đơn hàng) | Ban đầu định dùng Google Sheets làm DB chính — đã điều chỉnh (xem mục 4) |
| 2 | QR gắn theo từng bàn, dẫn tới danh sách món ăn | QR nên encode cả `restaurant_id` + `table_id` để hỗ trợ multi-tenant |
| 3 | Đánh dấu món đã ra: tích ✅ | Trạng thái món: `pending → cooking → ready → served` |
| 4 | Món chưa ra thì hiển thị nhấp nháy 🧨 | Cảnh báo trực quan cho bếp/nhân viên |
| 5 | Countdown ngầm theo loại món: 10 phút/món mặn, 5 phút/món nhạt | Nếu quá thời gian mà chưa tích ✅ → tăng tốc độ nhấp nháy (mức độ khẩn cấp tăng dần, có thể xử lý bằng flag `overdue_level` thay vì đổi state) |
| 6 | Nút thanh toán → đóng bàn, in bill (nếu có máy in) | Cần hỗ trợ cả in nhiệt và fallback PDF |

## 3. Yêu cầu phi chức năng (non-functional)

- **Real-time**: Trạng thái món và countdown phải cập nhật gần như tức thời giữa màn hình bếp và màn hình khách.
- **Đa người dùng đồng thời**: Nhiều bàn, nhiều món được tích ✅ cùng lúc — cần tránh race condition.
- **Multi-tenant sẵn sàng**: Mọi bảng dữ liệu đều gắn `restaurant_id`, dù hiện chỉ phục vụ 1 quán.
- **Dễ vận hành cho quán nhỏ**: Chi phí hạ tầng thấp ở giai đoạn đầu, có thể scale dần.
- **Báo cáo cho chủ quán**: Cần xuất được dữ liệu dễ xem (không bắt buộc real-time).

## 4. Quyết định kiến trúc quan trọng: vai trò của Google Sheets

**Ban đầu**: dự định dùng Google Sheets làm database chính.

**Sau khi phân tích, điều chỉnh lại:**

- ❌ **Không** dùng Sheets làm live database (trạng thái món, countdown, tích ✅), vì:
  - Giới hạn rate limit của Google Sheets API (~60-100 request/phút/user) không đáp ứng được tần suất cập nhật real-time.
  - Độ trễ đọc/ghi cao (vài trăm ms – vài giây), không phù hợp hiệu ứng nhấp nháy mượt.
  - Dễ xảy ra race condition khi nhiều thao tác ghi đồng thời.
  - Không scale được khi mở rộng nhiều quán cùng lúc.
- ✅ **Vẫn giữ vai trò phụ**:
  - Đồng bộ định kỳ để **xuất báo cáo** (doanh thu, món bán chạy...) cho chủ quán dễ xem.
  - Có thể tạm dùng để quản lý menu ở giai đoạn rất sớm, trước khi có giao diện admin.

## 5. Công nghệ đề xuất

| Layer | Công nghệ | Lý do chính |
|---|---|---|
| Backend | **FastAPI** (Python) + SQLAlchemy (async) | Async tốt, tự sinh docs, hỗ trợ WebSocket |
| Database chính | **PostgreSQL** (Supabase ở giai đoạn đầu) | Chịu tải tốt, hỗ trợ concurrent writes, JSON field cho settings linh hoạt theo quán |
| Realtime | **WebSocket** (FastAPI) / Redis Pub-Sub khi scale | Đẩy trạng thái món/countdown tức thời, tránh polling liên tục |
| Cache / trạng thái tạm | **Redis** | Lưu trạng thái countdown đang chạy, session bàn active |
| Frontend khách (quét QR) | **React (Vite)** hoặc HTMX + Jinja2 | Web nhẹ, không cần cài app |
| Frontend bếp | **React SPA** | Chạy trên tablet/màn hình cố định |
| Styling | **TailwindCSS** | Responsive nhanh cho cả mobile và tablet |
| QR code | Thư viện `qrcode` (Python) | Encode `restaurant_slug` + `table_id` |
| In bill | `python-escpos` (máy in nhiệt) / `reportlab` hoặc `weasyprint` (PDF fallback) | Phù hợp máy in phổ biến ở VN |
| Đồng bộ báo cáo | `gspread` + Google Service Account | Chỉ dùng cho báo cáo định kỳ, không phải live DB |
| Deploy giai đoạn 1 | **Railway** hoặc **Render** | Có Postgres + Redis addon sẵn, chi phí thấp |
| Deploy khi mở rộng | Docker hoá (Dockerfile + docker-compose) → VPS (DigitalOcean/Vultr) | Kiểm soát chi phí khi scale nhiều quán |

## 6. Nguyên tắc thiết kế cần tuân thủ ngay từ MVP

1. `restaurant_id` là khóa ngoại xuyên suốt mọi bảng dữ liệu.
2. Cấu hình theo quán (thời gian countdown, tên, logo...) lưu trong bảng `restaurant_settings`, không hardcode trong code.
3. QR code encode cả `restaurant_id` và `table_id`.
4. Mỗi quán có mapping riêng tới Google Sheet phục vụ báo cáo (dù hiện tại chỉ có 1 dòng mapping).
5. Naming convention: repo dạng kebab-case (`qorder-kitchen`), module Python dạng snake_case (`qorder_api/models.py`).

## 7. Việc còn cần làm rõ / bước tiếp theo

- Thiết kế schema DB chi tiết: `restaurants`, `tables`, `menu_items`, `orders`, `order_items`, `restaurant_settings`.
- Thiết kế luồng trạng thái món ăn và cơ chế tính mức độ khẩn cấp (`overdue_level`) cho hiệu ứng nhấp nháy.
- Dựng khung project (folder structure + FastAPI skeleton).
