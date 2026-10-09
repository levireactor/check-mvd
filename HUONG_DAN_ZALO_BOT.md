# HƯỚNG DẪN CÀI ĐẶT & SỬ DỤNG BOT LỌC ĐƠN HÀNG ZALO WEB

Bot Zalo được xây dựng dưới dạng **Chrome Extension (Manifest V3)** chạy trực tiếp trên **Zalo Web (https://chat.zalo.me)**, giúp tự động đọc và trích xuất thông tin đơn hàng từ các cuộc hội thoại, đồng thời đóng vai trò là **Chatbot tự động trả lời tra cứu Mã Vận Đơn theo SĐT thật 24/7** cho khách hàng.

---

## ⚡ CÁCH CHẠY CON BOT ZALO TỰ ĐỘNG 24/7 (NHANH NHẤT)

Chỉ cần nhấp đúp vào file:
```text
D:\tool pee\CHAY_BOT_ZALO_AUTO_247.bat
```
* File sẽ tự động mở một cửa sổ trình duyệt riêng biệt (Profile riêng, không ảnh hưởng đến nick Zalo chính của bạn).
* Tự động nạp sẵn Extension Bot và mở trang `chat.zalo.me`.
* Bạn chỉ cần đăng nhập tài khoản Zalo dùng làm Bot (quét mã QR) **1 lần duy nhất**.
* Kể từ lúc này, cứ để cửa sổ đó chạy:
  - Khách nhắn **"alo / shop ơi / xin chào"** -> Bot tự động chào và hướng dẫn gửi SĐT!
  - Khách nhắn **Số Điện Thoại Thật** -> Bot tự động tra Sheet và gửi ngay toàn bộ Mã Vận Đơn (MVĐ), trạng thái bưu cục, tiền COD, đơn vị vận chuyển cho khách!


---

## 🌟 CÁC TRƯỜNG THÔNG TIN TỰ ĐỘNG BÓC TÁCH

1. **👤 Tên khách hàng**: Tự động nhận diện từ cú pháp tin nhắn (*Tên:..., Khách:..., Gửi cho:...*) hoặc lấy theo tên hiển thị Zalo.
2. **📞 Số điện thoại thật**: Bộ giải mã thông minh tự động xử lý các hình thức lách số kiểm duyệt:
   - Viết chữ: `không`, `một`, `hai`, `ba`, `bốn`... -> chuyển thành số.
   - Viết chữ `o` hoặc `O`: `o98...` -> chuyển thành `098...`.
   - Ngắt dấu chấm, khoảng trắng, gạch nối: `098.123.4567`, `0 9 8 1 2 3...` -> đưa về dạng 10 chữ số chuẩn.
3. **🔗 Link sản phẩm**: Bóc tách link Shopee (kể cả link rút gọn `s.shopee.vn`, `shp.ee`), TikTok Shop, Lazada.
4. **🎟️ Mã giảm giá (Voucher)**: Tự động bắt mã voucher muốn đặt (`GIAM50K`, `FREESHIPEXTRA`, mã live...).
5. **🏠 Địa chỉ Mới & Địa chỉ Cũ (Sau sáp nhập)**: 
   - Tự động đối chiếu quy định sắp xếp đơn vị hành chính xã/phường/huyện.
   - Phân loại rõ **Địa chỉ mới** và **Địa chỉ cũ** để dễ dàng tra cứu bưu điện và tạo vận đơn.

---

## 🚀 HƯỚNG DẪN CÀI ĐẶT EXTENSION (CHỈ MẤT 30 GIÂY)

### Bước 1: Mở trang quản lý tiện ích trình duyệt
- Mở **Google Chrome**, **Cốc Cốc** hoặc **Microsoft Edge**.
- Nhập vào thanh địa chỉ: `chrome://extensions` (hoặc `edge://extensions` nếu dùng Edge) rồi nhấn Enter.

### Bước 2: Bật chế độ nhà phát triển (Developer Mode)
- Ở góc trên cùng bên phải, bật công tắc **"Chế độ dành cho nhà phát triển"** (Developer mode).

### Bước 3: Tải Extension vào trình duyệt
- Nhấp vào nút **"Tải tiện ích đã giải nén"** (Load unpacked) ở góc trên bên trái.
- Chọn thư mục:
  ```
  D:\tool pee\zalo_extension
  ```
- Trình duyệt sẽ hiển thị tiện ích **"Zalo Order Filter Bot - Lọc Đơn Hàng & Tag Khách Hàng"**.

---

## 📖 HƯỚNG DẪN SỬ DỤNG TRÊN ZALO WEB

1. Truy cập vào **https://chat.zalo.me** và đăng nhập nick Zalo của bạn.
2. Gắn **Thẻ phân loại (Tag)** cho khách hàng (ví dụ thẻ: *"Khách hàng"*, *"Chờ chốt"*... bằng tính năng phân loại có sẵn trên Zalo).

### ⚡ CHẾ ĐỘ KẾT NỐI TỰ ĐỘNG (AUTO MODE) - KHÔNG CẦN BẤM TAY
Bot được tích hợp **Bộ lắng nghe thời gian thực (Real-time Auto Capture)**:
1. **Tự động bắt đơn khi mở chat**: Khi công tắc `⚡ Tự Động Bắt Đơn` đang BẬT, bạn chỉ cần bấm vào bất kỳ khách nào trên danh sách Zalo hoặc khi khách gửi tin nhắn mới có chứa (SĐT, Link Shopee, địa chỉ, cú pháp đặt hàng), Bot sẽ:
   - Tự động bóc tách thông tin ngay lập tức.
   - Tự động lưu vào danh sách đơn hàng.
   - Hiển thị Toast thông báo ở góc trên màn hình Zalo: `⚡ [Tự Động Bắt Đơn] Đã lưu đơn của: Khánh Chi`.
2. **🚀 Quét Tự Động Tất Cả Khách Có Tag**:
   - Trong Popup Extension, nhập tên Tag (ví dụ: *Khách hàng*).
   - Nhấp nút **🚀 Quét Tự Động Tất Cả Tag**.
   - Bot sẽ tự động duyệt lần lượt từng khách hàng bên danh sách Zalo, tự động click mở, đọc tin nhắn và gom toàn bộ đơn về danh sách mà bạn không cần thao tác từng người!
3. **🔗 Đồng bộ sang Tool Shopee Tracker (Port 8080)**:
   - Nhấn nút **🔗 Đẩy Tool Shopee** để tự động lưu toàn bộ đơn hàng sang máy chủ Tool Shopee (`localhost:8080`), phục vụ check vận đơn và quản lý đơn hàng tập trung.

### 📦 TÍNH NĂNG MỚI: TRA CỨU MÃ VẬN ĐƠN (MVĐ) TỪ SHEET CLOUD RENDER
Bot đã được tích hợp liên thông trực tiếp với máy chủ đám mây Shopee Tracker Pro:
```text
https://shopee-tracker-pro-b1v8.onrender.com/
```
👉 **Đặc quyền**: Dữ liệu được lấy trực tiếp trên Cloud 24/7 (kết nối Supabase), bạn **không cần phải bật server máy tính hay chạy file server.py ở localhost** mà Bot vẫn tự động tra cứu mã vận đơn cho khách bình thường!

1. **Đồng bộ dữ liệu Sheet (1 Click)**:
   - Trong Popup Extension, chuyển sang tab **📦 Tra MVĐ & Báo Khách**.
   - Nguồn Sheet mặc định đã được cài sẵn: `https://shopee-tracker-pro-b1v8.onrender.com`.
   - Bấm nút **🔄 Đồng Bộ Sheet Cloud**: Bot sẽ tự động tải toàn bộ danh sách đơn hàng có mã vận đơn từ Cloud về Extension ngay tức khắc!
2. **Tra cứu theo Số Điện Thoại khách**:
   - Nhập SĐT khách hàng vào ô tìm kiếm hoặc bấm **🎯 Tự lấy SĐT từ hội thoại Zalo đang mở**.
   - Bot lập tức hiển thị thông tin chi tiết:
     - 📦 **Mã vận đơn** (MVĐ) & Đơn vị vận chuyển (SPX, Giao Hàng Nhanh, J&T...).
     - 🚚 **Trạng thái giao hàng thực tế** (Đang giao, Đã đến bưu cục, Đã giao thành công...).
     - 💰 **Tiền COD** cần thu.
     - 📱 **SĐT Shipper** (nếu có).
3. **🤖 CHATBOT TỰ ĐỘNG PHẢN HỒI 24/7 KHI KHÁCH NHẮN SĐT THẬT**:
   - Khi bạn bật công tắc **🤖 Chatbot Tự Trả Lời MVĐ** trong Extension:
   - Bất cứ khi nào có khách hàng gửi tin nhắn có chứa **Số Điện Thoại Thật** (hoặc cú pháp tra đơn):
     1. Bot tự động phát hiện SĐT thật của khách.
     2. Bot tự động tra cứu trong Sheet (đối chiếu cả cột SĐT người nhận `receiver_phone`, cột ghi chú `note_name` và thẻ `order_tag`).
     3. Bot tự động gom tất cả các đơn hàng thuộc SĐT đó (nếu khách có 1 đơn hoặc 2-3 đơn).
     4. Bot **TỰ ĐỘNG GÕ VÀ GỬI THẲNG TIN NHẮN TRẢ LỜI CHO KHÁCH HÀNG TRÊN ZALO** ngay lập tức mà bạn không cần chạm vào máy tính!
   - Khách hàng nhận được tin nhắn báo mã vận đơn, tình trạng giao hàng và tiền COD chỉ sau 1-2 giây!

### Cách Sử Dụng Nhanh Khác:
- **Nút nổi Zalo**: Ở góc dưới bên phải màn hình chat có 2 nút nổi: `⚡ Tự Động Bắt Đơn (BẬT)` và `📦 Tra MVĐ Báo Khách`.
- **Xuất Excel**: Bấm **📥 Xuất Excel** để tải về file `.csv` chứa toàn bộ các đơn đã gom (hỗ trợ tiếng Việt UTF-8 chuẩn).



---

## 🛡️ DÙNG NICK ZALO CHÍNH LÀM BOT: PHÂN BIỆT RÕ BẰNG THẺ TAG

Bạn hoàn toàn có thể dùng **chính nick Zalo cá nhân/chính của mình** để vừa chat bình thường, vừa làm Bot tự động mà không lo bị trả lời nhầm:

### 1. Nguyên lý hoạt động thông minh:
- **Người có gắn Thẻ Tag (ví dụ: `🔴 Khách hàng`)**:
  - Khi họ gửi tin nhắn chào hỏi hoặc gửi **Số Điện Thoại**: Bot sẽ tự động nhận diện, tra cứu Sheet và **trả lời mã vận đơn ngay lập tức**.
- **Người KHÔNG có Thẻ Tag (Bạn bè, gia đình, người thân, đối tác, đồng nghiệp)**:
  - Bot **BỎ QUA 100%**, tuyệt đối không can thiệp, không gõ phím hay gửi tin nhắn tự động. Bạn thoải mái nhắn tin trò chuyện với họ bằng tay bình thường!
- **Nhóm Chat (Group Zalo)**:
  - Bot tự động phát hiện và **bỏ qua tất cả các nhóm chat**, tránh việc spam trong group.

### 2. Các bước thiết lập trên Extension:
1. Mở Popup Extension -> Chuyển sang tab **📦 Tra MVĐ & Báo Khách**.
2. Bật công tắc **🏷️ Chỉ Bot với người có Thẻ Tag**: **BẬT (ON)**.
3. Nhập tên thẻ Tag muốn Bot phục vụ (Mặc định: `Khách hàng`).
4. Bật công tắc **🤖 Chatbot Tự Trả Lời MVĐ**: **BẬT (ON)**.
5. *(Tùy chọn)* Bật **⚡ Tự động bấm nút Gửi luôn**:
   - Nếu **BẬT**: Bot tự động gõ và tự bấm gửi luôn cho khách 24/7.
   - Nếu **TẮT**: Bot sẽ tự động gõ sẵn nội dung mã vận đơn vào ô chat, bạn chỉ việc liếc qua và ấn Enter khi thấy ưng ý!
