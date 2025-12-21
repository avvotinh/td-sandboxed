# Story 2.4: Trading Engine ZeroMQ Adapter

Status: review

## Story

As a **trading engine developer**,
I want **a Python ZeroMQ adapter for bidirectional communication with mt5-bridge**,
So that **the trading engine can receive tick data and send order commands to MT5**.

## Acceptance Criteria

1. **AC1**: Given the adapter is initialized, when it connects to mt5-bridge, then it establishes SUB socket on port 5556 for tick data and PUB socket on port 5557 for orders
2. **AC2**: Given the SUB socket is connected, when tick messages arrive with topic `tick:{symbol}`, then ticks are parsed into Tick dataclass and yielded via async iterator
3. **AC3**: Given the PUB socket is bound, when `send_order()` is called, then the order JSON is published with topic `order:{account_id}`
4. **AC4**: Given a connection failure occurs, when the adapter detects disconnection, then it attempts reconnection with exponential backoff (1s, 2s, 4s, 8s, 16s, 30s max)
5. **AC5**: Given ticks are received, when the adapter routes them, then each tick is delivered to the appropriate account based on `account_id` field
6. **AC6**: Given the adapter sends an order, when a result is received on SUB socket topic `order_result:{order_id}`, then the result is correlated and returned
7. **AC7**: Unit tests cover socket operations, message parsing, and reconnection logic with mock ZMQ sockets
8. **AC8**: Integration tests verify end-to-end communication with running mt5-bridge

## Tasks / Subtasks

### Task 1: Create ZmqAdapter Class Structure (AC: 1)
- [x] Create `src/adapters/zmq_adapter.py` with `ZmqAdapter` class
- [x] Define `ZmqConfig` Pydantic model with host, ports, timeouts
- [x] Initialize `zmq.asyncio.Context` as class attribute
- [x] Create SUB socket for tick data (port 5556)
- [x] Create PUB socket for order commands (port 5557)
- [x] Add socket options: ZMQ_RCVTIMEO, ZMQ_SNDTIMEO, ZMQ_LINGER

### Task 2: Implement Connection Management (AC: 1, 4)
- [x] Implement `async connect()` method with socket connect/bind
- [x] Implement `async disconnect()` method with proper socket cleanup
- [x] Add connection state tracking (connected, connecting, disconnected)
- [x] Implement exponential backoff reconnection: delays = [1, 2, 4, 8, 16, 30]
- [x] Add `async reconnect()` method called on connection failure
- [x] Log connection events at INFO level, failures at ERROR

### Task 3: Implement Tick Data Reception (AC: 2, 5)
- [x] Subscribe to all tick topics: `sub_socket.subscribe(b"tick:")`
- [x] Implement `async receive_ticks()` as async generator
- [x] Parse multipart messages: `[topic, payload]` structure
- [x] Deserialize JSON payload into `Tick` dataclass
- [x] Extract account_id from tick for routing
- [x] Handle malformed messages gracefully (log warning, continue)

### Task 4: Implement Order Publishing (AC: 3)
- [x] Implement `async send_order(order: Order) -> None`
- [x] Serialize order to JSON using Pydantic model
- [x] Publish with topic: `order:{order.account_id}`
- [x] Use multipart message: `[topic_bytes, payload_bytes]`
- [x] Log order sent at DEBUG level

### Task 5: Implement Order Result Handling (AC: 6)
- [x] Subscribe to order result topics: `sub_socket.subscribe(b"order_result:")`
- [x] Create `_pending_orders: dict[str, asyncio.Future]` for correlation
- [x] Implement `async send_order_and_wait(order: Order, timeout: float = 5.0) -> OrderResult`
- [x] Create Future before sending, store in pending_orders
- [x] On result receipt, resolve matching Future
- [x] Handle timeout with `asyncio.wait_for()` raising `TimeoutError`

### Task 6: Create Data Models (AC: 2, 3, 6)
- [x] Create `Tick` dataclass matching mt5-bridge protocol
- [x] Create `Order` Pydantic model matching mt5-bridge protocol
- [x] Create `OrderResult` dataclass matching mt5-bridge protocol
- [x] Add `OrderSide` enum: BUY, SELL
- [x] Add `OrderStatus` enum: filled, partially_filled, rejected, error

