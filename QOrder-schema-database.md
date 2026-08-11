# QOrder — Thiết kế Database (PostgreSQL)

Thiết kế theo hướng multi-tenant ngay từ đầu: mọi bảng nghiệp vụ đều gắn `restaurant_id`, dù giai đoạn 1 chỉ có 1 quán.

---

## 1. `restaurants`

Thông tin quán (tenant).

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `slug` | VARCHAR, UNIQUE | dùng trong URL QR, vd `bia-hoi-abc` |
| `name` | VARCHAR | Tên quán |
| `phone` | VARCHAR | |
| `address` | TEXT | |
| `is_active` | BOOLEAN | tạm khoá quán nếu cần (SaaS sau này) |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

---

## 2. `restaurant_settings`

Cấu hình riêng theo quán — tách khỏi `restaurants` để dễ mở rộng key-value mà không phải migrate schema liên tục.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `restaurant_id` | UUID (FK → restaurants) | |
| `default_savory_minutes` | INT | **preset gợi ý** cho admin điền nhanh `prep_time_minutes` món mặn, vd 10 (không dùng ở runtime) |
| `default_light_minutes` | INT | preset gợi ý món nhạt/đồ uống, vd 5 (hoặc 0) |
| `session_timeout_hours` | INT | ngưỡng tự đánh dấu `abandoned` khi bàn không hoạt động, **mặc định 6** (R13.2) |
| `kitchen_screen_requires_pin` | BOOLEAN | bật/tắt yêu cầu PIN cho màn hình bếp, mặc định TRUE (R12.9) |
| `staff_call_cooldown_seconds` | INT | giới hạn tần suất gọi nhân viên, mặc định 60 (R7.4) |
| `timezone` | VARCHAR | vd "Asia/Ho_Chi_Minh" — dùng cho báo cáo/scheduler |
| `logo_url` | VARCHAR, nullable | logo quán, in trên bill / hiển thị menu |
| `currency` | VARCHAR | vd "VND" |
| `bill_footer_note` | TEXT | in ở cuối bill, nullable |
| `report_sheet_id` | VARCHAR | ID Google Sheet dùng để xuất báo cáo, nullable (R9.2) |
| `report_sync_cron` | VARCHAR | lịch đồng bộ báo cáo, mặc định `'0 * * * *'` (mỗi giờ) (R9.1) |
| `updated_at` | TIMESTAMPTZ | |

> **Đã bỏ ở MVP:** `overdue_flash_multiplier` (từng có ở bản đầu). Ngưỡng nhấp nháy dùng ratio cố định (1.0/1.5/2.0 × `prep_time`) ở tầng client, không cấu hình theo quán. Có thể thêm lại ở giai đoạn 2 mà không phá schema.

---

## 3. `users`

Tài khoản nhân viên/chủ quán — gộp staff + admin trong 1 bảng, sẵn sàng tách vai trò sau này (R12.7).

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `restaurant_id` | UUID (FK → restaurants) | gắn tenant (R12.4) |
| `role` | ENUM | `staff`, `admin` (mở rộng `kitchen`, `waiter` sau) |
| `email` | VARCHAR, nullable | cho admin; UNIQUE theo `(restaurant_id, email)` (R12.3) |
| `password_hash` | VARCHAR, nullable | admin (R12.6) |
| `pin_hash` | VARCHAR, nullable | staff — PIN chung của quán (R12.2, R12.6) |
| `display_name` | VARCHAR, nullable | |
| `is_active` | BOOLEAN | |
| `created_at` | TIMESTAMPTZ | |

**CHECK constraint** (tránh dữ liệu rác):
```sql
CHECK (
  (role = 'admin' AND email IS NOT NULL AND password_hash IS NOT NULL)
  OR
  (role = 'staff' AND pin_hash IS NOT NULL)
)
```

Ghi chú: giai đoạn 1 mỗi quán có 1 bản ghi `role='staff'` (PIN chung) + ≥1 bản ghi `role='admin'`.

