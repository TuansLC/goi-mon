# Requirements Document

## Introduction

QOrder là hệ thống đặt món qua QR code dành cho quán bia/quán ăn. Khách quét QR gắn tại bàn để xem menu và gọi món; bếp và nhân viên theo dõi trạng thái món theo thời gian thực với hiệu ứng cảnh báo (nhấp nháy) và countdown ngầm; nhân viên đóng bàn và in bill khi thanh toán.

Giai đoạn 1 phục vụ **1 quán**, nhưng kiến trúc và dữ liệu được thiết kế **multi-tenant** ngay từ đầu để mở rộng thành SaaS ở giai đoạn 2. PostgreSQL là database chính; Google Sheets chỉ đóng vai trò xuất báo cáo định kỳ (không phải live DB).

Tài liệu nguồn: `QOrder-tong-hop-yeu-cau-cong-nghe.md`.

## Glossary

- **Restaurant (quán)**: một tenant trong hệ thống.
- **Table (bàn)**: bàn vật lý trong quán, gắn với 1 QR code.
- **`qr_token`**: chuỗi ngẫu nhiên định danh bàn trên QR/URL, thay cho `table_id` thật để tránh lộ và đoán bàn khác; có thể sinh lại để thu hồi QR cũ.
- **Table session (phiên bàn)**: một lượt khách ngồi từ lúc mở bàn tới lúc thanh toán; gom nhiều đợt gọi món vào chung 1 bill.
- **Order (đợt gọi)**: một lần khách gửi giỏ hàng; một phiên bàn có nhiều order.
- **Order item (món trong đợt gọi)**: từng dòng món, có trạng thái riêng.
- **Món mặn / món nhạt**: gợi ý phân loại chỉ dùng ở màn hình admin để điền nhanh `prep_time_minutes`; **không** phải field runtime.
- **`prep_time_minutes`**: thời gian chuẩn bị dự kiến của một món (phút), bắt buộc cho mỗi món, là nguồn duy nhất để tính countdown.
- **Trạng thái nội bộ bếp**: `cooking`, `ready` là trạng thái chỉ hiển thị cho nhân viên; khách chỉ thấy 2 mức "chưa ra" / "đã ra".
- **`cancelled`**: trạng thái kết thúc của một món bị huỷ, tách khỏi luồng `pending → cooking → ready → served`.
- **Staff / Admin**: nhân viên (bếp/phục vụ) đăng nhập bằng PIN chung của quán; admin (chủ quán) có tài khoản riêng. Khách hoàn toàn ẩn danh qua QR.

## Requirements

### Requirement 1: Quản lý quán & cấu hình multi-tenant

**User Story:** Là chủ hệ thống, tôi muốn mọi dữ liệu gắn với một `restaurant_id` và cấu hình theo từng quán được lưu tách biệt, để có thể mở rộng nhiều quán mà không cần sửa code.

#### Acceptance Criteria

1. WHEN một bản ghi dữ liệu (bàn, menu, order, session) được tạo THEN hệ thống SHALL gắn `restaurant_id` cho bản ghi đó.
2. WHEN truy vấn dữ liệu của một quán THEN hệ thống SHALL chỉ trả về bản ghi thuộc `restaurant_id` tương ứng.
3. WHERE cấu hình theo quán (thời gian countdown món mặn/nhạt, tên quán, logo, đơn vị tiền tệ) được yêu cầu THE hệ thống SHALL đọc từ bảng `restaurant_settings` thay vì hardcode.
4. IF một `restaurant_id` không tồn tại hoặc bị vô hiệu hóa THEN hệ thống SHALL từ chối truy cập và trả về lỗi rõ ràng.
5. THE hệ thống SHALL định danh mỗi quán bằng một `slug` duy nhất dùng trong URL và QR code.

### Requirement 2: QR code theo bàn

**User Story:** Là khách hàng, tôi muốn quét QR tại bàn và thấy ngay menu của đúng quán và đúng bàn của mình, để gọi món mà không cần cài app.