### Task 7: Write Unit Tests (AC: 7)
- [x] Create `tests/unit/test_zmq_adapter.py`
- [x] Test ZmqConfig validation
- [x] Test Tick parsing from JSON
- [x] Test Order serialization to JSON
- [x] Test OrderResult parsing
- [x] Test reconnection delay sequence
- [x] Mock zmq sockets using `unittest.mock`

### Task 8: Write Integration Tests (AC: 8)
- [x] Create `tests/integration/test_zmq_integration.py`
- [ ] Test connection to running mt5-bridge (requires MT5_BRIDGE_AVAILABLE=true)
- [ ] Test tick subscription and receipt (requires MT5_BRIDGE_AVAILABLE=true)
- [ ] Test order publishing (requires MT5_BRIDGE_AVAILABLE=true)
- [x] Mark tests with `@pytest.mark.integration`

## Dev Notes

### Quick Reference (Executive Summary)

**Key Implementation Points:**
- **SUB socket** connects to `mt5-bridge:5556` for tick data
- **PUB socket** binds to `0.0.0.0:5557` for order commands
- **CRITICAL:** `receive_ticks()` must run in background task for order results to work
- Message format: Multipart `[topic_bytes, json_payload_bytes]`
- Topics: `tick:{symbol}`, `order:{account_id}`, `order_result:{order_id}`

### Architecture Patterns and Constraints

**From Architecture Document (docs/architecture.md):**

```
Trading Engine ZeroMQ Communication:
├── SUB socket (port 5556) ← Tick data from mt5-bridge PUB
├── PUB socket (port 5557) → Order commands to mt5-bridge SUB
└── SUB socket (port 5556) ← Order results from mt5-bridge PUB
```

**ZeroMQ Socket Pattern (Python ↔ Rust Bridge):**
```
┌─────────────────┐         ┌───────────────┐
│trading-engine   │         │  mt5-bridge   │
│   (Python)      │         │    (Rust)     │
└───────┬─────────┘         └───────┬───────┘
        │                           │
        │ ◀──── SUB: tick:XAUUSD ───│ (port 5556)
        │                           │
        │ ──── PUB: order:ftmo-001 ─▶│ (port 5557)
        │                           │
        │ ◀──── SUB: order_result:* ─│ (port 5556)
```

**Critical Socket Rules:**
- SUB sockets `connect()` to PUB sockets (trading-engine SUB connects to mt5-bridge PUB)
- PUB sockets `bind()` (trading-engine PUB binds, mt5-bridge SUB connects)
- Topics are byte prefixes: `b"tick:"`, `b"order:"`, `b"order_result:"`
- All messages are multipart: `[topic, json_payload]`
- REP socket MUST reply after every receive (handled by mt5-bridge)

### Technical Requirements

**pyzmq Asyncio API (From Context7 Research 2025-12-22):**

```python
import zmq
import zmq.asyncio

# Create asyncio-compatible context (singleton pattern)
ctx = zmq.asyncio.Context.instance()

# SUB socket - connect to publisher, subscribe to topics
sub = ctx.socket(zmq.SUB)
sub.connect("tcp://mt5-bridge:5556")
sub.subscribe(b"tick:")  # Subscribe to all tick topics
sub.subscribe(b"order_result:")  # Also subscribe to order results

# PUB socket - bind for subscribers to connect
pub = ctx.socket(zmq.PUB)
pub.bind("tcp://0.0.0.0:5557")

# Async receive (returns Future)
msg = await sub.recv_multipart()  # [topic_bytes, payload_bytes]
topic = msg[0].decode()
payload = json.loads(msg[1])

# Async send
await pub.send_multipart([topic.encode(), json.dumps(order).encode()])
```

**Socket Options for Reliability:**
```python
# Timeout for receives (milliseconds)
sub.setsockopt(zmq.RCVTIMEO, 1000)  # 1 second receive timeout

# Linger on close (don't lose pending messages)
sub.setsockopt(zmq.LINGER, 1000)  # Wait 1 second before discarding

# Reconnection settings (ZMQ handles reconnection automatically)
sub.setsockopt(zmq.RECONNECT_IVL, 1000)  # Initial reconnect interval (ms)
sub.setsockopt(zmq.RECONNECT_IVL_MAX, 30000)  # Max reconnect interval (ms)
```

### ⚠️ CRITICAL: Concurrent Operation Pattern

**The `receive_ticks()` async generator MUST run in a background task for order results to work.**

Order results are received via the SUB socket and processed inside `receive_ticks()`. If you call `send_order_and_wait()` without `receive_ticks()` running, the order will timeout.