---

## 4. `tables`

Bàn vật lý trong quán. (Tên chuẩn `tables` theo `design.md`; hợp lệ trong PostgreSQL — sẽ quote nếu cần.)

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `restaurant_id` | UUID (FK → restaurants) | |
| `table_number` | VARCHAR | vd "12", "VIP-1" — số bàn có thể trùng giữa các quán nên không unique toàn cục |
| `qr_token` | VARCHAR, UNIQUE | token ngẫu nhiên riêng, không lộ `id` thật ra QR — QR link dạng `/r/{restaurant_slug}/t/{qr_token}` |
| `is_active` | BOOLEAN | bàn có đang dùng được không (vd đang sửa) |
| `created_at` | TIMESTAMPTZ | |

**Unique constraint**: `(restaurant_id, table_number)`

---

## 5. `table_sessions`

Một "phiên ngồi bàn" — gom tất cả các đợt gọi món của cùng 1 lượt khách vào 1 bill. Đây là khái niệm mấu chốt cho quán bia (khách gọi thêm nhiều lần).

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `restaurant_id` | UUID (FK) | |
| `table_id` | UUID (FK → tables) | |
| `status` | ENUM | `open`, `closed`, `abandoned` (R13.1) — luồng thanh toán 1 bước, **không** có `payment_requested` |
| `opened_at` | TIMESTAMPTZ | thời điểm khách quét QR đầu tiên hoặc NV mở bàn |
| `last_activity_at` | TIMESTAMPTZ | cập nhật khi có order mới / đổi trạng thái / gọi nhân viên — mốc tính auto-abandon (R13.2) |
| `closed_at` | TIMESTAMPTZ | nullable, set khi thanh toán xong |
| `abandoned_at` | TIMESTAMPTZ | nullable, set khi tự đánh dấu `abandoned`; mốc tính hạn 24h khôi phục (R13.5/13.7) |
| `total_amount` | NUMERIC(12,2) | lưu khi `closed`; `abandoned`/`open` để **NULL** (không tính doanh thu — R13.4) |
| `opened_by` | UUID (FK → users), nullable | NULL nếu khách tự mở qua QR; có giá trị nếu nhân viên mở thủ công (R12.2) |

**Ràng buộc "1 session open/bàn" — enforce ở tầng DB (mạnh hơn tầng app):**
```sql
CREATE UNIQUE INDEX uq_one_open_session_per_table
ON table_sessions (table_id) WHERE status = 'open';
```
- Khi khách quét QR: nếu bàn đã có session `open` → dùng lại; nếu chưa → tạo mới. 2 request đồng thời cùng tạo → 1 cái vi phạm index → retry đọc session vừa tạo.

**Đổi `status` phải dùng compare-and-swap** để tránh race giữa checkout thủ công và job auto-abandon:
```sql
-- checkout: UPDATE ... SET status='closed' WHERE id=:id AND status='open' RETURNING *;
-- sweep:    UPDATE ... SET status='abandoned' WHERE id=:id AND status='open' RETURNING *;
```
Bên thắng ghi được; bên thua nhận `RETURNING` rỗng → xử lý mềm.

**Index**: `(table_id, status)`; `(status, last_activity_at)` cho job quét abandoned.

---

## 6. `menu_categories` (tuỳ chọn nhưng nên có)

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `restaurant_id` | UUID (FK) | |
| `name` | VARCHAR | vd "Đồ nhậu", "Đồ uống", "Món chính" |
| `sort_order` | INT | thứ tự hiển thị menu |
| `is_active` | BOOLEAN DEFAULT true | ẩn/hiện cả nhóm khỏi menu (R8.1) |

---

