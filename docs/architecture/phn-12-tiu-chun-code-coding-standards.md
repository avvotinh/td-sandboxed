# **Phần 12: Tiêu chuẩn code (Coding Standards)**

  * **Core:** Tuân thủ `go fmt` và `black`/`ruff`. Test file đặt cạnh file code.
  * **Critical Rules:**
    1.  Không truy cập trực tiếp biến môi trường.
    2.  Không hardcode credentials.
    3.  Chỉ dùng structured logging.
    4.  Truy cập database qua Repository Pattern.
    5.  Sử dụng `context.Context` trong Go cho các tác vụ I/O.