**Correct Usage Pattern:**
```python
import asyncio
from src.adapters.zmq_adapter import ZmqAdapter
from src.adapters.zmq_models import Order, OrderSide

async def main():
    adapter = ZmqAdapter()
    await adapter.connect()

    # CRITICAL: Start tick receiver in background task
    async def tick_receiver():
        async for tick in adapter.receive_ticks():
            # Process tick (also handles order_result messages internally)
            print(f"Tick: {tick.symbol} bid={tick.bid}")

    # Run receiver in background
    receiver_task = asyncio.create_task(tick_receiver())

    # Now orders can be sent - results will be received by the background task
    order = Order(
        account_id="ftmo-001",
        action=OrderSide.BUY,
        symbol="XAUUSD",
        volume=0.1,
        price=1850.45,
        order_id="ORDER-123",
    )

    try:
        result = await adapter.send_order_and_wait(order, timeout=5.0)
        print(f"Order filled at {result.fill_price}")
    except asyncio.TimeoutError:
        print("Order timed out - is receive_ticks() running?")

    # Cleanup
    receiver_task.cancel()
    await adapter.disconnect()

asyncio.run(main())
```

**Why This Matters:**
- `send_order_and_wait()` creates a Future and stores it in `_pending_orders`
- The order result arrives on the SUB socket with topic `order_result:{order_id}`
- `receive_ticks()` processes ALL incoming messages including order results
- When a result arrives, it resolves the matching Future
- Without `receive_ticks()` running, results are never processed → timeout

### Message Protocol (JSON)

**Tick Message (mt5-bridge → trading-engine):**
```json
{
  "account_id": "ftmo-gold-001",
  "symbol": "XAUUSD",
  "bid": 1850.25,
  "ask": 1850.45,
  "timestamp": "2025-12-03T14:32:15.123Z"
}
```

**Order Command (trading-engine → mt5-bridge):**
```json
{
  "type": "order",
  "account_id": "ftmo-gold-001",
  "action": "BUY",
  "symbol": "XAUUSD",
  "volume": 0.1,
  "price": 1850.45,
  "sl": 1845.00,
  "tp": 1860.00,
  "order_id": "ORDER-UUID-123"
}
```

**Order Result (mt5-bridge → trading-engine):**
```json
{
  "order_id": "ORDER-UUID-123",
  "status": "filled",
  "fill_price": 1850.47,
  "slippage": 0.02,
  "timestamp": "2025-12-03T14:32:15.456Z"
}
```

### File Structure Requirements

```
services/trading-engine/
├── src/
│   ├── adapters/
│   │   ├── __init__.py          # MODIFY: Export ZmqAdapter
│   │   ├── zmq_adapter.py       # NEW: ZeroMQ adapter implementation
│   │   └── zmq_models.py        # NEW: Tick, Order, OrderResult models
│   └── ...
├── tests/
│   ├── unit/
│   │   └── test_zmq_adapter.py  # NEW: Unit tests
│   └── integration/
│       └── test_zmq_integration.py  # NEW: Integration tests
└── ...
```

### Expected Implementation Pattern

