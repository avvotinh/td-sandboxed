# **HFT Data Lakehouse Blueprint - Product Requirements Document (PRD)**

## **Phần 1: Mục tiêu và Bối cảnh (Goals and Background Context)**

#### **Mục tiêu (Goals)**

* **Về sản phẩm:** Tạo ra một bản thiết kế kiến trúc hoàn chỉnh, sẵn sàng để triển khai cho một hệ thống data lakehouse HFT.
* **Về hiệu năng:** Đảm bảo hệ thống sau khi triển khai đạt được độ trễ truy vấn dữ liệu nóng dưới 20ms.
* **Về người dùng:** Cung cấp một hướng dẫn triển khai rõ ràng, cho phép người dùng có kỹ thuật có thể cài đặt toàn bộ hệ thống trong vòng 8 giờ.
* **Về chi phí:** Chứng minh kiến trúc này có tổng chi phí sở hữu (TCO) thấp hơn đáng kể so với các giải pháp thương mại.
* **Về cộng đồng:** Xây dựng một dự án mã nguồn mở thu hút được sự quan tâm và đóng góp từ cộng đồng các nhà giao dịch thuật toán.

#### **Bối cảnh (Background Context)**

Dự án này ra đời từ nhu cầu thực tế của các nhà giao dịch thuật toán cá nhân và nhóm nhỏ, những người thiếu khả năng tiếp cận một hạ tầng dữ liệu chuyên nghiệp, chi phí cao và độ trễ lớn là rào cản chính. Bằng cách cung cấp một bản thiết kế kiến trúc mã nguồn mở, hiệu năng cao, dự án này nhằm mục đích dân chủ hóa công cụ giao dịch HFT, cho phép các nhà giao dịch độc lập tập trung vào việc phát triển chiến lược thay vì phải vật lộn với hạ tầng.

#### **Nhật ký thay đổi (Change Log)**

| Ngày | Phiên bản | Mô tả | Tác giả |
| :--- | :--- | :--- | :--- |
| 01/10/2025 | 1.1 | Bổ sung NFR6, NFR7 | John (PM) |
| 01/10/2025 | 1.0 | Tạo bản nháp đầu tiên | John (PM) |

## **Phần 2: Yêu cầu (Requirements)**

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

## **Phần 3: Các giả định kỹ thuật (Technical Assumptions)**

* **Cấu trúc Repository:** **Monorepo**
* **Kiến trúc Dịch vụ:** **Kiến trúc lai (Hybrid Architecture)**
* **Yêu cầu về Kiểm thử (Testing):** **Unit Test + Integration Test**
* **Các giả định và yêu cầu kỹ thuật bổ sung**
    * **Ngôn ngữ:** Go (cho Ingestion), Python (cho Processing).
    * **Lưu trữ nóng (Hot Storage):** Redis + TimescaleDB.
    * **Lưu trữ lạnh (Cold Storage):** File Parquet + ClickHouse.
    * **Điều phối (Orchestration):** Apache Airflow.
    * **Triển khai MVP:** Docker Compose.
    * **Tích hợp:** Các ứng dụng kết nối trực tiếp đến database.

## **Phần 4: Danh sách Epic (Epic List)**

1.  **Epic 1: Nền tảng và Luồng dữ liệu nóng (Foundation & Hot Path)**
    * **Mục tiêu:** Thiết lập toàn bộ hạ tầng cơ bản của dự án, triển khai module thu thập dữ liệu, và xây dựng luồng lưu trữ/truy vấn dữ liệu nóng (hot path) để đáp ứng yêu cầu giao dịch real-time.
2.  **Epic 2: Luồng dữ liệu lạnh và Hoàn thiện (Cold Path & Finalization)**
    * **Mục tiêu:** Xây dựng luồng xử lý và lưu trữ dữ liệu lạnh (cold path) cho mục đích backtesting và AI, đồng thời hoàn thiện tài liệu hướng dẫn và các script hỗ trợ.

## **Phần 5: Chi tiết Epic 1: Nền tảng và Luồng dữ liệu nóng**

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

## **Phần 6: Chi tiết Epic 2: Luồng dữ liệu lạnh và Hoàn thiện**

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