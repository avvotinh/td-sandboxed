# Tech-Spec: Epic 2 - Adapters & External Integration

**Created:** 2025-12-03
**Status:** Ready for Development
**Epic:** 2 - Adapters & External Integration
**Service:** trading-engine (Python/Nautilus Trader)

---

## Overview

### Problem Statement

The trading-engine needs to connect to external systems (Redis, TimescaleDB, ZeroMQ) to receive market data and execute orders. These integrations must be abstracted through clean adapter interfaces that can be mocked for testing.

### Solution

Create adapter classes following Nautilus Trader patterns:
- **RedisDataAdapter** - Subscribe to OHLCV candles from tv-api via Redis Pub/Sub
- **TimescaleDBAdapter** - Load historical data and persist trades/audit logs
- **ZMQExecutionAdapter** - Send orders to mt5-bridge and receive tick data via ZeroMQ
- **Mock Adapters** - Test doubles for all adapters enabling isolated testing
- **DataValidator** - Validate data quality (gaps, anomalies, timestamps)

### Scope

**In Scope:**
- Redis async client with Pub/Sub subscription and reconnection logic
- TimescaleDB async client with connection pooling
- ZeroMQ REQ/REP and PUB/SUB patterns for MT5 bridge
- Mock adapters implementing same interfaces
- Data quality validation (gaps, anomalies, timestamps)
- Conversion to Nautilus Bar/QuoteTick objects

**Out of Scope:**
- FTMO compliance logic (Epic 3)
- Strategy execution (Epic 4)
- Backtesting engine (Epic 5)

---

## Context for Development

### Codebase Patterns

**From Architecture Document (Section: Inter-Service Communication):**

```
Communication Matrix:
| From           | To              | Protocol    | Port | Data           |
|----------------|-----------------|-------------|------|----------------|
| tv-api         | Redis           | Redis PUB   | 6379 | OHLCV Candles  |
| mt5-bridge     | trading-engine  | ZeroMQ PUB  | 5556 | Tick Data      |
| trading-engine | mt5-bridge      | ZeroMQ REQ  | 5557 | Order Commands |
| trading-engine | TimescaleDB     | PostgreSQL  | 5432 | Trades, Audit  |
```

**Directory Structure:**
```
services/trading-engine/src/
├── adapters/
│   ├── __init__.py
│   ├── base.py              # Abstract base classes
│   ├── redis_adapter.py     # Redis data adapter
│   ├── timescale_adapter.py # TimescaleDB adapter
│   ├── zmq_adapter.py       # ZeroMQ execution adapter
│   └── mock/
│       ├── __init__.py
│       ├── mock_redis.py
│       ├── mock_timescale.py
│       └── mock_zmq.py
├── data/
│   ├── __init__.py
│   └── validator.py         # Data quality validation
```

### Files to Reference

| File | Purpose |
|------|---------|
| `docs/architecture.md` | Section: Inter-Service Communication, Redis Pub/Sub Channels |
| `docs/epics-trading-engine.md` | Stories 2.1-2.5 acceptance criteria |
| `services/tv-api/internal/store/redis.go` | Pattern reference for Redis channel naming |
| `services/tv-api/internal/store/timescaledb.go` | Pattern reference for TimescaleDB schema |

### Technical Decisions

#### TD-1: redis-py Async with Pub/Sub

**Decision:** Use `redis.asyncio` for async Redis operations with Pub/Sub

**Rationale (from Context7 research):**
- Native async/await support
- Built-in Pub/Sub with pattern subscriptions
- Automatic reconnection capabilities
- High benchmark score (89.9)

**Implementation Pattern:**