**ZmqAdapter Full Implementation:**
```python
# src/adapters/zmq_adapter.py
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import zmq
import zmq.asyncio
from pydantic import BaseModel

from .zmq_models import Order, OrderResult, Tick

logger = logging.getLogger(__name__)


class ZmqConfig(BaseModel):
    """ZeroMQ adapter configuration."""
    bridge_host: str = "localhost"
    tick_port: int = 5556   # Port we SUB to for ticks (mt5-bridge PUB)
    order_port: int = 5557  # Port we PUB on for orders (mt5-bridge SUB connects)
    recv_timeout_ms: int = 1000
    send_timeout_ms: int = 5000
    reconnect_ivl_ms: int = 1000
    reconnect_ivl_max_ms: int = 30000


@dataclass
class ConnectionState:
    """Connection state tracking."""
    connected: bool = False
    connecting: bool = False
    last_error: str | None = None


class ZmqAdapter:
    """ZeroMQ adapter for mt5-bridge communication.

    Provides bidirectional communication with mt5-bridge:
    - SUB socket receives tick data and order results from bridge PUB
    - PUB socket sends order commands to bridge SUB
    """

    # Exponential backoff delays for reconnection (seconds)
    RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30]

    def __init__(self, config: ZmqConfig | None = None):
        self.config = config or ZmqConfig()
        self._ctx = zmq.asyncio.Context.instance()
        self._sub_socket: zmq.asyncio.Socket | None = None
        self._pub_socket: zmq.asyncio.Socket | None = None
        self._state = ConnectionState()
        self._pending_orders: dict[str, asyncio.Future[OrderResult]] = {}
        self._reconnect_attempt = 0

    @property
    def is_connected(self) -> bool:
        return self._state.connected

    async def connect(self) -> None:
        """Connect to mt5-bridge ZeroMQ sockets."""
        if self._state.connected:
            return

        self._state.connecting = True
        try:
            # SUB socket - connect to mt5-bridge PUB (port 5556)
            self._sub_socket = self._ctx.socket(zmq.SUB)
            self._sub_socket.setsockopt(zmq.RCVTIMEO, self.config.recv_timeout_ms)
            self._sub_socket.setsockopt(zmq.LINGER, 1000)
            self._sub_socket.setsockopt(zmq.RECONNECT_IVL, self.config.reconnect_ivl_ms)
            self._sub_socket.setsockopt(zmq.RECONNECT_IVL_MAX, self.config.reconnect_ivl_max_ms)

            sub_endpoint = f"tcp://{self.config.bridge_host}:{self.config.tick_port}"
            self._sub_socket.connect(sub_endpoint)

            # Subscribe to tick and order_result topics
            self._sub_socket.subscribe(b"tick:")
            self._sub_socket.subscribe(b"order_result:")

            logger.info("SUB socket connected to %s", sub_endpoint)

            # PUB socket - bind for mt5-bridge SUB to connect (port 5557)
            self._pub_socket = self._ctx.socket(zmq.PUB)
            self._pub_socket.setsockopt(zmq.SNDTIMEO, self.config.send_timeout_ms)
            self._pub_socket.setsockopt(zmq.LINGER, 1000)

            pub_endpoint = f"tcp://0.0.0.0:{self.config.order_port}"
            self._pub_socket.bind(pub_endpoint)

            logger.info("PUB socket bound to %s", pub_endpoint)

            self._state.connected = True
            self._state.last_error = None
            self._reconnect_attempt = 0

        except zmq.ZMQError as e:
            self._state.last_error = str(e)
            logger.error("Failed to connect: %s", e)
            raise
        finally:
            self._state.connecting = False

    async def disconnect(self) -> None:
        """Disconnect and cleanup sockets."""
        self._state.connected = False

        if self._sub_socket:
            self._sub_socket.close()
            self._sub_socket = None

        if self._pub_socket:
            self._pub_socket.close()
            self._pub_socket = None

        logger.info("ZMQ adapter disconnected")

    async def reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        delay_idx = min(self._reconnect_attempt, len(self.RECONNECT_DELAYS) - 1)
        delay = self.RECONNECT_DELAYS[delay_idx]

        logger.warning(
            "Reconnecting in %d seconds (attempt %d)",
            delay,
            self._reconnect_attempt + 1
        )

        await asyncio.sleep(delay)
        self._reconnect_attempt += 1

        await self.disconnect()
        await self.connect()

    async def receive_ticks(self) -> AsyncIterator[Tick]:
        """Async generator yielding tick data from mt5-bridge.

        Yields:
            Tick: Parsed tick data with account_id, symbol, bid, ask, timestamp
        """
        if not self._sub_socket:
            raise RuntimeError("Not connected - call connect() first")

        while True:
            try:
                msg = await self._sub_socket.recv_multipart()

                if len(msg) < 2:
                    logger.warning("Received malformed message: %s", msg)
                    continue

                topic = msg[0].decode()
                payload = msg[1].decode()

                # Route by topic prefix
                if topic.startswith("tick:"):
                    try:
                        data = json.loads(payload)
                        tick = Tick(
                            account_id=data["account_id"],
                            symbol=data["symbol"],
                            bid=data["bid"],
                            ask=data["ask"],
                            timestamp=data["timestamp"],
                        )
                        yield tick
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("Failed to parse tick: %s - %s", e, payload)

                elif topic.startswith("order_result:"):
                    try:
                        data = json.loads(payload)
                        result = OrderResult(
                            order_id=data["order_id"],
                            status=data["status"],
                            fill_price=data.get("fill_price"),
                            slippage=data.get("slippage"),
                            timestamp=data["timestamp"],
                            error=data.get("error"),
                        )
                        # Resolve pending order future
                        future = self._pending_orders.pop(result.order_id, None)
                        if future and not future.done():
                            future.set_result(result)
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("Failed to parse order result: %s", e)

            except zmq.Again:
                # Receive timeout - continue loop
                continue
            except zmq.ZMQError as e:
                logger.error("ZMQ receive error: %s", e)
                await self.reconnect()

    async def send_order(self, order: Order) -> None:
        """Send order command to mt5-bridge.

        Args:
            order: Order to send
        """
        if not self._pub_socket:
            raise RuntimeError("Not connected - call connect() first")

        topic = f"order:{order.account_id}"
        payload = order.model_dump_json()

        await self._pub_socket.send_multipart([
            topic.encode(),
            payload.encode(),
        ])

        logger.debug(
            "Order sent: %s %s %s @ %.2f",
            order.order_id,
            order.action,
            order.symbol,
            order.price,
        )

    async def send_order_and_wait(
        self,
        order: Order,
        timeout: float = 5.0,
    ) -> OrderResult:
        """Send order and wait for result with timeout.

        Args:
            order: Order to send
            timeout: Timeout in seconds

        Returns:
            OrderResult from mt5-bridge

        Raises:
            asyncio.TimeoutError: If no result received within timeout
        """
        # Create future for this order
        future: asyncio.Future[OrderResult] = asyncio.get_running_loop().create_future()
        self._pending_orders[order.order_id] = future

        try:
            await self.send_order(order)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_orders.pop(order.order_id, None)
            logger.error("Order timeout: %s", order.order_id)
            raise

    async def __aenter__(self) -> ZmqAdapter:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()
```

