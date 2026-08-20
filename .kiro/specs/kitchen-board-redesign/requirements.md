# Requirements Document

## Introduction

Màn hình bếp (`/kitchen`) của QOrder MVP đã chạy được, nhưng gộp toàn bộ công việc của **hai vai trò khác nhau** vào một lưới phẳng duy nhất: đầu bếp cần biết "nấu món nào tiếp theo", còn phục vụ cần biết "món nào mang ra bàn nào" và "bàn nào thanh toán". Hậu quả là cả hai vai trò đều phải đọc toàn bộ board để lọc ra phần việc của mình.

Spec này là **thiết kế lại kiến trúc thông tin (UX) của một màn hình đã có**, không thêm nghiệp vụ backend mới ngoài phần dữ liệu ngữ cảnh bàn còn thiếu. Mọi quy tắc nghiệp vụ của `qorder-mvp` (R4, R5, R6.7, R7, R11.4, R12.9/R12.10) được **giữ nguyên**; spec này chỉ quy định dữ liệu đó được **trình bày và sắp xếp** như thế nào.

### Bối cảnh vận hành đã xác nhận

Quán dùng **một tablet duy nhất đặt tại bếp**, cả đầu bếp và phục vụ đều xem cùng màn hình đó. Điều này định hướng toàn bộ layout:

- Chế_Độ_Gộp là chế độ **mặc định**; hai chế độ chuyên biệt chỉ là bộ lọc tạm thời khi một vai trò cần tập trung.
- Hai vai trò cần **cùng nhìn thấy phần việc của mình trên một khung hình**, nên phân vùng theo chiều dọc quan trọng hơn việc chuyển qua lại giữa các trang.
- Nhân viên đọc màn hình **từ xa và không đứng sát tablet**, nên cỡ chữ và Nhãn_Bàn phải đọc được ở khoảng cách một sải tay.
- Không thể dựa vào việc "mỗi thiết bị ghim một chế độ", nên **không được để một vai trò phải chuyển chế độ để làm việc thường ngày**.

### Giả định cần xác nhận

Bốn điểm dưới đây được đặt giả định để hoàn thiện bản đầu; nếu thực tế khác thì sửa lại các requirement tương ứng:

- **Nhóm mặc định theo Nhóm_Bàn** (Requirement 3), vì trên một tablet dùng chung thì nhu cầu "mang một chuyến ra một bàn" của phục vụ va chạm ít hơn. Nhóm theo tên món vẫn bật được bằng 1 lần chạm.
- **Trạng thái `cooking`/`ready` vẫn được dùng** (Requirement 5). Nếu thực tế bếp luôn tích thẳng `pending → served` thì Làn_Sẵn_Sàng nên bỏ và Requirement 5 rút gọn còn thao tác một chạm.
- **Thanh toán vẫn thực hiện trên màn bếp** (Requirement 8), giữ đúng phạm vi `CheckoutPanel` hiện có.
- **Nhãn_Bàn chưa hề xuất hiện trên board hiện tại** (Requirement 2) và cần sửa cả backend `GET /kitchen/board`.

### Hiện trạng đã kiểm chứng trong code

Các quan sát dưới đây lấy trực tiếp từ `frontend/src/kitchen/*` và `qorder_api/api/kitchen_router.py`:

1. `KitchenBoard.tsx` render **một lưới phẳng** tất cả item đang hoạt động, chỉ sắp xếp theo `requested_at` tăng dần; không nhóm theo bàn, không nhóm theo món, không tách vai trò.
2. `KitchenItemCard.tsx` **không hiển thị bàn nào cả** (chỉ có tên món, số lượng, ghi chú, badge trạng thái). `KitchenBoardItem` cũng không có trường bàn — `GET /kitchen/board` chỉ trả `order_id`. Phục vụ không thể biết mang món đi đâu.
3. `getBlinkClass` trả `animate-blink-slow` cho `overdue_level = 0`, nên **mọi món đúng hạn cũng nhấp nháy**; khi board đông thì toàn bộ màn hình nhấp nháy và mất hết khả năng phân biệt món trễ.
4. Thẻ món **không có số phút** đã chờ hoặc còn lại; mức khẩn cấp chỉ được truyền tải bằng tốc độ nhấp nháy và emoji 🧨.
5. Board **không có nút chuyển `cooking`/`ready`**; chỉ có "✅ Xong" (nhảy thẳng sang `served`) và "✕". Badge `Nấu`/`Sẵn` tồn tại nhưng không đường nào đặt được từ màn hình bếp.
6. Nút huỷ "✕" nằm ngay cạnh nút "✅ Xong", **không có bước xác nhận** — rủi ro chạm nhầm cao trong giờ cao điểm.
7. Thẻ hoàn tác là một placeholder lỗi: render `name_snapshot="(đã phục vụ)"`, `quantity={0}`, và hiện `ID: xxxxxxxx...`; nó **chiếm ô trong cùng lưới** với món đang chờ nên càng làm board rối.
8. `StaffCallNotification` là overlay `fixed top-4 right-4` xếp chồng **không giới hạn**, đè lên header (nút refresh/đăng xuất) và đè lên nội dung board.
9. `CheckoutPanel` nhóm theo `orderSessionMap`, map này **chỉ được nạp từ event WS `order.created`**; sau khi tải lại trang map rỗng nên panel luôn hiện "Không có bàn nào có món đang chờ" (khớp gap đã ghi trong `HUONG-DAN-CHAY.md`). Khi có dữ liệu thì cũng chỉ hiện `Phiên: <8 ký tự UUID>` chứ không phải tên bàn.
10. Board chỉ chứa item **chưa** `served`, nên phục vụ không có cách nào xem lại toàn bộ món của một bàn trước khi thanh toán.
11. Không có chỉ báo kết nối realtime; `useKitchenWebSocket` dùng lại **cùng một ticket one-shot** cho mọi lần reconnect nên sau khi mất kết nối là hỏng vĩnh viễn, mà màn hình không báo gì cho nhân viên.

