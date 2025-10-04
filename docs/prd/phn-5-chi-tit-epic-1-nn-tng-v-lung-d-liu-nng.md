# **Phần 5: Chi tiết Epic 1: Nền tảng và Luồng dữ liệu nóng**

**Mục tiêu mở rộng:** Epic này sẽ đặt nền móng cho toàn bộ dự án, từ việc thiết lập cấu trúc mã nguồn đến triển khai các thành phần hạ tầng cốt lõi. Mục tiêu cuối cùng của Epic này là tạo ra một luồng dữ liệu "nóng" (hot path) hoàn chỉnh và có thể kiểm chứng, cho phép thu thập dữ liệu từ TradingView, lưu trữ và truy vấn với độ trễ cực thấp.

#### **Story 1.1: Thiết lập cấu trúc Monorepo và môi trường Docker**
* **Là một** người phát triển, **tôi muốn** có một cấu trúc Monorepo chuẩn và một file Docker Compose để thiết lập môi trường, **để** có thể dễ dàng quản lý và chạy tất cả các thành phần của dự án một cách nhất quán.
* **Tiêu chí chấp nhận:**
    1.  Một project Monorepo được khởi tạo.
    2.  File `docker-compose.yml` ở thư mục gốc được tạo, định nghĩa các service cơ bản: `ingestion-client`, `redis`, và `timescaledb`.
    3.  Có thể chạy lệnh `docker-compose up` để khởi tạo các service mà không bị lỗi.
    4.  Một file `README.md` cơ bản được tạo, hướng dẫn cách build và chạy môi trường.

#### **Story 1.2: Xây dựng Go client kết nối tới WebSocket của TradingView**
* **Là một** hệ thống, **tôi muốn** một ứng dụng Go có thể thiết lập và duy trì kết nối WebSocket ổn định tới TradingView, **để** có thể bắt đầu nhận dữ liệu thị trường real-time.
* **Tiêu chí chấp nhận:**
    1.  Ứng dụng Go kết nối thành công tới endpoint WebSocket của TradingView.
    2.  Ứng dụng xử lý được quá trình xác thực (authentication).
    3.  Ứng dụng ghi log (logs) trạng thái kết nối (thành công, thất bại, mất kết nối).
    4.  Ứng dụng có cơ chế tự động kết nối lại nếu bị mất kết nối.

#### **Story 1.3: Thu thập và ghi dữ liệu vào Redis**
* **Là một** hệ thống, **tôi muốn** Go client xử lý các tin nhắn từ WebSocket và ghi dữ liệu tick/giá mới nhất vào Redis, **để** dữ liệu mới nhất luôn có sẵn với độ trễ thấp nhất cho bot giao dịch.
* **Tiêu chí chấp nhận:**
    1.  Go client phân tích (parses) thành công định dạng dữ liệu từ TradingView.
    2.  Dữ liệu tick/giá mới nhất của mỗi symbol được ghi vào một key riêng biệt trong Redis (ví dụ: `latest_price:BTCUSD`).
    3.  Thao tác ghi vào Redis thành công và được ghi log.

#### **Story 1.4: Ghi dữ liệu vào TimescaleDB**
* **Là một** hệ thống, **tôi muốn** Go client đồng thời ghi dữ liệu tick/nến nhận được vào TimescaleDB, **để** lưu trữ lịch sử dữ liệu nóng ngắn hạn cho việc phân tích theo cửa sổ thời gian.
* **Tiêu chí chấp nhận:**
    1.  Schema cho bảng dữ liệu thị trường (với hypertable) được tạo trong TimescaleDB.
    2.  Go client kết nối thành công tới database TimescaleDB.
    3.  Mỗi điểm dữ liệu nhận được được chèn (insert) như một hàng mới vào bảng tương ứng trong TimescaleDB.

#### **Story 1.5: Tạo script kiểm thử hiệu năng Hot Path**
* **Là một** người phát triển, **tôi muốn** một script kiểm thử (benchmark) để đo lường độ trễ truy vấn từ Redis và TimescaleDB, **để** có thể xác thực rằng hệ thống đáp ứng yêu cầu phi chức năng (NFR) về thời gian phản hồi dưới 20ms.
* **Tiêu chí chấp nhận:**
    1.  Một script (bằng Python hoặc Go) được tạo ra.
    2.  Script có thể kết nối và truy vấn dữ liệu mới nhất từ Redis.
    3.  Script có thể kết nối và truy vấn dữ liệu trong vòng 1 giây gần nhất từ TimescaleDB.
    4.  Script chạy một vòng lặp truy vấn (ví dụ: 1000 lần) và xuất ra độ trễ trung bình cho cả hai database.
    5.  Script được coi là "Pass" nếu độ trễ trung bình dưới 20ms.