**Data Models:**
```python
# src/adapters/zmq_models.py
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    """Order direction."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Order execution status."""
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass
class Tick:
    """Market tick data from mt5-bridge."""
    account_id: str
    symbol: str
    bid: float
    ask: float
    timestamp: str  # ISO format: "2025-12-22T10:00:00.123Z"

    @property
    def spread(self) -> float:
        """Calculate spread in price units."""
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        """Calculate mid price."""
        return (self.bid + self.ask) / 2

    @property
    def timestamp_dt(self) -> datetime:
        """Parse timestamp to datetime object."""
        from datetime import datetime
        return datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))


class Order(BaseModel):
    """Order command to mt5-bridge."""
    type: str = Field(default="order", frozen=True)
    account_id: str
    action: OrderSide
    symbol: str
    volume: float
    price: float
    sl: Optional[float] = None
    tp: Optional[float] = None
    order_id: str


@dataclass
class OrderResult:
    """Order execution result from mt5-bridge."""
    order_id: str
    status: OrderStatus
    fill_price: Optional[float] = None
    slippage: Optional[float] = None
    timestamp: str = ""
    error: Optional[str] = None

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED

    @property
    def is_rejected(self) -> bool:
        return self.status in (OrderStatus.REJECTED, OrderStatus.ERROR)
```

### Testing Requirements

