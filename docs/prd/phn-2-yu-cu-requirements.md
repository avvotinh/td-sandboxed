# **Phần 2: Yêu cầu (Requirements)**

#### **Yêu cầu chức năng (Functional Requirements)**

* **FR1:** Hệ thống phải có khả năng kết nối tới WebSocket API của TradingView bằng thông tin xác thực do người dùng cung cấp.
* **FR2:** Hệ thống phải thu thập được dữ liệu real-time (tick và nến 1M, 5M, 15M, 1H, 4H, 1D) cho các symbol do người dùng chỉ định.
* **FR3:** Hệ thống phải ghi đồng thời dữ liệu thu thập được vào cache real-time (Redis) và database chuỗi thời gian ngắn hạn (TimescaleDB).
* **FR4:** Hệ thống phải cung cấp một tác vụ xử lý lô (sử dụng Airflow/Python) để định kỳ chuyển dữ liệu từ TimescaleDB sang lưu trữ dài hạn (file Parquet).
* **FR5:** Hệ thống phải cho phép các truy vấn phân tích trên dữ liệu lịch sử dài hạn thông qua một query engine (ClickHouse).
* **FR6:** Hệ thống phải cho phép các ứng dụng (bot giao dịch, script backtest) kết nối trực tiếp đến các kho dữ liệu nóng và lạnh.

#### **Yêu cầu phi chức năng (Non-Functional Requirements)**

* **NFR1:** Các truy vấn lấy dữ liệu real-time mới nhất từ "hot path" phải có thời gian phản hồi trung bình dưới 20ms.
* **NFR2:** Toàn bộ kiến trúc của phiên bản MVP phải có thể được triển khai bằng Docker Compose.
* **NFR3:** Tất cả các thành phần của hệ thống phải dựa trên công nghệ mã nguồn mở và có thể tự host.
* **NFR4:** Module thu thập dữ liệu phải có khả năng xử lý ít nhất 100 luồng dữ liệu symbol đồng thời mà không bị suy giảm hiệu năng đáng kể.
* **NFR5:** Tất cả các thành phần chính (thu thập, xử lý, lưu trữ) phải có cơ chế ghi log để phục vụ cho việc gỡ lỗi.
* **NFR6:** **Quản lý thông tin nhạy cảm:** Mọi thông tin nhạy cảm (như API key, mật khẩu database) **không được** lưu trữ trực tiếp trong mã nguồn. Chúng phải được truyền vào ứng dụng thông qua biến môi trường (environment variables) khi khởi chạy.
* **NFR7:** **Giám sát hệ thống:** Hệ thống phải cung cấp các phương tiện (ví dụ: log có cấu trúc hoặc health check endpoint) để theo dõi các chỉ số quan trọng sau:
    1.  Trạng thái kết nối của client thu thập dữ liệu.
    2.  Số lượng tin nhắn được xử lý mỗi phút.
    3.  Độ trễ của luồng dữ liệu nóng (hot path).
    4.  Trạng thái thành công/thất bại của các tác vụ xử lý lô.