#### Acceptance Criteria

1. THE hệ thống SHALL sinh QR code cho mỗi bàn encode `restaurant_slug` và một `qr_token` ngẫu nhiên (không lộ `table_id` thật ra URL) để tránh khách đoán/sửa URL xem bàn khác.
2. WHEN khách quét QR THEN hệ thống SHALL phân giải `qr_token` về đúng bàn nội bộ và mở giao diện menu tương ứng với quán và bàn đó.
3. IF `qr_token` không hợp lệ hoặc trỏ tới bàn/quán không tồn tại/không hoạt động THEN hệ thống SHALL hiển thị thông báo lỗi thân thiện và không cho gọi món.
4. WHEN khách quét QR của một bàn chưa có phiên đang mở THEN hệ thống SHALL tạo hoặc gắn vào một phiên bàn (table session) hiện hành.
5. THE hệ thống SHALL cho phép nhân viên/chủ quán xuất (tải/in) QR của từng bàn.
6. WHERE cần thu hồi một QR (in lại, nghi lộ) THE hệ thống SHALL cho phép sinh lại `qr_token` mới khiến QR cũ hết hiệu lực; IF bàn đang có phiên `open` khi thu hồi THEN phiên đó SHALL giữ nguyên (không bị đóng), khách quét QR mới vẫn gắn vào đúng phiên đang mở của bàn.

### Requirement 3: Xem menu & gọi món

**User Story:** Là khách hàng, tôi muốn xem danh sách món theo nhóm và gửi order, để được phục vụ.

#### Acceptance Criteria

1. THE hệ thống SHALL hiển thị danh sách món của quán, kèm tên, giá, nhóm món và trạng thái còn/hết hàng.
2. WHERE một món được đánh dấu hết hàng THE hệ thống SHALL vẫn hiển thị món đó kèm nhãn "Hết hàng" nhưng vô hiệu hóa nút thêm vào giỏ (không tự động ẩn khỏi menu).
3. WHEN khách thêm món vào giỏ và gửi order THEN hệ thống SHALL tạo một `order` mới gắn vào phiên bàn hiện hành cùng các `order_item` với trạng thái ban đầu `pending`.
4. WHEN khách gọi thêm món trong cùng một phiên bàn THEN hệ thống SHALL tạo order mới nhưng vẫn gom chung vào bill của phiên bàn đó.
5. THE hệ thống SHALL cho phép khách ghi chú cho từng món (ví dụ: ít đá, không cay).
6. IF khách gửi order với giỏ hàng rỗng THEN hệ thống SHALL từ chối và thông báo.

### Requirement 4: Theo dõi & cập nhật trạng thái món (real-time)

**User Story:** Là nhân viên bếp, tôi muốn thấy các món cần làm và cập nhật trạng thái để bàn khác và khách biết món đã ra chưa.

#### Acceptance Criteria

