# **Phần 3: Các giả định kỹ thuật (Technical Assumptions)**

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
