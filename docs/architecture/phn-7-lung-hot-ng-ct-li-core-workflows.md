# **Phần 7: Luồng hoạt động cốt lõi (Core Workflows)**

Sơ đồ tuần tự minh họa luồng thu thập và truy vấn dữ liệu real-time:

```mermaid
sequenceDiagram
    participant Bot as Trading Bot
    participant Client as Ingestion Client (Go)
    participant TV as TradingView WS
    participant Redis
    participant TimescaleDB

    Client->>TV: 1. Kết nối & Xác thực
    Client->>TV: 2. Gửi yêu cầu Subscribe ('BTCUSD')
    loop Liên tục nhận dữ liệu
        TV-->>Client: 3. Đẩy dữ liệu Tick ('BTCUSD')
        par
            Client->>Redis: 4a. Ghi giá mới nhất (SET)
        and
            Client->>TimescaleDB: 4b. Ghi đầy đủ dữ liệu tick (INSERT)
        end
    end
    
    Bot->>Redis: 5. Truy vấn giá mới nhất (GET)
    Redis-->>Bot: 6. Trả về giá <20ms
```

***Ghi chú:*** *Bước 4a và 4b được thực hiện đồng thời (concurrently) bằng goroutines trong Go để đảm bảo việc ghi vào TimescaleDB không làm chậm việc ghi vào Redis.*