1. THE hệ thống SHALL quản lý trạng thái mỗi `order_item` theo luồng: `pending → cooking → ready → served`, trong đó `cooking` và `ready` là **tuỳ chọn** (bếp có thể tích thẳng từ `pending` sang `served`). Trạng thái `cancelled` (xem Requirement 11) là trạng thái kết thúc tách khỏi luồng này.
2. WHERE hiển thị cho khách THE hệ thống SHALL chỉ phân biệt 2 mức: "chưa ra" (mọi trạng thái trước `served`) và "đã ra" (`served`); các trạng thái `cooking`/`ready` chỉ hiển thị trên màn hình nhân viên.
3. WHEN nhân viên bếp bắt đầu làm một món THEN hệ thống SHALL cho phép chuyển món sang `cooking` (không bắt buộc).
4. WHEN nhân viên tích ✅ một món đã ra THEN hệ thống SHALL chuyển trạng thái món sang `served` và ngừng countdown/cảnh báo của món đó.
5. WHEN trạng thái một món thay đổi THEN hệ thống SHALL đẩy cập nhật tới màn hình bếp và màn hình khách qua realtime trong vòng ~1 giây.
6. WHERE nhiều nhân viên cập nhật nhiều món đồng thời THE hệ thống SHALL xử lý không gây race condition (mỗi cập nhật là atomic).
7. IF một cập nhật trạng thái đi ngược luồng (ví dụ từ `served` về `pending`) THEN hệ thống SHALL từ chối, NGOẠI TRỪ thao tác hoàn tác của **bất kỳ nhân viên đã đăng nhập PIN** trong vòng 2 phút kể từ khi món được tích `served`. THE hệ thống SHALL lưu `served_by` và `served_at` cho mỗi món; MVP KHÔNG cần bảng audit log riêng cho hành động hoàn tác. **Giới hạn đã biết:** do PIN dùng chung (Requirement 12.2/12.7), hệ thống không phân biệt được cá nhân nào hoàn tác — chấp nhận được ở giai đoạn 1.
8. WHEN kết nối realtime bị gián đoạn rồi khôi phục THEN client SHALL đồng bộ lại trạng thái hiện tại của các món.

### Requirement 5: Countdown ngầm & cảnh báo nhấp nháy

**User Story:** Là nhân viên bếp, tôi muốn món chưa ra thì nhấp nháy 🧨 và nhấp nháy nhanh dần khi quá giờ, để ưu tiên xử lý món trễ.

#### Acceptance Criteria

1. WHERE một món có `prep_time_minutes > 0` và chưa ở trạng thái `served`/`cancelled` THE hệ thống SHALL hiển thị món đó với hiệu ứng nhấp nháy 🧨; WHERE `prep_time_minutes = 0` (ví dụ bia, nước ngọt phục vụ ngay) THE hệ thống SHALL KHÔNG áp dụng nhấp nháy/countdown.
2. WHEN một `order_item` có `prep_time_minutes > 0` được tạo THEN hệ thống SHALL bắt đầu countdown ngầm dựa trên `prep_time_minutes` của món (bắt buộc, giá trị ≥ 0; `0` nghĩa là không cần countdown), tính động từ mốc `requested_at`.
3. THE hệ thống SHALL cung cấp preset thời gian gợi ý (mặc định mặn 10 phút, nhạt 5 phút) trong `restaurant_settings` **chỉ** để admin điền nhanh `prep_time_minutes` khi tạo món; runtime không suy ra thời gian từ loại món.
4. WHEN thời gian chờ của món vượt ngưỡng `prep_time_minutes` THEN hệ thống SHALL tăng `overdue_level` (mức khẩn cấp) làm tốc độ nhấp nháy nhanh hơn theo mức.
5. THE hệ thống SHALL tính `overdue_level` **động** từ `requested_at` và thời điểm hiện tại, KHÔNG lưu vào DB và KHÔNG đổi trạng thái (`status`) của món.
6. WHEN món chuyển sang `served` hoặc `cancelled` THEN hệ thống SHALL dừng nhấp nháy và reset cảnh báo của món đó.
7. THE hiệu ứng nhấp nháy 🧨 và tốc độ tăng dần theo `overdue_level` SHALL áp dụng cho **màn hình nhân viên/bếp** (để ưu tiên xử lý); WHERE hiển thị cho khách THE hệ thống SHALL chỉ thể hiện trạng thái "đang chờ" đơn giản, KHÔNG nhấp nháy theo cùng tốc độ khẩn cấp (tránh gây sốt ruột không cần thiết).

### Requirement 6: Thanh toán, đóng bàn & in bill

**User Story:** Là nhân viên, tôi muốn thanh toán để đóng bàn và in bill, để kết thúc phục vụ một lượt khách.

#### Acceptance Criteria

