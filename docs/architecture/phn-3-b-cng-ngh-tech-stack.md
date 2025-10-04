# **Phần 3: Bộ công nghệ (Tech Stack)**

#### **Hạ tầng (Infrastructure)**

  * **Nền tảng:** Tự host (Self-hosted)
  * **Mô hình triển khai MVP:** Sử dụng Docker và Docker Compose trên một hoặc nhiều máy chủ Linux.

#### **Bảng Công nghệ (Technology Stack Table)**

| Hạng mục | Công nghệ | Phiên bản (Đề xuất) | Mục đích | Lý do |
| :--- | :--- | :--- | :--- | :--- |
| **Ngôn ngữ** | Golang | 1.2x.x | Xây dựng Ingestion Client | Hiệu năng cao, xử lý đồng thời tốt (NFR4). |
| **Ngôn ngữ** | Python | 3.1x.x | Viết script cho Airflow | Hệ sinh thái mạnh cho xử lý dữ liệu (Pandas/Polars). |
| **Hot Storage**| Redis | 7.x | Cache dữ liệu tick mới nhất | Tốc độ truy vấn key-value cực nhanh (NFR1). |
| **Hot Storage**| TimescaleDB | 2.x (trên PostgreSQL 16) | Lưu dữ liệu nóng ngắn hạn | Tối ưu cho truy vấn chuỗi thời gian, dùng SQL (FR6). |
| **Cold Storage**| ClickHouse | 24.x | Query Engine cho dữ liệu lạnh | Tốc độ truy vấn phân tích vượt trội trên dữ liệu lớn (FR5). |
| **Orchestration**| Apache Airflow | 2.x.x | Điều phối pipeline xử lý lô | Chuẩn công nghiệp, linh hoạt, mã nguồn mở (FR4). |
| **Kiểm thử** | Pytest | 8.x | Unit/Integration test cho Python | Framework kiểm thử mạnh mẽ và phổ biến cho Python. |
| **Triển khai** | Docker / Docker Compose | 26.x / 2.x | Đóng gói và vận hành | Đảm bảo tính nhất quán và đơn giản hóa việc triển khai (NFR2). |