```python
import asyncio
import redis.asyncio as redis
from typing import Callable, Any

class RedisDataAdapter:
    def __init__(self, url: str):
        self._url = url
        self._client: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._running = False

    async def connect(self) -> None:
        self._client = redis.from_url(self._url)
        self._pubsub = self._client.pubsub()

    async def disconnect(self) -> None:
        if self._pubsub:
            await self._pubsub.close()
        if self._client:
            await self._client.close()

    async def subscribe_bars(
        self,
        symbol: str,
        timeframe: str,
        callback: Callable[[dict], Any]
    ) -> None:
        channel = f"bars:{symbol}:{timeframe}"
        await self._pubsub.subscribe(channel)

        async def reader():
            while self._running:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0
                )
                if message and message["type"] == "message":
                    data = json.loads(message["data"])
                    await callback(data)

        self._running = True
        asyncio.create_task(reader())
```

#### TD-2: asyncpg for TimescaleDB

**Decision:** Use `asyncpg` for high-performance async PostgreSQL access

**Rationale (from Context7 research):**
- Fastest Python PostgreSQL driver
- Native async/await support
- Connection pooling built-in
- Efficient binary protocol
- Bulk insert via COPY

**Implementation Pattern:**

```python
import asyncpg
from datetime import datetime
from decimal import Decimal

class TimescaleDBAdapter:
    def __init__(self, dsn: str, min_pool: int = 2, max_pool: int = 10):
        self._dsn = dsn
        self._min_pool = min_pool
        self._max_pool = max_pool
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min_pool,
            max_size=self._max_pool,
            command_timeout=60,
        )

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()

    async def load_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                '''
                SELECT time, open, high, low, close, volume
                FROM candles
                WHERE symbol = $1 AND timeframe = $2
                  AND time >= $3 AND time < $4
                ORDER BY time ASC
                ''',
                symbol, timeframe, start, end
            )
            return [dict(row) for row in rows]

    async def save_trade(self, trade: dict) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                '''
                INSERT INTO trades (
                    trade_id, strategy_name, symbol, side, quantity,
                    entry_price, entry_time, exit_price, exit_time,
                    pnl_dollars, pnl_percent, slippage, signal_reason, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ''',
                *trade.values()
            )

    async def save_audit_log(self, log: dict) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                '''
                INSERT INTO audit_logs (
                    log_id, timestamp, event_type, rule_name, rule_result,
                    current_value, threshold_value, order_id, context
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ''',
                *log.values()
            )
```

#### TD-3: pyzmq Async for MT5 Bridge

**Decision:** Use `zmq.asyncio` for async ZeroMQ communication

**Rationale (from Context7 research):**
- Native asyncio integration
- REQ/REP for order submission (synchronous acknowledgment)
- SUB for tick data streaming
- Topic-based filtering

**Implementation Pattern:**

```python
import zmq
import zmq.asyncio
import json
from typing import Callable

class ZMQExecutionAdapter:
    def __init__(self, host: str, pub_port: int, sub_port: int):
        self._host = host
        self._pub_port = pub_port
        self._sub_port = sub_port
        self._ctx: zmq.asyncio.Context | None = None
        self._req_socket: zmq.asyncio.Socket | None = None
        self._sub_socket: zmq.asyncio.Socket | None = None

    async def connect(self) -> None:
        self._ctx = zmq.asyncio.Context()

        # REQ socket for order submission
        self._req_socket = self._ctx.socket(zmq.REQ)
        self._req_socket.connect(f"tcp://{self._host}:{self._pub_port}")
        self._req_socket.setsockopt(zmq.RCVTIMEO, 2000)  # 2s timeout

        # SUB socket for tick data
        self._sub_socket = self._ctx.socket(zmq.SUB)
        self._sub_socket.connect(f"tcp://{self._host}:{self._sub_port}")

    async def disconnect(self) -> None:
        if self._req_socket:
            self._req_socket.close()
        if self._sub_socket:
            self._sub_socket.close()
        if self._ctx:
            self._ctx.term()

    async def submit_order(self, order: dict) -> dict:
        message = json.dumps(order).encode()
        await self._req_socket.send(message)
        response = await self._req_socket.recv()
        return json.loads(response)

    async def subscribe_ticks(
        self,
        symbol: str,
        callback: Callable[[dict], None]
    ) -> None:
        self._sub_socket.setsockopt(zmq.SUBSCRIBE, symbol.encode())

        async def reader():
            while True:
                msg = await self._sub_socket.recv_multipart()
                topic = msg[0].decode()
                data = json.loads(msg[1])
                await callback(data)

        asyncio.create_task(reader())
```

