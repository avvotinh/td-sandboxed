# **Phần 4: Mô hình Dữ liệu (Data Models)**

#### **Mô hình 1: Dữ liệu Tick (TickData)**

  * **Mục đích:** Lưu trữ mọi biến động giá nhỏ nhất của một symbol, bao gồm cả giá mua/bán tốt nhất, cung cấp dữ liệu có độ phân giải cao nhất.
  * **Các thuộc tính chính:**
      * `timestamp` (timestamptz): Thời gian chính xác của tick.
      * `symbol` (text): Mã giao dịch (ví dụ: 'BTCUSD').
      * `bid` (decimal): Giá mua tốt nhất.
      * `ask` (decimal): Giá bán tốt nhất.
      * `price` (decimal): Giá khớp lệnh cuối cùng (có thể không có ở mọi tick).
      * `volume` (decimal): Khối lượng giao dịch của tick đó (nếu có).
  * **Mối quan hệ:** Một `TickData` thuộc về một `Symbol`.

#### **Mô hình 2: Dữ liệu Nến (CandlestickData)**

  * **Mục đích:** Lưu trữ dữ liệu thị trường đã được tổng hợp (Mở, Cao, Thấp, Đóng, Khối lượng) theo các khung thời gian cụ thể (1M, 5M, 1H, etc.).
  * **Các thuộc tính chính:**
      * `timestamp` (timestamptz): Thời gian bắt đầu của khung thời gian của nến.
      * `symbol` (text): Mã giao dịch.
      * `interval` (text): Khung thời gian của nến (ví dụ: '1M', '5M', '1H').
      * `open` (decimal): Giá mở cửa.
      * `high` (decimal): Giá cao nhất.
      * `low` (decimal): Giá thấp nhất.
      * `close` (decimal): Giá đóng cửa.
      * `volume` (decimal): Tổng khối lượng giao dịch.
  * **Mối quan hệ:** Một `CandlestickData` thuộc về một `Symbol` và một `Interval`.