**Unit Test Example:**
```python
# tests/unit/test_zmq_adapter.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.adapters.zmq_adapter import ZmqAdapter, ZmqConfig
from src.adapters.zmq_models import Order, OrderResult, OrderSide, OrderStatus, Tick


class TestZmqConfig:
    def test_default_config(self):
        config = ZmqConfig()
        assert config.bridge_host == "localhost"
        assert config.tick_port == 5556
        assert config.order_port == 5557

    def test_custom_config(self):
        config = ZmqConfig(bridge_host="mt5-bridge", tick_port=6556)
        assert config.bridge_host == "mt5-bridge"
        assert config.tick_port == 6556


class TestTick:
    def test_tick_spread(self):
        tick = Tick(
            account_id="test",
            symbol="XAUUSD",
            bid=1850.25,
            ask=1850.45,
            timestamp="2025-12-22T10:00:00Z",
        )
        assert tick.spread == pytest.approx(0.20)
        assert tick.mid == pytest.approx(1850.35)


class TestOrder:
    def test_order_serialization(self):
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.1,
            price=1850.45,
            sl=1845.00,
            tp=1860.00,
            order_id="ORDER-123",
        )
        json_str = order.model_dump_json()
        assert '"action":"BUY"' in json_str
        assert '"order_id":"ORDER-123"' in json_str


class TestZmqAdapterConcurrentOperation:
    """Test concurrent tick receiving and order sending."""

    @pytest.mark.asyncio
    async def test_send_order_with_receiver_running(self):
        """Order results require receive_ticks() to be running."""
        adapter = ZmqAdapter()
        # Mock connection for unit test
        adapter._state.connected = True
        adapter._sub_socket = AsyncMock()
        adapter._pub_socket = AsyncMock()

        # Simulate order result arriving
        async def mock_recv():
            await asyncio.sleep(0.1)
            return [b"order_result:ORDER-123", b'{"order_id":"ORDER-123","status":"filled","fill_price":1850.47,"timestamp":"2025-12-22T10:00:00Z"}']

        adapter._sub_socket.recv_multipart = mock_recv

        # Start receiver in background
        async def receiver():
            async for _ in adapter.receive_ticks():
                break  # Exit after first message

        receiver_task = asyncio.create_task(receiver())

        # Send order while receiver is running
        order = Order(
            account_id="test",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.1,
            price=1850.45,
            order_id="ORDER-123",
        )

        result = await adapter.send_order_and_wait(order, timeout=1.0)
        assert result.order_id == "ORDER-123"
        assert result.status == OrderStatus.FILLED

        receiver_task.cancel()


class TestZmqAdapterReconnection:
    def test_reconnect_delays(self):
        adapter = ZmqAdapter()
        assert adapter.RECONNECT_DELAYS == [1, 2, 4, 8, 16, 30]

    @pytest.mark.asyncio
    async def test_reconnect_exponential_backoff(self):
        adapter = ZmqAdapter()

        # First attempt: 1 second delay
        adapter._reconnect_attempt = 0
        delay = adapter.RECONNECT_DELAYS[
            min(adapter._reconnect_attempt, len(adapter.RECONNECT_DELAYS) - 1)
        ]
        assert delay == 1

        # Fourth attempt: 8 second delay
        adapter._reconnect_attempt = 3
        delay = adapter.RECONNECT_DELAYS[
            min(adapter._reconnect_attempt, len(adapter.RECONNECT_DELAYS) - 1)
        ]
        assert delay == 8

        # Beyond max: stays at 30 seconds
        adapter._reconnect_attempt = 100
        delay = adapter.RECONNECT_DELAYS[
            min(adapter._reconnect_attempt, len(adapter.RECONNECT_DELAYS) - 1)
        ]
        assert delay == 30
```

**Test Execution:**
```bash
# From services/trading-engine directory
cd services/trading-engine

# Run all tests
uv run pytest

# Run unit tests only
uv run pytest tests/unit/

# Run with verbose output
uv run pytest -v

# Run integration tests (requires running mt5-bridge)
uv run pytest tests/integration/ -m integration

# Check code quality
uv run ruff check src/
```

### Previous Story Learnings (Story 2.3)

From the Story 2.3 MT5 Bridge ZeroMQ Server implementation:
- **Port 5556**: mt5-bridge PUB socket - trading-engine SUB connects here for ticks
- **Port 5557**: mt5-bridge SUB socket - trading-engine PUB binds, bridge connects
- **Topic format**: `tick:{symbol}` (e.g., `tick:XAUUSD`), `order:{account_id}`, `order_result:{order_id}`
- **Message structure**: Multipart `[topic_bytes, json_payload_bytes]`
- **account_id field**: Included in tick messages for multi-account routing
- **Order queue**: mt5-bridge queues orders for MT5 EA polling
- **Heartbeat tracking**: Per-account with 30-second timeout (bridge-side)

**Files created in Story 2.3 to align with:**
- `services/mt5-bridge/src/zmq_server.rs` - ZMQ socket implementation
- `services/mt5-bridge/src/protocol.rs` - Message types (Tick, Order, OrderResult, Heartbeat)
- `services/mt5-bridge/src/models/tick.rs` - Tick model with `topic()` method
- `services/mt5-bridge/src/models/order.rs` - Order and OrderResult models

**Key Pattern from Story 2.3:**
```rust
// Bridge publishes ticks with topic
let topic = tick.topic(); // "tick:XAUUSD"
pub_socket.send(ZmqMessage::from([topic, payload])).await?;

// Bridge subscribes to orders with topic
sub_socket.subscribe("order:").await?;
```

### Git Intelligence (Recent Commits)

From commit `1f5f24d` (Story 2.3):
- Implemented full ZmqServer with REP (5555), PUB (5556), SUB (5557) sockets
- Added per-account heartbeat tracking
- Added order queue (mpsc channel) for async order delivery
- All 49 tests passing