## Glossary

- **Màn_Hình_Bếp**: toàn bộ trang `/kitchen/board` sau khi thiết kế lại.
- **Chế_Độ_Nấu**: chế độ hiển thị dành cho đầu bếp, ưu tiên câu hỏi "nấu món nào tiếp theo".
- **Chế_Độ_Phục_Vụ**: chế độ hiển thị dành cho phục vụ, ưu tiên câu hỏi "mang món nào ra bàn nào" và "bàn nào cần thanh toán".
- **Chế_Độ_Gộp**: chế độ hiển thị cả phần việc nấu và phần việc phục vụ trên cùng một màn hình, dùng khi quán chỉ có một thiết bị.
- **Thẻ_Món**: khối hiển thị một `order_item` trên Màn_Hình_Bếp.
- **Nhãn_Bàn**: `tables.label` — tên bàn người đọc được (ví dụ "Bàn 5"), phân biệt với `table_id`/`table_session_id` dạng UUID.
- **Nhóm_Bàn**: tập hợp các Thẻ_Món thuộc cùng một `table_session_id`, hiển thị dưới một tiêu đề là Nhãn_Bàn.
- **Làn_Chờ_Nấu**: vùng chứa các món có `status` ∈ {`pending`, `cooking`}.
- **Làn_Sẵn_Sàng**: vùng chứa các món có `status` = `ready`, tức món chờ phục vụ mang ra.
- **Dải_Hoàn_Tác**: vùng riêng biệt, nằm ngoài Làn_Chờ_Nấu và Làn_Sẵn_Sàng, chứa các món vừa được tích `served` còn trong cửa sổ hoàn tác 2 phút theo R4.7 của `qorder-mvp`.
- **Khay_Gọi_NV**: vùng hiển thị các yêu cầu gọi nhân viên đang `pending` (R7 của `qorder-mvp`).
- **Bảng_Thanh_Toán**: vùng cho phép nhân viên chọn một phiên bàn và thanh toán (R6 của `qorder-mvp`).
- **Chỉ_Báo_Kết_Nối**: thành phần hiển thị trạng thái kết nối realtime của Màn_Hình_Bếp.
- **`overdue_level`**: mức trễ 0..3 tính client-side từ `requested_at` + `prep_time_snapshot`, không lưu DB (R5.5 của `qorder-mvp`).
- **Món_Phục_Vụ_Ngay**: món có `prep_time_snapshot = 0` (bia, nước ngọt), không countdown và không nhấp nháy (R5.1 của `qorder-mvp`).
- **Giờ_Cao_Điểm**: điều kiện Màn_Hình_Bếp có từ 40 Thẻ_Món đang hoạt động trở lên.

## Requirements

### Requirement 1: Tách phần việc theo vai trò

**User Story:** Là đầu bếp hoặc phục vụ, tôi muốn màn hình chỉ hiện phần việc của vai trò mình, để không phải đọc qua công việc của người khác.

#### Acceptance Criteria