## 7. `menu_items`

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `restaurant_id` | UUID (FK) | |
| `category_id` | UUID (FK → menu_categories), nullable | |
| `name` | VARCHAR | |
| `description` | TEXT | nullable |
| `price` | NUMERIC(12,2) | |
| `prep_time_minutes` | INT, **NOT NULL**, CHECK (≥ 0) | **bắt buộc** (tránh admin quên điền); **`0` = không cần countdown** (vd bia, nước ngọt). Preset mặn/nhạt ở `restaurant_settings` chỉ để điền nhanh khi tạo món (R5.2/R8.1) |
| `is_available` | BOOLEAN DEFAULT true | **còn/hết hàng** — hết thì vẫn hiện kèm nhãn "Hết hàng", khách không đặt được (R3.2) |
| `is_active` | BOOLEAN DEFAULT true | **ẩn/hiện món khỏi menu** — gỡ hẳn món (theo mùa/ngừng bán) mà không xoá dữ liệu, giữ nguyên tham chiếu `order_items.menu_item_id` của đơn cũ (R8.1) |
| `image_url` | VARCHAR, nullable | |
| `sort_order` | INT | thứ tự hiển thị trong nhóm |

---

## 8. `orders`

Một **đợt gọi món** (1 lần khách bấm "gửi đơn"). Nhiều `orders` thuộc về 1 `table_session`.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `restaurant_id` | UUID (FK) | |
| `table_session_id` | UUID (FK → table_sessions) | |
| `created_at` | TIMESTAMPTZ | thời điểm gửi đơn (mốc để tính countdown chung, nhưng countdown thực tế tính theo từng `order_item`) |
| `note` | TEXT, nullable | ghi chú chung cho cả đợt gọi, vd "không cay" |

---

## 9. `order_items`

Từng món trong 1 đợt gọi — đây là bảng trung tâm cho toàn bộ logic tích ✅ / nhấp nháy 🧨.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `restaurant_id` | UUID (FK) | denormalize để lọc/RLS theo tenant (nhất quán ghi chú 5) |
| `order_id` | UUID (FK → orders) | |
| `menu_item_id` | UUID (FK → menu_items) | |
| `name_snapshot` | VARCHAR | **snapshot tên món** tại thời điểm gọi (menu có thể đổi tên sau) |
| `quantity` | INT, CHECK (> 0) | |
| `price_snapshot` | NUMERIC(12,2) | snapshot giá tại thời điểm gọi (giá menu có thể đổi sau) |
| `prep_time_snapshot` | INT, NOT NULL, CHECK (≥ 0) | snapshot từ `menu_items.prep_time_minutes` tại thời điểm gọi (CHECK cùng mức cột nguồn để schema tự bảo vệ; tên khác để không nhầm) |
| `status` | ENUM | `pending`, `cooking` (tuỳ chọn), `ready`, `served`, `cancelled` (R4.1, R11.1) |
| `requested_at` | TIMESTAMPTZ | = thời điểm tạo, mốc bắt đầu đếm countdown |
| `served_at` | TIMESTAMPTZ, nullable | thời điểm bếp tích ✅ (R4.7) |
| `served_by` | UUID (FK → users), nullable | ai tích ✅; NULL nếu bếp chạy chế độ tắt PIN (R12.10) |
| `cancelled_at` | TIMESTAMPTZ, nullable | thời điểm huỷ |
| `cancelled_by` | ENUM, nullable | `customer` / `staff` / `system` (R11.7) |
| `cancel_reason` | VARCHAR, nullable | vd `table_closed` (R6.8), `session_abandoned` (R13.8) |
| `note` | TEXT, nullable | ghi chú riêng cho món này |

**Đổi `status` / huỷ dùng compare-and-swap** (atomic, tránh race giữa 2 nhân viên hoặc huỷ-đúng-lúc-tích):
```sql
UPDATE order_items SET status = :to, served_at = ..., served_by = ...
WHERE id = :id AND status = ANY(:allowed_from) RETURNING *;
```
`RETURNING` rỗng → transition thất bại (có người đổi trước) → trả 409. Lùi trạng thái chỉ cho `served → pending` khi `now - served_at ≤ 120s` (R4.7).