From commit `09bad32` (Story 2.2):
- Account lifecycle management implemented
- Redis state storage for accounts
- CLI commands for start/stop/status

### Environment Variables Required

```bash
# ZeroMQ Configuration
ZMQ_BRIDGE_HOST=localhost      # mt5-bridge hostname (or Docker service name)
ZMQ_TICK_PORT=5556             # Port we SUB to for ticks (mt5-bridge PUB)
ZMQ_ORDER_PORT=5557            # Port we PUB on for orders (mt5-bridge SUB connects)

# Timeouts
ZMQ_RECV_TIMEOUT_MS=1000       # Receive timeout (default: 1000ms)
ZMQ_SEND_TIMEOUT_MS=5000       # Send timeout (default: 5000ms)

# Reconnection
ZMQ_RECONNECT_IVL_MS=1000      # Initial reconnect interval
ZMQ_RECONNECT_IVL_MAX_MS=30000 # Max reconnect interval
```

### Dependencies (pyproject.toml - Already Configured)

```toml
dependencies = [
    "nautilus_trader>=1.200",
    "redis>=5.0",
    "pyzmq>=25.0",  # Required for ZMQ adapter
    "sqlalchemy>=2.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "typer>=0.9",
]
```

### Project Structure Notes

- Alignment with monorepo structure confirmed
- ZmqAdapter goes in `src/adapters/zmq_adapter.py`
- Data models go in `src/adapters/zmq_models.py`
- Tests follow pytest async patterns with `pytest-asyncio`
- Integration tests marked with `@pytest.mark.integration`

### References