1. THE Màn_Hình_Bếp SHALL cung cấp ba chế độ hiển thị: Chế_Độ_Gộp, Chế_Độ_Nấu và Chế_Độ_Phục_Vụ.
2. THE Màn_Hình_Bếp SHALL dùng Chế_Độ_Gộp làm chế độ mặc định khi mở màn hình lần đầu trên một thiết bị.
3. WHILE Chế_Độ_Gộp đang bật, THE Màn_Hình_Bếp SHALL hiển thị đồng thời Làn_Chờ_Nấu và Làn_Sẵn_Sàng trong hai vùng tách biệt, mỗi vùng có tiêu đề riêng và số món riêng.
4. WHILE Chế_Độ_Gộp đang bật, THE Màn_Hình_Bếp SHALL cho đầu bếp hoàn tất thao tác trên Làn_Chờ_Nấu và cho phục vụ hoàn tất thao tác trên Làn_Sẵn_Sàng mà không cần chuyển chế độ.
5. WHILE Chế_Độ_Gộp đang bật, THE Màn_Hình_Bếp SHALL cho phép mở Bảng_Thanh_Toán và hiển thị Khay_Gọi_NV mà không cần chuyển chế độ.
6. WHILE Chế_Độ_Nấu đang bật, THE Màn_Hình_Bếp SHALL hiển thị Làn_Chờ_Nấu và ẩn Bảng_Thanh_Toán.
7. WHILE Chế_Độ_Phục_Vụ đang bật, THE Màn_Hình_Bếp SHALL hiển thị Làn_Sẵn_Sàng, Khay_Gọi_NV và Bảng_Thanh_Toán.
8. WHEN nhân viên chọn một chế độ hiển thị, THE Màn_Hình_Bếp SHALL lưu lựa chọn đó trên thiết bị và áp dụng lại lựa chọn đó sau khi tải lại trang.
9. WHEN nhân viên chuyển chế độ hiển thị, THE Màn_Hình_Bếp SHALL hoàn tất chuyển trong vòng 300 ms mà không gọi lại `GET /kitchen/board`.
10. THE Màn_Hình_Bếp SHALL cho phép chuyển chế độ hiển thị bằng 1 lần chạm từ trạng thái mặc định của màn hình.
11. THE Màn_Hình_Bếp SHALL cho phép quay về Chế_Độ_Gộp bằng 1 lần chạm từ Chế_Độ_Nấu và từ Chế_Độ_Phục_Vụ.
12. WHERE `restaurant_settings.kitchen_screen_requires_pin = FALSE`, THE Màn_Hình_Bếp SHALL cho phép chọn chế độ hiển thị mà không yêu cầu đăng nhập PIN (giữ nguyên R12.10 của `qorder-mvp`).

### Requirement 2: Ngữ cảnh bàn trên mỗi món

**User Story:** Là phục vụ, tôi muốn thấy ngay món này thuộc bàn nào, để mang ra đúng bàn mà không phải hỏi lại bếp.

#### Acceptance Criteria

1. THE endpoint `GET /kitchen/board` SHALL trả về `table_session_id`, `table_id` và Nhãn_Bàn cho mỗi item.
2. THE các event realtime `order.created`, `item.updated` và `item.cancelled` trên kênh bếp SHALL mang `table_session_id` và Nhãn_Bàn của item tương ứng.
3. THE Thẻ_Món SHALL hiển thị Nhãn_Bàn, tên món, số lượng và ghi chú của món.
4. THE Thẻ_Món SHALL hiển thị Nhãn_Bàn bằng cỡ chữ tối thiểu bằng cỡ chữ của tên món.
5. IF một item không phân giải được Nhãn_Bàn, THEN THE Thẻ_Món SHALL hiển thị nhãn dự phòng "Bàn ?" và giữ item đó trên Màn_Hình_Bếp.
6. THE Màn_Hình_Bếp SHALL hiển thị định danh dạng UUID (`table_session_id`, `order_id`, `item_id`) chỉ trong khu vực dành cho chẩn đoán lỗi, tách khỏi Thẻ_Món.

### Requirement 3: Nhóm và sắp xếp món

**User Story:** Là đầu bếp, tôi muốn gộp các món giống nhau để nấu một lượt; là phục vụ, tôi muốn gộp theo bàn để mang một chuyến.

#### Acceptance Criteria

1. THE Màn_Hình_Bếp SHALL cung cấp hai cách nhóm: nhóm theo Nhóm_Bàn và nhóm theo tên món.
2. THE Màn_Hình_Bếp SHALL dùng nhóm theo Nhóm_Bàn làm cách nhóm mặc định.
3. THE Màn_Hình_Bếp SHALL cho phép chuyển giữa hai cách nhóm bằng 1 lần chạm và SHALL lưu lựa chọn đó trên thiết bị.
4. WHILE nhóm theo tên món đang bật, THE Làn_Chờ_Nấu SHALL gộp các item cùng `menu_item_id` và cùng ghi chú thành một Thẻ_Món kèm tổng số lượng và danh sách Nhãn_Bàn liên quan.
5. WHILE nhóm theo Nhóm_Bàn đang bật, THE Làn_Chờ_Nấu SHALL sắp xếp các Nhóm_Bàn theo `requested_at` nhỏ nhất trong nhóm, tăng dần.
6. THE Màn_Hình_Bếp SHALL sắp xếp các Thẻ_Món trong cùng một nhóm theo `overdue_level` giảm dần, rồi theo `requested_at` tăng dần.
7. WHEN nhân viên đổi cách nhóm, THE Màn_Hình_Bếp SHALL giữ nguyên tập item đang hiển thị và chỉ thay đổi cách gộp.
8. WHERE một Thẻ_Món gộp nhiều item, THE Màn_Hình_Bếp SHALL cho phép mở nhóm đó ra thành từng item riêng để thao tác trên một item.
9. THE Màn_Hình_Bếp SHALL đặt Món_Phục_Vụ_Ngay thành một nhóm riêng tách khỏi các món cần nấu.

### Requirement 4: Hiển thị mức khẩn cấp giảm nhiễu thị giác

**User Story:** Là đầu bếp trong giờ cao điểm, tôi muốn chỉ món trễ mới gây chú ý, để mắt tôi bắt được đúng món cần làm trước.