#### TD-4: Nautilus Data Conversion

**Decision:** Convert external data to Nautilus Bar and QuoteTick objects

**Rationale:**
- Nautilus strategies expect specific data types
- Consistent interface for backtest and live
- Type safety and validation

**Implementation Pattern:**

```python
from nautilus_trader.model.data import Bar, BarType, QuoteTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity

def convert_to_bar(data: dict, bar_type: BarType) -> Bar:
    return Bar(
        bar_type=bar_type,
        open=Price.from_str(str(data["open"])),
        high=Price.from_str(str(data["high"])),
        low=Price.from_str(str(data["low"])),
        close=Price.from_str(str(data["close"])),
        volume=Quantity.from_str(str(data["volume"])),
        ts_event=pd.Timestamp(data["timestamp"]).value,
        ts_init=pd.Timestamp(data["timestamp"]).value,
    )

def convert_to_quote_tick(data: dict, instrument_id: InstrumentId) -> QuoteTick:
    return QuoteTick(
        instrument_id=instrument_id,
        bid_price=Price.from_str(str(data["bid"])),
        ask_price=Price.from_str(str(data["ask"])),
        bid_size=Quantity.from_int(1),
        ask_size=Quantity.from_int(1),
        ts_event=pd.Timestamp(data["timestamp"]).value,
        ts_init=pd.Timestamp(data["timestamp"]).value,
    )
```

#### TD-5: Exponential Backoff Reconnection

**Decision:** Implement exponential backoff for all adapter reconnections

**Rationale:**
- Prevents thundering herd on service recovery
- Graceful handling of transient failures
- Configurable max retry duration

**Implementation Pattern:**

```python
import asyncio
from typing import Callable

async def reconnect_with_backoff(
    connect_fn: Callable,
    max_delay: float = 30.0,
    max_duration: float = 300.0,
) -> bool:
    delay = 1.0
    elapsed = 0.0

    while elapsed < max_duration:
        try:
            await connect_fn()
            return True
        except Exception as e:
            logger.warning(f"Connection failed: {e}, retrying in {delay}s")
            await asyncio.sleep(delay)
            elapsed += delay
            delay = min(delay * 2, max_delay)

    return False
```

---

## Implementation Plan

### Tasks

#### Story 2.1: Redis Data Adapter

- [ ] **Task 2.1.1:** Create `src/adapters/base.py` with abstract `DataAdapter` base class
- [ ] **Task 2.1.2:** Create `src/adapters/redis_adapter.py` with `RedisDataAdapter` class
- [ ] **Task 2.1.3:** Implement `connect()` and `disconnect()` methods
- [ ] **Task 2.1.4:** Implement `subscribe_bars(symbol, timeframe, callback)` with Redis Pub/Sub
- [ ] **Task 2.1.5:** Parse JSON messages from channel `bars:{symbol}:{timeframe}`
- [ ] **Task 2.1.6:** Convert to Nautilus `Bar` objects
- [ ] **Task 2.1.7:** Implement exponential backoff reconnection
- [ ] **Task 2.1.8:** Handle invalid message format gracefully (log and continue)
- [ ] **Task 2.1.9:** Write unit tests for message parsing and conversion

#### Story 2.2: TimescaleDB Adapter

