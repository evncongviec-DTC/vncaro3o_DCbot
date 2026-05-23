# Vncaro3o DCbot

Vncaro3o DCbot là phần mềm hỗ trợ chơi cờ Caro tự động, được thiết kế với tiêu chí **bảo mật tuyệt đối** cho người sử dụng. Nó cho phép bạn kết nối với nền tảng VnCaro thông qua trình duyệt an toàn và đưa ra các nước cờ tối ưu hoặc tự động đánh.

## Các tính năng chính
- **Chơi bằng Model AI**: Bot sẽ dựa trên file mô hình huấn luyện được chọn để tự động phân tích và đưa ra nước đi tốt nhất.
- **Chơi thủ công (Ghi Log)**: Bạn tự đánh cờ, Bot sẽ âm thầm ghi lại lịch sử ván đấu (SGF) để bạn có thể xem lại hoặc dùng để huấn luyện AI sau này.
- **Auto-Farm**: Tính năng treo máy đánh liên tục không ngừng nghỉ.
- **Phân tích ngầm (Pondering)**: Bot sẽ tận dụng thời gian đối thủ đang suy nghĩ để tính toán trước các nước đi, giúp tăng tốc độ phản hồi.
- **Xem lại ván đấu**: Tích hợp sẵn công cụ trực quan (HTML) để xem lại từng nước đi trong ván cờ đã đánh.

## Cam kết Bảo mật (Cơ chế Sandbox)
Rất nhiều người dùng lo ngại khi phải đăng nhập tài khoản vào một phần mềm của bên thứ 3. **Tuy nhiên, Vncaro3o DCbot được thiết kế với cơ chế an toàn tối đa:**

1. **Trình duyệt Độc lập (Sandbox)**: Khi bạn bấm "BẮT ĐẦU BOT", phần mềm sẽ không can thiệp vào trình duyệt Chrome chính mà bạn đang sử dụng hàng ngày. Thay vào đó, nó mở ra một **phiên bản Chrome trắng tinh hoàn toàn độc lập**.
2. **Không chạm đến dữ liệu cá nhân**: Vì chạy trên Sandbox độc lập, Bot **không hề quét, đọc, hay lấy cắp** bất kỳ lịch sử duyệt web, Cookie, mật khẩu Facebook, hay tài khoản ngân hàng nào đang lưu trữ trên trình duyệt chính của bạn.
3. **An toàn hơn việc kết nối trực tiếp**: Nếu Bot chạy thẳng vào trình duyệt chính của bạn, rủi ro lộ lọt thông tin cá nhân sẽ cực kỳ cao. Cơ chế Sandbox giúp "cách ly" Bot hoàn toàn khỏi đời sống cá nhân của bạn.
4. **Nhớ tài khoản tự động**: Bạn chỉ cần đăng nhập tài khoản VnCaro **1 lần duy nhất** ở cửa sổ trắng này. Thông tin đăng nhập sẽ được lưu trữ cục bộ vào thư mục chrome_profile ngay cạnh phần mềm. Các lần mở sau, Bot sẽ tự động đăng nhập.

## Hướng dẫn sử dụng
1. Giải nén hoặc để file Vncaro3o_DCbot.exe vào một thư mục bất kỳ.
2. Mở file .exe lên.
3. Chọn file AI (Mô hình).
4. Nhấn **BẮT ĐẦU BOT**.
5. Cửa sổ Chrome mở ra -> Đăng nhập VnCaro.
6. Khi vào bàn cờ, bạn chỉ cần đánh nước đầu tiên, hoặc chờ đối thủ đánh, Bot sẽ tự động tiếp quản ván cờ.

---
*Mọi dữ liệu ván đấu và cấu hình đều được lưu trữ hoàn toàn trên máy tính cá nhân của bạn. Chúc bạn có những trận cờ đỉnh cao!*
