# **Phần 6: Các API bên ngoài (External APIs)**

  * **API:** TradingView WebSocket API
  * **Mục đích:** Nguồn dữ liệu real-time duy nhất cho toàn bộ hệ thống.
  * **Xác thực:** Sử dụng `username` và `password` của tài khoản TradingView, quản lý qua biến môi trường.
  * **Các Endpoint chính:**
      * **WebSocket URL:** `wss://data.tradingview.com/socket.io/websocket`
      * **Symbol Search API:** `https://symbol-search.tradingview.com/symbol_search`
      * **Sign-in URL:** `https://www.tradingview.com/accounts/signin/`