- [ ] **Task 2.2.1:** Create `src/adapters/timescale_adapter.py` with `TimescaleDBAdapter` class
- [ ] **Task 2.2.2:** Implement connection pooling (min 2, max 10 connections)
- [ ] **Task 2.2.3:** Implement `load_bars(symbol, timeframe, start, end)` returning Nautilus Bars
- [ ] **Task 2.2.4:** Implement `load_trades(start, end, strategy=None)` for trade history
- [ ] **Task 2.2.5:** Implement `save_trade(trade)` for trade persistence
- [ ] **Task 2.2.6:** Implement `save_audit_log(log)` for compliance audit trail
- [ ] **Task 2.2.7:** Implement `save_performance_metrics(metrics)` for daily stats
- [ ] **Task 2.2.8:** Ensure query performance < 30 seconds for 2 years of 1m data (indexed)
- [ ] **Task 2.2.9:** Write unit tests with mock database

#### Story 2.3: ZeroMQ Execution Adapter

- [ ] **Task 2.3.1:** Create `src/adapters/zmq_adapter.py` with `ZMQExecutionAdapter` class
- [ ] **Task 2.3.2:** Implement REQ socket for order submission (port 5557)
- [ ] **Task 2.3.3:** Implement SUB socket for tick data (port 5556)
- [ ] **Task 2.3.4:** Implement `submit_order(order)` with 2-second timeout
- [ ] **Task 2.3.5:** Parse order result JSON (status, fill_price, slippage)
- [ ] **Task 2.3.6:** Implement `subscribe_ticks(symbol, callback)` with topic filtering
- [ ] **Task 2.3.7:** Convert tick data to Nautilus `QuoteTick` objects
- [ ] **Task 2.3.8:** Implement order queue and retry logic (max 3 attempts)
- [ ] **Task 2.3.9:** Write unit tests for order submission and tick parsing

#### Story 2.4: Mock Adapters for Testing

- [ ] **Task 2.4.1:** Create `src/adapters/mock/__init__.py` exporting all mocks
- [ ] **Task 2.4.2:** Create `MockRedisAdapter` implementing same interface
- [ ] **Task 2.4.3:** Add `inject_bar(bar_data)` method for test data injection
- [ ] **Task 2.4.4:** Create `MockTimescaleAdapter` with configurable test data
- [ ] **Task 2.4.5:** Add `set_historical_data(bars)` for backtest data
- [ ] **Task 2.4.6:** Create `MockZMQAdapter` with configurable responses
- [ ] **Task 2.4.7:** Add `set_fill_response(response)` for order simulation
- [ ] **Task 2.4.8:** Add `inject_tick(tick_data)` for tick simulation
- [ ] **Task 2.4.9:** Add failure injection methods for error testing
- [ ] **Task 2.4.10:** Create pytest fixtures in `tests/conftest.py`

#### Story 2.5: Data Quality Validation

- [ ] **Task 2.5.1:** Create `src/data/validator.py` with `DataValidator` class
- [ ] **Task 2.5.2:** Implement gap detection (configurable threshold, default 5 min for 1m data)
- [ ] **Task 2.5.3:** Return `DataQualityWarning` with gap details
- [ ] **Task 2.5.4:** Implement anomaly detection (price jumps > 10x previous)
- [ ] **Task 2.5.5:** Return `AnomalyDetected` alert with anomaly details
- [ ] **Task 2.5.6:** Implement timestamp validation (no future dates, no duplicates)
- [ ] **Task 2.5.7:** Return `TimestampError` for invalid timestamps
- [ ] **Task 2.5.8:** Implement data source fallback (use cached for backtest, pause for live)
- [ ] **Task 2.5.9:** Write comprehensive unit tests for all validation rules

---

### Acceptance Criteria

#### Story 2.1: Redis Data Adapter

- [ ] **AC 2.1.1:** Given Redis is running with candle data published, When I subscribe to channel `bars:GOLD:1m`, Then I receive OHLCV data as Nautilus Bar events
- [ ] **AC 2.1.2:** Given a message is received, Then it is parsed from JSON with fields: symbol, timeframe, timestamp, open, high, low, close, volume
- [ ] **AC 2.1.3:** Given Redis connection is lost, When connection is restored, Then adapter automatically reconnects and resubscribes
- [ ] **AC 2.1.4:** Given invalid message format received, When parsing fails, Then error is logged but adapter continues operating

