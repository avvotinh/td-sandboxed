# **Phần 5: Các thành phần (Components)**

  * **1. Ingestion Client:** Dùng Go, kết nối tới TradingView WebSocket, nhận, phân tích và chuyển tiếp dữ liệu tới Hot Storage.
  * **2. Real-time Cache:** Dùng Redis, chỉ lưu trữ giá trị tick mới nhất cho mỗi symbol để bot đọc cực nhanh.
  * **3. Short-term Store:** Dùng TimescaleDB, lưu trữ lịch sử dữ liệu nóng ngắn hạn (vài ngày) cho phân tích.
  * **4. Batch Processing Orchestrator:** Dùng Apache Airflow, quản lý và lên lịch cho tác vụ ETL.
  * **5. Processing Script:** Dùng Python, chứa logic ETL đọc từ TimescaleDB và ghi ra file Parquet.
  * **6. Analytical Query Engine:** Dùng ClickHouse, cung cấp giao diện SQL để truy vấn các file Parquet trong Cold Storage.