**Cách tính trạng thái nhấp nháy (xử lý ở tầng application/frontend, không lưu DB):**
```
elapsed = now - requested_at
if prep_time_snapshot == 0:
    no_flash                       # món phục vụ ngay (đồ uống) - R5.1
elif status in ('served', 'cancelled'):
    no_flash                       # đã xong hoặc đã huỷ - R5.6
else:
    ratio = elapsed / prep_time_snapshot
    overdue_level = 0 if ratio < 1.0
                    1 if 1.0 <= ratio < 1.5
                    2 if 1.5 <= ratio < 2.0
                    3 if ratio >= 2.0     # nhấp nháy nhanh nhất
    # client map level -> tốc độ nhấp nháy; CHỈ hiển thị ở màn hình bếp (R5.7)
```
→ Không cần cột `overdue_level` trong DB — tính động từ `requested_at` + `prep_time_snapshot` (R5.5). Server chỉ gửi 2 giá trị này qua WebSocket, client tự animate; không ghi DB mỗi giây.

**Index**: `(order_id)`, `(restaurant_id, status)` cho màn hình bếp lọc nhanh các món chưa `served`/`cancelled`.

---

## 10. `staff_calls`

Yêu cầu gọi nhân viên (1 nút "Gọi nhân viên" chung — R7) — tách khỏi luồng món ăn vì không qua bếp. Giữ tối giản đúng phạm vi R7: **không** phân loại `type`.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `restaurant_id` | UUID (FK) | |
| `table_id` | UUID (FK → tables) | dùng để tính cooldown per-bàn (R7.4) |
| `table_session_id` | UUID (FK → table_sessions), NOT NULL | mọi call luôn gắn 1 phiên (nút gọi chỉ hiện sau khi quét QR đã tạo phiên — R2.4) |
| `status` | ENUM | `pending`, `acknowledged` |
| `created_at` | TIMESTAMPTZ | mốc kiểm tra cooldown (R7.4) |
| `acknowledged_at` | TIMESTAMPTZ, nullable | |
| `acknowledged_by` | UUID (FK → users), nullable | nhân viên tiếp nhận (R7.3) |

**Ghi chú hành vi:**
- **Cooldown per-bàn**: từ chối tạo call mới nếu bàn đã có call trong `staff_call_cooldown_seconds` (mặc định 60s) gần nhất — **tính theo bàn, không theo loại** (khớp R7.4 & Property 7).
- **Tạo call cập nhật `table_sessions.last_activity_at = now()`** — gọi nhân viên là hoạt động ngăn auto-abandon (R13.2).
- **Dọn mồ côi**: khi phiên chuyển `closed`/`abandoned`, mọi call còn `pending` của phiên/bàn SHALL được set `acknowledged` (dismiss) để không kẹt trên board bếp.

> Nếu về sau muốn phân loại yêu cầu (thêm đá / xin bill / khác), cần bổ sung requirement mới cho R7 (làm rõ cooldown per-bàn hay per-loại) rồi mới thêm cột `type` — không thêm tuỳ tiện ở tầng schema.

---

## 11. `bills` (tuỳ chọn tách riêng, hoặc gộp vào `table_sessions`)

Nếu muốn giữ lịch sử in bill (in lại, in nháp trước khi thanh toán):

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID (PK) | |
| `table_session_id` | UUID (FK) | |
| `subtotal` | NUMERIC(12,2) | |
| `total` | NUMERIC(12,2) | |
| `printed_at` | TIMESTAMPTZ, nullable | |
| `payment_method` | ENUM, nullable | `cash`, `transfer`, `other` |
| `created_at` | TIMESTAMPTZ | |

*(Giai đoạn MVP có thể bỏ bảng này, tính tổng động từ `table_sessions` + `order_items` khi bấm thanh toán, chỉ thêm khi cần lưu lịch sử in/loại thanh toán.)*