#### Story 2.2: TimescaleDB Adapter

- [ ] **AC 2.2.1:** Given TimescaleDB has historical candle data, When I call `load_bars("GOLD", "1m", start, end)`, Then I receive a list of Nautilus Bar objects
- [ ] **AC 2.2.2:** Given I request 2 years of 1-minute data, When the query executes, Then it completes in < 30 seconds
- [ ] **AC 2.2.3:** Given a trade is executed, When I call `save_trade(trade)`, Then the trade is persisted to `trades` table
- [ ] **AC 2.2.4:** Given a compliance check occurs, When I call `save_audit_log(log)`, Then the audit entry is persisted (append-only)

#### Story 2.3: ZeroMQ Execution Adapter

- [ ] **AC 2.3.1:** Given mt5-bridge is running, When I call `submit_order(order)`, Then a ZeroMQ message is sent with type, action, symbol, volume, order_id
- [ ] **AC 2.3.2:** Given mt5-bridge responds, When order is filled, Then I receive order result with status, fill_price, slippage
- [ ] **AC 2.3.3:** Given I subscribe to tick data, When mt5-bridge publishes ticks, Then I receive QuoteTick events
- [ ] **AC 2.3.4:** Given ZeroMQ connection fails, When sending order, Then order is queued and retried (max 3 attempts)

#### Story 2.4: Mock Adapters for Testing

- [ ] **AC 2.4.1:** Given I run unit tests, When using MockRedisAdapter, Then I can simulate receiving bar data
- [ ] **AC 2.4.2:** Given MockZMQAdapter is used, When I submit an order, Then I can simulate fill responses with configurable slippage
- [ ] **AC 2.4.3:** Given MockTimescaleAdapter is used, When I load historical data, Then I receive pre-configured test data

#### Story 2.5: Data Quality Validation

- [ ] **AC 2.5.1:** Given I load historical data, When there are gaps > 5 minutes in 1m data, Then I receive a DataQualityWarning with gap details
- [ ] **AC 2.5.2:** Given a price is impossible (negative or 10x previous), When validation runs, Then I receive an AnomalyDetected alert
- [ ] **AC 2.5.3:** Given timestamps are inconsistent (future dates, duplicates), When validation runs, Then I receive a TimestampError
- [ ] **AC 2.5.4:** Given data source is unavailable, When I try to load data, Then I use cached data (for backtest) or pause trading (for live)

---

## Additional Context

### Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| redis | >= 5.0.0 | Async Redis client with Pub/Sub |
| asyncpg | >= 0.29.0 | High-performance async PostgreSQL |
| pyzmq | >= 25.0.0 | ZeroMQ async bindings |
| nautilus_trader | >= 1.200.0 | Bar, QuoteTick data types |

### Message Formats

**Redis Bar Message (from tv-api):**
```json
{
  "symbol": "GOLD",
  "timeframe": "1m",
  "timestamp": "2025-12-03T14:32:00Z",
  "open": 1850.25,
  "high": 1851.00,
  "low": 1849.50,
  "close": 1850.75,
  "volume": 1234
}
```

**ZeroMQ Order Command:**
```json
{
  "type": "order",
  "action": "BUY",
  "symbol": "XAUUSD",
  "volume": 0.1,
  "order_id": "ORDER-123"
}
```

**ZeroMQ Order Result:**
```json
{
  "type": "order_result",
  "order_id": "ORDER-123",
  "status": "filled",
  "fill_price": 1850.47,
  "slippage": 0.02,
  "timestamp": "2025-12-03T14:32:15.456Z"
}
```

**ZeroMQ Tick Data:**
```json
{
  "type": "tick",
  "symbol": "XAUUSD",
  "bid": 1850.25,
  "ask": 1850.45,
  "timestamp": "2025-12-03T14:32:15.123Z"
}
```

### Redis Pub/Sub Channels