1. WHEN nhân viên bấm thanh toán cho một phiên bàn THEN hệ thống SHALL tính tổng tiền dựa trên tất cả order_item của phiên (trừ món đã hủy).
2. WHEN thanh toán hoàn tất THEN hệ thống SHALL đóng phiên bàn (trạng thái `closed`) và giải phóng bàn cho lượt khách mới.
3. WHERE có máy in nhiệt THE hệ thống SHALL in bill qua máy in nhiệt (ESC/POS).
4. IF không có máy in nhiệt THEN hệ thống SHALL tạo bill dạng PDF làm phương án dự phòng.
5. THE bill SHALL gồm tên quán, số bàn, danh sách món + số lượng + đơn giá, tổng tiền, và thời gian.
6. WHEN một phiên bàn đã đóng THEN hệ thống SHALL không cho thêm order vào phiên đó.
7. IF bấm thanh toán khi còn món chưa `served` THEN hệ thống SHALL cảnh báo và liệt kê các món chưa ra, nhưng vẫn cho phép nhân viên xác nhận đóng bàn.
8. WHEN nhân viên xác nhận đóng bàn mà còn món ở `pending`/`cooking`/`ready` THEN hệ thống SHALL tự động chuyển các món đó sang `cancelled` với `cancel_reason = "table_closed"`; các món này SHALL bị loại khỏi tổng bill (khách không trả tiền món chưa nhận), dừng nhấp nháy và biến mất khỏi màn hình bếp.
9. THE hệ thống SHALL tính tổng bill (Requirement 6.1) **sau khi** đã xử lý huỷ tự động các món chưa `served` ở trên, đảm bảo tổng chỉ gồm món `served`.

### Requirement 7: Gọi nhân viên (đặc thù quán bia)

**User Story:** Là khách hàng ở quán bia, tôi muốn bấm nút gọi nhân viên để yêu cầu hỗ trợ (thêm đá, tính tiền...), để không phải đứng dậy.

#### Acceptance Criteria

1. THE hệ thống SHALL cung cấp nút "Gọi nhân viên" trên giao diện khách.
2. WHEN khách bấm gọi nhân viên THEN hệ thống SHALL đẩy thông báo realtime tới màn hình nhân viên kèm số bàn.
3. WHEN nhân viên xác nhận đã tiếp nhận THEN hệ thống SHALL xóa/đánh dấu đã xử lý yêu cầu gọi của bàn đó.
4. THE hệ thống SHALL giới hạn tối đa 1 yêu cầu gọi nhân viên mỗi 60 giây cho mỗi bàn; IF khách bấm lại trong khoảng này THEN hệ thống SHALL bỏ qua và thông báo nhẹ ("Đã gửi yêu cầu, nhân viên đang tới").

### Requirement 8: Quản lý menu & bàn (admin cơ bản)

**User Story:** Là chủ quán, tôi muốn quản lý menu và bàn, để cập nhật món và bố trí bàn.

#### Acceptance Criteria

1. THE hệ thống SHALL cho phép tạo/sửa/ẩn món (tên, giá, nhóm, `prep_time_minutes` bắt buộc, còn/hết hàng); WHERE admin chọn preset mặn/nhạt THE hệ thống SHALL điền sẵn `prep_time_minutes` từ preset trong `restaurant_settings` (admin vẫn sửa được).
2. THE hệ thống SHALL cho phép tạo/sửa/vô hiệu hóa bàn và sinh lại QR.
3. THE hệ thống SHALL cho phép chỉnh cấu hình quán trong `restaurant_settings` (thời gian countdown mặc định, tên, logo, tiền tệ).
4. WHERE giai đoạn rất sớm THE hệ thống MAY cho phép nhập menu ban đầu từ Google Sheet.

### Requirement 9: Báo cáo qua Google Sheets (không real-time)

**User Story:** Là chủ quán, tôi muốn xem báo cáo doanh thu và món bán chạy dễ dàng, để ra quyết định kinh doanh.

#### Acceptance Criteria

