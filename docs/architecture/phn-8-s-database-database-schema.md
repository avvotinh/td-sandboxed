# **Phần 8: Sơ đồ Database (Database Schema)**

#### **1. TimescaleDB**

```sql
CREATE TABLE ticks (
    "time" TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    bid DECIMAL,
    ask DECIMAL,
    price DECIMAL,
    volume DECIMAL
);
SELECT create_hypertable('ticks', 'time');

CREATE TABLE candles (
    "time" TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    open DECIMAL,
    high DECIMAL,
    low DECIMAL,
    close DECIMAL,
    volume DECIMAL
);
SELECT create_hypertable('candles', 'time');

CREATE INDEX ON ticks (symbol, "time" DESC);
CREATE INDEX ON candles (symbol, interval, "time" DESC);
```

#### **2. Redis**

  * **Cấu trúc key:** `latest_tick:{symbol}` (Ví dụ: `latest_tick:BTCUSD`)
  * **Loại dữ liệu:** **Hash** (chứa các trường: `bid`, `ask`, `price`, `volume`, `timestamp`).

#### **3. ClickHouse**

```sql
CREATE TABLE ticks_cold (
    `time` DateTime64(9, 'UTC'),
    `symbol` String,
    `bid` Decimal(18, 8),
    `ask` Decimal(18, 8),
    `price` Decimal(18, 8),
    `volume` Decimal(18, 8)
) ENGINE = S3('path/to/data/*.parquet', 'Parquet');
```