| Channel Pattern | Publisher | Data |
|-----------------|-----------|------|
| `bars:GOLD:1m` | tv-api | 1-minute OHLCV candles |
| `bars:BTC:5m` | tv-api | 5-minute OHLCV candles |
| `bars:{symbol}:{timeframe}` | tv-api | Generic bar data |

### TimescaleDB Schema Reference

```sql
-- Candles (from Architecture)
CREATE TABLE candles (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,
    open DECIMAL(18, 5) NOT NULL,
    high DECIMAL(18, 5) NOT NULL,
    low DECIMAL(18, 5) NOT NULL,
    close DECIMAL(18, 5) NOT NULL,
    volume DECIMAL(18, 2)
);
CREATE INDEX idx_candles_symbol_time ON candles (symbol, time DESC);

-- Trades
CREATE TABLE trades (
    trade_id UUID PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL,
    quantity DECIMAL(18, 8) NOT NULL,
    entry_price DECIMAL(18, 5) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_price DECIMAL(18, 5),
    exit_time TIMESTAMPTZ,
    pnl_dollars DECIMAL(18, 2),
    pnl_percent DECIMAL(8, 4),
    slippage DECIMAL(18, 5),
    signal_reason TEXT,
    metadata JSONB
);

-- Audit Logs
CREATE TABLE audit_logs (
    log_id UUID PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    rule_name VARCHAR(100),
    rule_result VARCHAR(20),
    current_value DECIMAL(18, 4),
    threshold_value DECIMAL(18, 4),
    order_id UUID,
    context JSONB
);
```

### Testing Strategy

1. **Unit Tests (All Stories):**
   - Message parsing and conversion
   - Validation rules
   - Mock adapter behavior
   - Error handling

2. **Integration Tests (Stories 2.1-2.3):**
   - Real Redis connection (Docker)
   - Real TimescaleDB connection (Docker)
   - ZeroMQ with mock bridge

3. **Test Fixtures:**
   ```python
   # tests/conftest.py
   import pytest
   from src.adapters.mock import MockRedisAdapter, MockTimescaleAdapter, MockZMQAdapter

   @pytest.fixture
   def mock_redis():
       return MockRedisAdapter()

   @pytest.fixture
   def mock_timescale():
       adapter = MockTimescaleAdapter()
       adapter.set_historical_data([...])
       return adapter

   @pytest.fixture
   def mock_zmq():
       adapter = MockZMQAdapter()
       adapter.set_fill_response({"status": "filled", "fill_price": 1850.47})
       return adapter
   ```

### Notes

- **Adapter Pattern:** All adapters implement abstract base class for consistent interface
- **Async First:** All I/O operations use async/await
- **Reconnection:** Built-in exponential backoff for all external connections
- **Logging:** All adapter events logged with structlog (from Epic 1)
- **Error Handling:** Failures logged but don't crash - graceful degradation
- **Dependency on Epic 1:** Requires configuration system and logging from Epic 1

---

## File Structure Summary

```
services/trading-engine/src/
├── adapters/
│   ├── __init__.py              # Export all adapters
│   ├── base.py                  # Abstract DataAdapter, ExecutionAdapter
│   ├── redis_adapter.py         # RedisDataAdapter
│   ├── timescale_adapter.py     # TimescaleDBAdapter
│   ├── zmq_adapter.py           # ZMQExecutionAdapter
│   └── mock/
│       ├── __init__.py          # Export all mocks
│       ├── mock_redis.py        # MockRedisAdapter
│       ├── mock_timescale.py    # MockTimescaleAdapter
│       └── mock_zmq.py          # MockZMQAdapter
├── data/
│   ├── __init__.py
│   ├── converter.py             # convert_to_bar, convert_to_quote_tick
│   └── validator.py             # DataValidator
```

---

_Tech-Spec generated via YOLO mode workflow execution._
_Source: Epic 2 from docs/epics-trading-engine.md_
_Research: Context7 documentation for redis-py, asyncpg, pyzmq, Nautilus Trader adapters_