1. THE hệ thống SHALL đồng bộ dữ liệu tổng hợp (doanh thu, số lượng món bán) sang Google Sheet theo lịch định kỳ.
2. THE hệ thống SHALL lưu mapping riêng giữa mỗi quán và Google Sheet phục vụ báo cáo.
3. THE hệ thống SHALL KHÔNG dùng Google Sheets cho dữ liệu live (trạng thái món, countdown, tích ✅).
4. IF đồng bộ Google Sheet thất bại THEN hệ thống SHALL ghi log lỗi và thử lại ở lần đồng bộ sau mà không ảnh hưởng hoạt động chính.

### Requirement 10: Yêu cầu phi chức năng (nền tảng)

**User Story:** Là chủ hệ thống, tôi muốn hệ thống chạy ổn định, chi phí thấp ở giai đoạn đầu và scale dần, để vận hành bền vững.

#### Acceptance Criteria

1. THE hệ thống SHALL dùng PostgreSQL làm database chính, hỗ trợ ghi đồng thời.
2. THE hệ thống SHALL cập nhật trạng thái realtime qua WebSocket, tránh polling liên tục.
3. THE hệ thống SHALL dùng Redis cho Pub/Sub realtime và lưu trạng thái tạm (phiên bàn active, fan-out WebSocket); nguồn sự thật (source of truth) vẫn là PostgreSQL.
4. THE naming convention SHALL theo: repo kebab-case, module Python snake_case.
5. THE hệ thống SHALL triển khai được trên nền tảng chi phí thấp (Railway/Render) ở giai đoạn 1 và Docker hóa để chuyển VPS khi mở rộng.
6. THE hệ thống SHALL cô lập dữ liệu giữa các quán để một quán không truy cập được dữ liệu quán khác.

### Requirement 11: Huỷ món (cancel)

**User Story:** Là khách hoặc nhân viên, tôi muốn huỷ một món khi cần (gọi nhầm, bếp không làm được), để bill phản ánh đúng thực tế.

#### Acceptance Criteria

1. THE hệ thống SHALL có trạng thái `cancelled` là trạng thái kết thúc, tách khỏi luồng `pending → cooking → ready → served`.
2. WHERE một `order_item` đang ở `pending` THE hệ thống SHALL cho phép khách tự huỷ món đó.
3. IF món đã chuyển sang `cooking`, `ready` hoặc `served` THEN hệ thống SHALL KHÔNG cho khách tự huỷ; khách phải gọi nhân viên.
4. THE hệ thống SHALL cho phép nhân viên huỷ bất kỳ món nào chưa `served` (kèm lý do tuỳ chọn).
5. WHEN một món chuyển sang `cancelled` THEN hệ thống SHALL loại món đó khỏi tính tổng bill và dừng countdown/cảnh báo của món.
6. WHEN một món bị huỷ THEN hệ thống SHALL đẩy cập nhật realtime tới màn hình bếp và khách.
7. THE hệ thống SHALL lưu vết `cancelled_by` (`customer` / `staff` / `system` — trong đó `system` dùng cho các trường hợp tự động huỷ theo Requirement 6.8 và 13.8) và thời điểm huỷ để phục vụ báo cáo.

### Requirement 12: Xác thực & phân quyền

**User Story:** Là chủ quán, tôi muốn kiểm soát ai được thao tác gì, để bảo vệ dữ liệu và tránh thao tác trái phép.

#### Acceptance Criteria