#### Acceptance Criteria

1. WHERE `overdue_level = 0`, THE Thẻ_Món SHALL hiển thị ở trạng thái tĩnh, không nhấp nháy.
2. WHERE `overdue_level` ∈ {1, 2, 3}, THE Thẻ_Món SHALL nhấp nháy với tốc độ tăng theo mức: mức 1 là 1 s, mức 2 là 0,6 s, mức 3 là 0,3 s mỗi chu kỳ (giữ nguyên ánh xạ tốc độ của R5.4 `qorder-mvp` cho các mức trễ).
3. WHERE `prep_time_snapshot = 0`, THE Thẻ_Món SHALL hiển thị tĩnh và không hiển thị countdown (giữ nguyên R5.1 của `qorder-mvp`).
4. THE Thẻ_Món SHALL hiển thị số phút đã chờ tính từ `requested_at` dưới dạng số nguyên phút.
5. WHERE `prep_time_snapshot > 0` và `overdue_level = 0`, THE Thẻ_Món SHALL hiển thị số phút còn lại tới hạn `prep_time_snapshot`.
6. THE Màn_Hình_Bếp SHALL cập nhật số phút và `overdue_level` của mọi Thẻ_Món ít nhất một lần mỗi 15 giây.
7. THE Thẻ_Món SHALL truyền tải `overdue_level` bằng ít nhất hai kênh thị giác đồng thời trong đó có một kênh không phải màu sắc và không phải nhấp nháy (ví dụ nhãn chữ hoặc thanh tiến độ), để nhân viên phân biệt được mức trễ khi nhìn nhanh hoặc khi bị hạn chế phân biệt màu.
8. THE Làn_Chờ_Nấu SHALL hiển thị số lượng món đang có `overdue_level ≥ 1` dưới dạng một con số tổng.
9. THE Màn_Hình_Bếp SHALL giới hạn hiệu ứng nhấp nháy trong phạm vi màn hình nhân viên (giữ nguyên R5.7 của `qorder-mvp`).
10. WHERE người dùng đã bật `prefers-reduced-motion` ở hệ điều hành, THE Thẻ_Món SHALL thay hiệu ứng nhấp nháy bằng chỉ báo tĩnh giữ đúng bậc khẩn cấp 0..3.

### Requirement 5: Luồng "sẵn sàng mang ra" cho phục vụ

**User Story:** Là phục vụ, tôi muốn thấy riêng danh sách món bếp đã làm xong, để mang ra ngay mà không cần bếp gọi.

#### Acceptance Criteria

1. THE Làn_Chờ_Nấu SHALL cung cấp thao tác chuyển một món sang `cooking` và thao tác chuyển một món sang `ready`.
2. WHEN một món chuyển sang `ready`, THE Màn_Hình_Bếp SHALL chuyển Thẻ_Món của món đó từ Làn_Chờ_Nấu sang Làn_Sẵn_Sàng trong vòng 1 giây.
3. THE Làn_Sẵn_Sàng SHALL nhóm các món theo Nhóm_Bàn và hiển thị số món đang chờ mang ra của từng bàn.
4. THE Làn_Sẵn_Sàng SHALL cung cấp thao tác đánh dấu `served` cho toàn bộ món `ready` của một Nhóm_Bàn bằng 1 lần chạm.
5. THE Làn_Chờ_Nấu SHALL cho phép đánh dấu một món trực tiếp thành `served` bằng 1 lần chạm, bỏ qua `cooking` và `ready` (giữ nguyên R4.1 và R4.4 của `qorder-mvp`).
6. THE Làn_Sẵn_Sàng SHALL hiển thị số phút đã trôi qua kể từ khi món chuyển sang `ready` cho mỗi Thẻ_Món.
7. WHERE một món ở `ready` quá 5 phút, THE Thẻ_Món SHALL hiển thị chỉ báo món chờ mang ra quá lâu.

### Requirement 6: Thao tác an toàn khi bận

**User Story:** Là nhân viên trong giờ cao điểm, tôi muốn không huỷ nhầm món khi chạm nhanh, để bill không bị sai.

#### Acceptance Criteria

