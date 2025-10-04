# **Phần 6: Chi tiết Epic 2: Luồng dữ liệu lạnh và Hoàn thiện**

**Mục tiêu mở rộng:** Epic này tập trung vào việc xây dựng luồng dữ liệu "lạnh" (cold path), cho phép lưu trữ dài hạn và phân tích dữ liệu lịch sử. Mục tiêu là hoàn thiện khả năng của hệ thống cho việc backtesting và huấn luyện AI. Cuối Epic này, toàn bộ bản thiết kế kiến trúc sẽ được hoàn chỉnh với đầy đủ tài liệu hướng dẫn.

#### **Story 2.1: Cài đặt Airflow và tạo DAG xử lý dữ liệu**
* **Là một** người phát triển, **tôi muốn** một môi trường Airflow cơ bản và một DAG (Directed Acyclic Graph) trống, **để** có thể bắt đầu xây dựng và điều phối pipeline xử lý dữ liệu.
* **Tiêu chí chấp nhận:**
    1.  Airflow được thêm như một service mới vào file `docker-compose.yml`.
    2.  Một thư mục mới cho các tác vụ xử lý (ví dụ: `apps/processing-job`) được tạo trong monorepo, chứa môi trường Python với các thư viện cần thiết (Pandas/Polars, connectors).
    3.  Một DAG đơn giản, có thể kích hoạt thủ công, được tạo trong Airflow.
    4.  DAG có thể chạy thành công một script Python và ghi log một thông điệp "Hello World".

#### **Story 2.2: Xây dựng script chuyển dữ liệu từ TimescaleDB sang Parquet**
* **Là một** hệ thống, **tôi muốn** một script có thể đọc dữ liệu từ TimescaleDB theo một khoảng thời gian và lưu dưới dạng file Parquet, **để** có thể lưu trữ dữ liệu lịch sử một cách hiệu quả về chi phí.
* **Tiêu chí chấp nhận:**
    1.  Script Python kết nối thành công tới TimescaleDB.
    2.  Script có thể truy vấn dữ liệu của ngày hôm trước.
    3.  Dữ liệu truy vấn được được chuyển đổi và lưu thành một file Parquet.
    4.  File Parquet được lưu vào một thư mục được chỉ định (ví dụ: `./data/cold_storage`).
    5.  Script được tích hợp vào DAG trong Airflow từ Story 2.1.

#### **Story 2.3: Cài đặt ClickHouse và truy vấn dữ liệu Parquet**
* **Là một** nhà phân tích dữ liệu, **tôi muốn** một môi trường ClickHouse có thể truy vấn trực tiếp các file Parquet từ cold storage, **để** có thể thực hiện các truy vấn phân tích nhanh trên dữ liệu lịch sử.
* **Tiêu chí chấp nhận:**
    1.  ClickHouse được thêm như một service mới vào file `docker-compose.yml`.
    2.  ClickHouse được cấu hình để có thể đọc dữ liệu từ thư mục chứa file Parquet.
    3.  Người dùng có thể kết nối tới ClickHouse và chạy thành công một câu lệnh SQL (ví dụ: `SELECT COUNT(*)`) trên dữ liệu Parquet đã được lưu trữ.

#### **Story 2.4: Hoàn thiện tài liệu hướng dẫn và script hỗ trợ**
* **Là một** người dùng mới, **tôi muốn** một tài liệu `README.md` toàn diện, giải thích kiến trúc và cung cấp hướng dẫn từng bước, **để** có thể tự mình triển khai và sử dụng thành công toàn bộ hệ thống.
* **Tiêu chí chấp nhận:**
    1.  File `README.md` được cập nhật để bao gồm hướng dẫn cài đặt và vận hành cho tất cả các thành phần (Go client, Airflow, ClickHouse).
    2.  Tài liệu giải thích rõ luồng dữ liệu từ hot path sang cold path.
    3.  Cung cấp các đoạn code/câu lệnh mẫu để truy vấn dữ liệu từ Redis, TimescaleDB, và ClickHouse.
    4.  Cách sử dụng script benchmark từ Epic 1 được ghi lại rõ ràng.