1. THE hệ thống SHALL cho phép khách hàng truy cập giao diện gọi món **ẩn danh** qua QR, không yêu cầu đăng nhập.
2. THE hệ thống SHALL yêu cầu nhân viên (bếp/phục vụ) đăng nhập bằng **PIN/mật khẩu chung của quán** trước khi mở bàn thủ công (`opened_by`), cập nhật trạng thái món, huỷ món, tiếp nhận gọi nhân viên, khôi phục phiên `abandoned`, hoặc thanh toán.
3. THE hệ thống SHALL yêu cầu admin (chủ quán) đăng nhập bằng **tài khoản riêng** để truy cập chức năng quản lý menu/bàn/cấu hình (Requirement 8) và báo cáo.
4. THE hệ thống SHALL gắn mọi tài khoản staff/admin với một `restaurant_id` và chỉ cho thao tác trong phạm vi quán đó.
5. WHEN một yêu cầu tới endpoint cần quyền mà không có phiên đăng nhập hợp lệ THEN hệ thống SHALL từ chối với lỗi 401/403.
6. THE hệ thống SHALL lưu mật khẩu/PIN dưới dạng hash (không lưu plaintext).
7. WHERE giai đoạn 1 (1 quán) THE hệ thống MAY dùng một vai trò staff duy nhất (bếp và phục vụ chung quyền), nhưng mô hình dữ liệu SHALL sẵn sàng tách vai trò sau này.
8. THE hệ thống SHALL cho phép admin đặt lại (reset) PIN của staff khi quên.
9. THE hệ thống SHALL cho phép admin bật/tắt yêu cầu PIN cho màn hình bếp qua `restaurant_settings.kitchen_screen_requires_pin` (mặc định TRUE).
10. WHERE `kitchen_screen_requires_pin = FALSE` THE hệ thống SHALL cho phép truy cập và thao tác trên màn hình bếp mà không cần đăng nhập PIN, NHƯNG các hành động (`served_by`, `cancelled_by`...) SHALL vẫn ghi nhận là `staff` ẩn danh (không có định danh cá nhân).

### Requirement 13: Vòng đời & tự đóng phiên bàn bị bỏ quên

**User Story:** Là chủ quán, tôi muốn bàn không bị "kẹt" ở trạng thái mở khi khách rời đi mà chưa thanh toán, để bàn sẵn sàng cho lượt khách mới.

#### Acceptance Criteria

1. THE hệ thống SHALL quản lý phiên bàn theo trạng thái: `open → closed` (thanh toán) hoặc `open → abandoned` (bỏ quên).
2. WHERE một phiên bàn ở trạng thái `open` không có hoạt động (order mới, cập nhật trạng thái, gọi nhân viên) trong khoảng thời gian cấu hình được (mặc định **6 giờ**, phù hợp đặc thù quán bia khách ngồi lâu) THE hệ thống SHALL tự động đánh dấu phiên đó là `abandoned`.
3. THE hệ thống SHALL lưu ngưỡng timeout tự đóng trong `restaurant_settings` để mỗi quán tự chỉnh.
4. WHEN một phiên chuyển sang `abandoned` THEN hệ thống SHALL giải phóng bàn cho lượt khách mới và KHÔNG tự động tính là doanh thu.
5. THE hệ thống SHALL cho phép nhân viên xử lý một phiên `abandoned` trong vòng **24 giờ** kể từ khi bị đánh dấu, theo 2 trường hợp:
   - IF bàn **chưa** có phiên `open` mới nào kể từ lúc abandoned THEN hệ thống SHALL cho khôi phục phiên cũ về `open`.
   - IF bàn **đã** có một phiên `open` mới THEN hệ thống SHALL KHÔNG cho khôi phục về `open` (tránh 2 phiên open song song trên cùng bàn); chỉ cho phép thanh toán trực tiếp phiên abandoned cũ (chuyển thẳng `abandoned → closed`).
6. THE hệ thống SHALL đảm bảo tại một thời điểm mỗi bàn có **tối đa 1 phiên ở trạng thái `open`**.
7. WHERE quá 24 giờ kể từ khi bị đánh dấu `abandoned` THE phiên SHALL bị khoá, chỉ còn xem để đối soát.
8. WHEN một phiên chuyển sang `abandoned` THEN hệ thống SHALL tự động chuyển mọi `order_item` còn ở `pending`/`cooking`/`ready` sang `cancelled` với `cancel_reason = "session_abandoned"` để dừng nhấp nháy và loại khỏi màn hình bếp.
9. WHEN một phiên đã `closed` hoặc `abandoned` THEN hệ thống SHALL không cho thêm order vào phiên đó.