1. THE Thẻ_Món SHALL đặt thao tác huỷ món trong một menu thao tác phụ cần tối thiểu 1 lần chạm để mở, và SHALL không hiển thị thao tác huỷ trong hàng thao tác chính chứa thao tác đánh dấu `served`.
2. WHEN nhân viên chọn huỷ một món, THE Màn_Hình_Bếp SHALL hiển thị một bước xác nhận nêu tên món, số lượng và Nhãn_Bàn, SHALL yêu cầu nhân viên chọn một lý do huỷ, và SHALL chỉ gọi `POST /kitchen/items/{id}/cancel` sau khi nhân viên xác nhận và đã có lý do huỷ.
3. THE Màn_Hình_Bếp SHALL đặt mọi vùng chạm thao tác có kích thước tối thiểu 44 × 44 pixel CSS, khoảng cách tối thiểu 8 pixel CSS giữa hai vùng chạm liền kề, và khoảng cách tối thiểu 24 pixel CSS giữa vùng chạm xác nhận huỷ và vùng chạm bỏ qua trong bước xác nhận huỷ.
4. WHEN một món được đánh dấu `served`, THE Dải_Hoàn_Tác SHALL hiển thị món đó kèm tên món thật của món, số lượng thật từ 1 trở lên, Nhãn_Bàn, và số giây còn lại của cửa sổ hoàn tác 2 phút đếm ngược từ 120 về 0 với tần suất cập nhật ít nhất một lần mỗi giây, và SHALL không hiển thị định danh dạng UUID trên món đó.
5. WHEN số giây còn lại của cửa sổ hoàn tác 2 phút của một món về 0, THE Dải_Hoàn_Tác SHALL loại món đó khỏi Dải_Hoàn_Tác trong vòng 1 giây và SHALL không còn cung cấp thao tác hoàn tác cho món đó (giữ nguyên R4.7 của `qorder-mvp`).
6. THE Màn_Hình_Bếp SHALL đặt Dải_Hoàn_Tác trong một vùng riêng nằm ngoài Làn_Chờ_Nấu và Làn_Sẵn_Sàng, SHALL không đặt Thẻ_Món đã `served` vào Làn_Chờ_Nấu hoặc Làn_Sẵn_Sàng, và SHALL không đặt món đã `cancelled` vào Dải_Hoàn_Tác.
7. WHILE Dải_Hoàn_Tác đang ở dạng thu gọn, THE Dải_Hoàn_Tác SHALL chiếm tối đa 15 % chiều cao vùng hiển thị, SHALL hiển thị số món đang trong cửa sổ hoàn tác 2 phút, và SHALL cung cấp thao tác mở rộng bằng 1 lần chạm tới dạng mở rộng chiếm tối đa 40 % chiều cao vùng hiển thị.
8. IF một thao tác đổi trạng thái món, huỷ món hoặc hoàn tác trả về HTTP 409, THEN THE Màn_Hình_Bếp SHALL hiển thị thông báo món đã được người khác cập nhật, SHALL đồng bộ lại item đó từ `GET /kitchen/board` trong vòng 2 giây, và SHALL hiển thị Thẻ_Món khớp với dữ liệu vừa đồng bộ.
9. IF một thao tác đổi trạng thái món, huỷ món hoặc hoàn tác thất bại vì lỗi mạng hoặc không nhận được phản hồi trong 10 giây, THEN THE Màn_Hình_Bếp SHALL khôi phục Thẻ_Món về trạng thái trước thao tác trong vòng 1 giây, SHALL hiển thị thông báo lỗi kèm một thao tác thử lại, và SHALL không tự động gửi lại yêu cầu đó.
10. WHEN nhân viên chọn hoàn tác một món trong Dải_Hoàn_Tác, THE Màn_Hình_Bếp SHALL đưa món về trạng thái ngay trước khi được đánh dấu `served`, SHALL chuyển Thẻ_Món của món đó về Làn_Chờ_Nấu hoặc Làn_Sẵn_Sàng tương ứng trong vòng 1 giây, và SHALL loại món đó khỏi Dải_Hoàn_Tác.
11. IF nhân viên đóng bước xác nhận huỷ mà không xác nhận, THEN THE Màn_Hình_Bếp SHALL không gọi `POST /kitchen/items/{id}/cancel` và SHALL giữ nguyên trạng thái cùng vị trí hiển thị của Thẻ_Món đó.
12. WHILE không có món nào trong cửa sổ hoàn tác 2 phút, THE Dải_Hoàn_Tác SHALL không chiếm chiều cao nào của vùng hiển thị và SHALL nhường toàn bộ không gian đó cho Làn_Chờ_Nấu và Làn_Sẵn_Sàng.

### Requirement 7: Yêu cầu gọi nhân viên không che nội dung

**User Story:** Là phục vụ, tôi muốn thấy bàn nào đang gọi mà không bị mất tầm nhìn vào board, để xử lý cả hai việc cùng lúc.

#### Acceptance Criteria

