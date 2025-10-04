# **Phần 11: Chiến lược Xử lý lỗi (Error Handling Strategy)**

  * **Logging:** Định dạng JSON, sử dụng `slog` cho Go và `logging` cho Python.
  * **Retry:** Ingestion client phải có cơ chế retry với exponential backoff khi kết nối tới TradingView.
  * **Idempotency:** Tác vụ xử lý lô của Airflow phải được thiết kế để chạy lại nhiều lần mà không tạo dữ liệu trùng lặp.