- [Source: docs/architecture.md#Trading-Engine-Service] - Service structure and ZMQ patterns
- [Source: docs/architecture.md#Inter-Service-Communication] - Port assignments and message flow
- [Source: docs/epic-2-context.md#Story-2.4] - Story requirements and implementation plan
- [Source: docs/sprint-artifacts/2-3-mt5-bridge-zeromq-server.md] - Previous story patterns
- [Source: Context7 pyzmq 2025-12-22] - Python ZeroMQ asyncio patterns
- [Source: Context7 zeromq.org 2025-12-22] - ZeroMQ PUB/SUB patterns

## Dev Agent Record

### Context Reference

- Epic 2 Context: `docs/epic-2-context.md`
- Architecture: `docs/architecture.md`
- PRD: `docs/prd.md`
- Previous Story: `docs/sprint-artifacts/2-3-mt5-bridge-zeromq-server.md`

### Agent Model Used

- Story Creation: Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A

### Completion Notes List

- Story created with comprehensive developer context from artifact analysis
- pyzmq asyncio patterns researched via Context7 MCP (2025-12-22)
- ZeroMQ PUB/SUB patterns researched via Context7 MCP (2025-12-22)
- All acceptance criteria mapped to specific tasks with file locations
- Complete implementation patterns provided based on architecture and Story 2.3
- Message protocol documented with JSON examples
- Test patterns provided for both unit and integration testing

### File List

Files created:
- `services/trading-engine/src/adapters/zmq_adapter.py` - ZeroMQ adapter implementation (ZmqAdapter, ZmqConfig, _ConnectionState)
- `services/trading-engine/src/adapters/zmq_models.py` - Tick, Order, OrderResult, OrderSide, OrderStatus models with validation
- `services/trading-engine/tests/unit/test_zmq_adapter.py` - 58 unit tests (includes validation + malformed message tests)
- `services/trading-engine/tests/integration/test_zmq_integration.py` - Integration test structure (skipped without MT5_BRIDGE_AVAILABLE)
- `docs/sprint-artifacts/validation-report-2-4-20251222.md` - Validation report from pre-implementation review

Files modified:
- `services/trading-engine/src/adapters/__init__.py` - Export ZmqAdapter and all models

---

## Verification Checklist

### Manual Test Steps

```bash
# 1. Ensure you're in the trading-engine directory
cd services/trading-engine

# 2. Install dependencies
uv sync

# 3. Run unit tests
uv run pytest tests/unit/test_zmq_adapter.py -v

# 4. Check code quality
uv run ruff check src/adapters/

# 5. Start mt5-bridge (in terminal 1)
cd ../mt5-bridge && RUST_LOG=debug cargo run

# 6. Test adapter connection (in terminal 2)
cd ../trading-engine
uv run python -c "
import asyncio
from src.adapters.zmq_adapter import ZmqAdapter

async def test():
    async with ZmqAdapter() as adapter:
        print('Connected to mt5-bridge')
        async for tick in adapter.receive_ticks():
            print(f'Tick: {tick.symbol} bid={tick.bid} ask={tick.ask}')
            break  # Exit after first tick

asyncio.run(test())
"
```

### Acceptance Criteria Verification

- [x] **AC1**: SUB socket connects to 5556, PUB socket binds to 5557
- [x] **AC2**: Tick messages parsed into Tick dataclass (with validation)
- [x] **AC3**: Orders published with topic `order:{account_id}` (with validation)
- [x] **AC4**: Reconnection with exponential backoff
- [x] **AC5**: Ticks routed by account_id field
- [x] **AC6**: Order results correlated by order_id
- [x] **AC7**: Unit tests pass (58 tests including validation + malformed message tests)
- [ ] **AC8**: Integration tests require running mt5-bridge (set MT5_BRIDGE_AVAILABLE=true)

---

## Definition of Done

- [x] `src/adapters/zmq_adapter.py` implements full ZMQ socket operations
- [x] `src/adapters/zmq_models.py` defines Tick, Order, OrderResult with validation
- [x] `src/adapters/__init__.py` exports ZmqAdapter
- [x] SUB socket connects to mt5-bridge PUB (port 5556)
- [x] PUB socket binds for mt5-bridge SUB (port 5557)
- [x] Tick messages parsed and yielded via async generator
- [x] Orders published with correct topic format
- [x] Reconnection works with exponential backoff
- [x] All unit tests pass: `uv run pytest tests/unit/` (202 tests)
- [ ] Integration tests pass with running bridge (requires MT5_BRIDGE_AVAILABLE=true)
- [x] Linting passes: `uv run ruff check src/`
- [ ] Story status updated to `done` (pending AC8)

---

## Troubleshooting

### Common Issues

**Socket Connect Error: "Connection refused"**
```bash
# Ensure mt5-bridge is running
cd services/mt5-bridge
cargo run

# Check if ports are available
lsof -i :5556 -i :5557
```

**No Ticks Received**
```bash
# Ensure subscription topics match publisher
# Topic prefix must match exactly: b"tick:" not b"tick"
# Check mt5-bridge logs for publishing activity
```

**Order Timeout**
```bash
# Check that mt5-bridge SUB is connected to trading-engine PUB
# Verify order topic format: "order:{account_id}"
# Check mt5-bridge order queue processing
```

**Slow Subscriber Issue**
```bash
# Add small delay after connect before expecting messages
# ZMQ PUB/SUB has "slow subscriber" problem
# First few messages may be lost during connect
await asyncio.sleep(0.1)  # Allow subscription to propagate
```

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-22 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-22 | pyzmq asyncio patterns researched via Context7 MCP |
| 2025-12-22 | Aligned with Story 2.3 mt5-bridge implementation patterns |
| 2025-12-22 | Complete implementation patterns provided with test examples |
| 2025-12-22 | **Validation improvements applied:** (1) Added Quick Reference executive summary at top of Dev Notes; (2) Added CRITICAL concurrent operation documentation with usage pattern; (3) Fixed asyncio.get_event_loop() → asyncio.get_running_loop() deprecation; (4) Renamed pub_port/sub_port to tick_port/order_port for clarity; (5) Added concurrent operation test example; (6) Added timestamp_dt property for datetime parsing |
| 2025-12-22 | **Implementation completed:** (1) Created zmq_adapter.py with full ZMQ socket operations; (2) Created zmq_models.py with Tick, Order, OrderResult, OrderSide, OrderStatus; (3) Updated __init__.py with exports; (4) 37 unit tests passing covering all functionality; (5) Integration test structure created; (6) All 179 trading-engine unit tests passing; (7) Ruff linting passes |
| 2025-12-22 | **Code review fixes applied:** (1) Added Order field validation - volume/price must be positive, account_id/symbol/order_id must be non-empty; (2) Added Tick validation via __post_init__ - all fields validated, ask >= bid enforced; (3) Renamed ConnectionState to _ConnectionState (internal API); (4) Added 21 new tests for validation and malformed message handling; (5) Fixed Task 8 completion status - integration tests require MT5_BRIDGE_AVAILABLE; (6) Updated File List with validation report |