1. THE Khay_Gọi_NV SHALL hiển thị trong luồng bố cục của Màn_Hình_Bếp tại một vùng dành riêng chiếm tối đa 15 % chiều cao vùng hiển thị, không phủ lên bất kỳ Thẻ_Món nào của Làn_Chờ_Nấu và Làn_Sẵn_Sàng.
2. THE Khay_Gọi_NV SHALL hiển thị Nhãn_Bàn và số phút chờ tính từ `created_at` dưới dạng số nguyên phút cho mỗi yêu cầu gọi nhân viên đang `pending`, và SHALL cập nhật số phút đó ít nhất một lần mỗi 15 giây.
3. THE Khay_Gọi_NV SHALL hiển thị chi tiết tối đa 3 yêu cầu `pending` cũ nhất đồng thời, hiển thị số yêu cầu `pending` còn lại dưới dạng một con số tổng, và SHALL không tăng chiều cao vùng của mình khi số yêu cầu `pending` vượt quá 3.
4. THE Khay_Gọi_NV SHALL sắp xếp các yêu cầu theo `created_at` tăng dần, và với các yêu cầu có cùng `created_at` thì sắp xếp theo Nhãn_Bàn theo thứ tự chữ cái.
5. WHEN nhân viên tiếp nhận một yêu cầu, THE Khay_Gọi_NV SHALL loại yêu cầu đó khỏi Khay_Gọi_NV trong vòng 1 giây (giữ nguyên R7.3 của `qorder-mvp`).
6. WHILE không có yêu cầu gọi nhân viên nào ở trạng thái `pending`, THE Màn_Hình_Bếp SHALL ẩn hoàn toàn vùng Khay_Gọi_NV (chiều cao 0) và nhường toàn bộ không gian đó cho Làn_Chờ_Nấu và Làn_Sẵn_Sàng.
7. WHILE Chế_Độ_Nấu đang bật, THE Khay_Gọi_NV SHALL hiển thị ở dạng chỉ một con số tổng số yêu cầu đang `pending`, chiếm tối đa 5 % chiều cao vùng hiển thị.
8. THE Màn_Hình_Bếp SHALL giữ các thao tác ở đầu Màn_Hình_Bếp (làm mới, đăng xuất, chuyển chế độ hiển thị) nhìn thấy được và chạm được với mọi số lượng yêu cầu gọi nhân viên đang `pending`.
9. THE Khay_Gọi_NV SHALL cho phép mở danh sách đầy đủ các yêu cầu `pending` bằng 1 lần chạm và hiển thị danh sách đó trong một vùng cuộn riêng, không phủ lên Thẻ_Món.
10. IF thao tác tiếp nhận một yêu cầu thất bại vì lỗi mạng hoặc vì yêu cầu đó đã được người khác tiếp nhận, THEN THE Khay_Gọi_NV SHALL giữ nguyên danh sách đang hiển thị cho tới khi đồng bộ lại xong, hiển thị thông báo lỗi nêu lý do, và đồng bộ lại danh sách yêu cầu `pending`.

### Requirement 8: Bảng thanh toán theo bàn

**User Story:** Là phục vụ, tôi muốn chọn bàn theo tên bàn và thấy trước bàn đó còn món chưa ra, để thanh toán đúng và không bỏ sót món.

#### Acceptance Criteria

1. THE Bảng_Thanh_Toán SHALL liệt kê mọi phiên bàn đang `open` của quán, mỗi phiên trên một dòng lấy Nhãn_Bàn làm định danh chính, sắp xếp theo thời điểm mở phiên tăng dần, cuộn dọc khi số dòng vượt quá vùng hiển thị, và SHALL không hiển thị `table_session_id` dạng UUID trên dòng phiên.
2. THE Bảng_Thanh_Toán SHALL liệt kê phiên bàn đang `open` kể cả khi phiên đó không còn item nào ở `pending`, `cooking` hoặc `ready`, và với phiên đó SHALL hiển thị số món chưa `served` bằng 0.
3. WHEN Màn_Hình_Bếp được tải hoặc tải lại, THE Bảng_Thanh_Toán SHALL nạp danh sách phiên bàn đang `open` từ dữ liệu do server trả về, không phụ thuộc vào việc đã nhận event realtime `order.created` hay chưa, và SHALL hiển thị danh sách đó trong vòng 2 giây kể từ khi dữ liệu về.
4. THE Bảng_Thanh_Toán SHALL hiển thị cho mỗi phiên bàn: số món đã `served`, số món chưa `served` và tổng tiền tạm tính của các món đã `served`; và SHALL cập nhật cả ba giá trị này trong vòng 2 giây sau mỗi event realtime làm thay đổi trạng thái item của phiên bàn đó.
5. WHEN nhân viên chọn thanh toán một phiên bàn còn món chưa `served`, THE Bảng_Thanh_Toán SHALL liệt kê trong bước xác nhận: Nhãn_Bàn, tên món, số lượng và trạng thái hiện tại (`pending`, `cooking` hoặc `ready`) của từng món chưa `served`, liệt kê đầy đủ mọi món chưa `served` và cuộn dọc khi vượt quá vùng hiển thị (giữ nguyên R6.7 của `qorder-mvp`).
6. WHEN một phiên bàn được thanh toán, THE Bảng_Thanh_Toán SHALL hiển thị tổng tiền cuối cùng và danh sách món bị tự huỷ do đóng bàn kèm tên món và số lượng (giữ nguyên R6.8 của `qorder-mvp`), và SHALL loại phiên bàn đó khỏi danh sách phiên bàn đang `open` trong vòng 2 giây.
7. THE Bảng_Thanh_Toán SHALL cho phép mở bảng và chọn một bàn trong tối đa 2 lần chạm từ trạng thái mặc định của Chế_Độ_Gộp.
8. IF việc nạp danh sách phiên bàn thất bại hoặc không hoàn tất trong 5 giây, THEN THE Bảng_Thanh_Toán SHALL hiển thị thông báo lỗi nêu rõ không nạp được danh sách phiên bàn, SHALL hiển thị một thao tác thử lại, và SHALL không hiển thị thông báo trạng thái rỗng ở lần thất bại này.
9. WHILE lần nạp danh sách phiên bàn gần nhất thành công và không có phiên bàn nào đang `open`, THE Bảng_Thanh_Toán SHALL hiển thị thông báo trạng thái rỗng nêu rõ quán hiện không có bàn nào đang mở, phân biệt được với thông báo lỗi nạp danh sách.
10. WHEN nhân viên huỷ bước xác nhận thanh toán, THE Bảng_Thanh_Toán SHALL giữ phiên bàn đó ở trạng thái `open` trong danh sách, SHALL không huỷ món nào của phiên bàn đó, và SHALL trở về danh sách phiên bàn.
11. IF thao tác thanh toán một phiên bàn thất bại, THEN THE Bảng_Thanh_Toán SHALL giữ phiên bàn đó ở trạng thái `open` trong danh sách, SHALL hiển thị thông báo lỗi nêu rõ thanh toán chưa hoàn tất, và SHALL cho phép thực hiện lại thao tác thanh toán.