---

## Sơ đồ quan hệ tổng quát

```
restaurants (1) ──< restaurant_settings (1)
restaurants (1) ──< users (N)                  [staff + admin]
restaurants (1) ──< tables (N)
restaurants (1) ──< menu_categories (N) ──< menu_items (N)
restaurants (1) ──< table_sessions (N)

tables (1) ──< table_sessions (N)   [chỉ 1 session "open"/bàn — unique partial index]
table_sessions (1) ──< orders (N)
table_sessions (1) ──< staff_calls (N)
table_sessions (1) ──< bills (N, thường chỉ 1)

orders (1) ──< order_items (N)
menu_items (1) ──< order_items (N)

users (1) ──< order_items (N)        [served_by]
users (1) ──< table_sessions (N)     [opened_by]
users (1) ──< staff_calls (N)        [acknowledged_by]
```

---

## Ghi chú thiết kế quan trọng

1. **Không tính countdown/overdue bằng cron job ghi DB liên tục** — chỉ lưu `requested_at` + `prep_time_snapshot`, để client tự tính real-time. Server chỉ cần bắn 1 sự kiện WebSocket khi có thay đổi trạng thái (món mới, tích ✅), không cần bắn liên tục mỗi giây.
2. **`qr_token` random, không dùng `table_id` trực tiếp** trong URL — tránh khách đoán/sửa URL để xem đơn bàn khác.
3. **Giá món snapshot vào `order_items.price_snapshot`** (kèm `name_snapshot`) — để nếu quán đổi giá/tên menu sau, các đơn cũ không bị tính sai lại.
4. **`prep_time_snapshot` snapshot vào `order_items`** — đề phòng quán đổi cấu hình thời gian chuẩn bị món giữa chừng, không ảnh hưởng đơn đang chạy.
5. Tất cả bảng nghiệp vụ đều có `restaurant_id` **trực tiếp** (kể cả khi có thể suy ra qua quan hệ) — giúp query báo cáo/lọc theo tenant nhanh hơn, không cần join sâu, và là điều kiện bắt buộc để áp dụng **Row-Level Security (RLS)** của Postgres/Supabase sau này khi multi-tenant.

---

## Quyết định đã chốt (từ spec `requirements.md` / `design.md`)

- **Trạng thái `cooking`/`ready`**: giữ trong enum nhưng là **tùy chọn** — bếp có thể tích thẳng `pending → served`. Khách chỉ thấy "chưa ra"/"đã ra"; `cooking`/`ready` chỉ hiện ở màn hình bếp (R4.1/R4.2).
- **`table_sessions.total_amount`**: **lưu cứng khi `closed`**; `open`/`abandoned` để NULL (R6.1/R13.4). Có thể tính động khi hiển thị bill nháp trước lúc đóng.
- **Lưu `served_by` / `cancelled_by` / `acknowledged_by`**: **có** ngay từ MVP (bảng `users` đã có). Khi `kitchen_screen_requires_pin=false`, `served_by=null` (ẩn danh) — R12.10.
- **Auth**: khách ẩn danh qua QR; staff PIN chung của quán; admin tài khoản riêng (R12).
- **Countdown**: `prep_time_minutes` bắt buộc, `0` = không countdown; `overdue_level` tính động, không lưu DB (R5).
- **Concurrency**: đổi trạng thái `order_items` và `table_sessions` dùng compare-and-swap; scheduler dùng Redis lock chống trùng job.

## Còn để mở tới lúc code (không chặn schema)

- **`bills`**: MVP có thể bỏ, tính tổng động từ `order_items` khi thanh toán; chỉ thêm khi cần lưu lịch sử in/loại thanh toán.
- **RLS (Row-Level Security)**: chưa bật ở MVP (cô lập tenant ở tầng app); cân nhắc bật ở giai đoạn 2 làm defense-in-depth — `restaurant_id` đã denormalize sẵn nên không phải đổi schema.