### Requirement 9: Tin cậy dữ liệu và trạng thái kết nối

**User Story:** Là nhân viên, tôi muốn biết board đang hiển thị dữ liệu mới hay đã đứng, để không tin vào màn hình cũ.

#### Acceptance Criteria

1. THE Chỉ_Báo_Kết_Nối SHALL hiển thị thường trực đúng một trong ba trạng thái, xác định như sau: "đang kết nối" khi Màn_Hình_Bếp đang lấy ticket hoặc đang mở kết nối realtime mà kết nối chưa mở xong; "đã kết nối" khi kết nối realtime đang mở và lần đồng bộ thành công gần nhất đã hoàn tất; "mất kết nối" khi không có kết nối realtime đang mở.
2. WHILE Chỉ_Báo_Kết_Nối ở trạng thái mất kết nối, THE Chỉ_Báo_Kết_Nối SHALL hiển thị số giây kể từ lần đồng bộ thành công gần nhất và SHALL cập nhật con số đó ít nhất một lần mỗi 5 giây, trong đó lần đồng bộ thành công gần nhất là thời điểm gần nhất Màn_Hình_Bếp nhận được phản hồi thành công từ `GET /kitchen/board` hoặc nhận được một event realtime trên kênh bếp.
3. WHEN kết nối realtime được khôi phục, THE Màn_Hình_Bếp SHALL gọi `GET /kitchen/board` và thay thế toàn bộ tập item đang hiển thị bằng kết quả trả về trước khi áp dụng bất kỳ event realtime nào, đồng thời giữ lại các event nhận được trong khi chờ phản hồi và áp dụng chúng theo thứ tự nhận sau khi thay thế xong (giữ nguyên R4.8 của `qorder-mvp`).
4. WHEN Màn_Hình_Bếp cần mở kết nối realtime, THE Màn_Hình_Bếp SHALL lấy một ticket mới qua `POST /auth/ws-ticket` ngay trước mỗi lần mở kết nối, kể cả mọi lần thử lại sau khi mất kết nối, và SHALL không dùng lại ticket của bất kỳ lần mở kết nối trước đó.
5. IF việc lấy ticket mới hoặc việc mở kết nối realtime thất bại, THEN THE Màn_Hình_Bếp SHALL thử lại sau 1 giây cho lần đầu và nhân đôi khoảng chờ sau mỗi lần thất bại kế tiếp tới giới hạn 30 giây mỗi lần, SHALL tiếp tục thử lại không giới hạn số lần trong khi Màn_Hình_Bếp còn mở, và SHALL giữ nguyên tập item đang hiển thị.
6. WHILE Chỉ_Báo_Kết_Nối ở trạng thái mất kết nối quá 30 giây, THE Màn_Hình_Bếp SHALL gọi `GET /kitchen/board` ít nhất một lần mỗi 30 giây với thời gian chờ tối đa 10 giây mỗi lần gọi, và WHEN một lần gọi trả về thành công, THE Màn_Hình_Bếp SHALL cập nhật tập item đang hiển thị và đặt lại mốc đồng bộ thành công gần nhất.
7. WHERE `restaurant_settings.kitchen_screen_requires_pin = FALSE`, THE Màn_Hình_Bếp SHALL lấy được ticket qua `POST /auth/ws-ticket`, tải được dữ liệu board và thực hiện được các thao tác đổi trạng thái món mà không có JWT staff (giữ nguyên R12.10 của `qorder-mvp`).
8. IF lời gọi `GET /kitchen/board` để đồng bộ lại thất bại, THEN THE Màn_Hình_Bếp SHALL giữ nguyên tập item đang hiển thị, giữ Chỉ_Báo_Kết_Nối ở trạng thái mất kết nối, hiển thị thông báo dữ liệu trên màn hình chưa được đồng bộ, và thử lại theo cùng quy tắc backoff của tiêu chí 5.
9. IF kết nối realtime bị đóng vì ticket không hợp lệ hoặc đã hết hạn, THEN THE Màn_Hình_Bếp SHALL loại bỏ ticket đang giữ và lấy một ticket mới qua `POST /auth/ws-ticket` trước lần thử mở kết nối kế tiếp, và SHALL không dùng lại ticket đã bị từ chối.
10. THE Chỉ_Báo_Kết_Nối SHALL hiển thị ở vị trí cố định không bị Thẻ_Món, Khay_Gọi_NV hoặc Bảng_Thanh_Toán che, ở cả ba chế độ hiển thị, và SHALL truyền tải trạng thái bằng cả nhãn chữ cỡ tối thiểu 18 pixel CSS và một ký hiệu hình, không chỉ bằng màu sắc.

### Requirement 10: Đọc được và dùng được trong giờ cao điểm

**User Story:** Là đầu bếp hoặc phục vụ đứng cách tablet dùng chung một sải tay với tay ướt, tôi muốn đọc và chạm chính xác, để không phải lại gần và nhìn kỹ.

#### Acceptance Criteria

1. THE Thẻ_Món SHALL hiển thị tên món ở cỡ chữ tối thiểu 18 pixel CSS, Nhãn_Bàn ở cỡ chữ tối thiểu 20 pixel CSS, và số lượng, ghi chú, số phút chờ ở cỡ chữ tối thiểu 16 pixel CSS, với tên món hiển thị tối đa 2 dòng và phần vượt quá được cắt bớt bằng dấu lược.
2. THE Màn_Hình_Bếp SHALL đạt tỉ lệ tương phản tối thiểu 4,5:1 giữa chữ và nền cho mọi chữ nhỏ hơn 24 pixel CSS, tối thiểu 3:1 cho chữ từ 24 pixel CSS trở lên, và tối thiểu 3:1 giữa đường viền hoặc chỉ báo trạng thái của Thẻ_Món và nền liền kề, giữ đúng các ngưỡng này ở mọi pha của hiệu ứng nhấp nháy.
3. WHILE Giờ_Cao_Điểm đang diễn ra, THE Màn_Hình_Bếp SHALL gộp các event realtime đến trong cùng một cửa sổ 200 ms thành một lần render và hoàn tất render lại danh sách trong vòng 200 ms kể từ event cuối của cửa sổ đó, với tối đa 120 Thẻ_Món đang hoạt động.
4. WHEN một item mới được thêm vào một làn, THE Màn_Hình_Bếp SHALL giữ nguyên vị trí hiển thị và vị trí cuộn của các Thẻ_Món đang thao tác — Thẻ_Món đang thao tác là Thẻ_Món đang được focus bàn phím, đang mở bước xác nhận, hoặc vừa được chạm trong vòng 3 giây gần nhất — và SHALL không tự cuộn vùng hiển thị.
5. THE Màn_Hình_Bếp SHALL hiển thị đồng thời Làn_Chờ_Nấu và Làn_Sẵn_Sàng trên vùng hiển thị rộng từ 768 pixel CSS trở lên mà không cần cuộn ngang, SHALL hiển thị tối thiểu 4 Thẻ_Món của mỗi làn mà không cần cuộn dọc, và SHALL giữ tiêu đề kèm số món của mỗi làn luôn hiển thị khi cuộn dọc trong làn đó.
6. WHERE vùng hiển thị hẹp hơn 768 pixel CSS, THE Màn_Hình_Bếp SHALL hiển thị một làn tại một thời điểm, cho phép chuyển sang làn còn lại bằng 1 lần chạm, và hiển thị số món của làn đang ẩn dưới dạng một con số tổng.
7. THE Màn_Hình_Bếp SHALL cho phép điều khiển mọi thao tác trên Thẻ_Món bằng bàn phím với thứ tự tab theo thứ tự hiển thị, SHALL hiển thị chỉ báo focus dày tối thiểu 2 pixel CSS với tương phản tối thiểu 3:1 so với nền liền kề, và SHALL cho phép rời khỏi mọi vùng chỉ bằng bàn phím.
8. WHILE không có item nào trong một làn, THE Màn_Hình_Bếp SHALL hiển thị trong vùng của riêng làn đó một thông báo trạng thái rỗng nêu tên làn và SHALL giữ tiêu đề của làn đó kèm số món bằng 0.
9. THE Màn_Hình_Bếp SHALL đặt khoảng cách tối thiểu 8 pixel CSS giữa hai vùng chạm thao tác liền kề, bổ trợ cho kích thước tối thiểu 44 × 44 pixel CSS của mỗi vùng chạm.
10. IF số Thẻ_Món đang hoạt động vượt quá 120, THEN THE Màn_Hình_Bếp SHALL hiển thị 120 Thẻ_Món đầu theo thứ tự sắp xếp hiện hành và hiển thị số món chưa được hiển thị dưới dạng một con số tổng của từng làn.
11. WHEN một item mới được thêm vào một làn mà Thẻ_Món của item đó nằm ngoài vùng nhìn hiện tại, THE Màn_Hình_Bếp SHALL hiển thị chỉ báo có món mới kèm số món mới của làn đó cho tới khi nhân viên cuộn tới Thẻ_Món đó hoặc chọn chỉ báo đó.
