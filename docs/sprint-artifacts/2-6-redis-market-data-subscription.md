# Story 2.6: Redis Market Data Subscription

Status: Done

## Story

As a **developer**,
I want **the trading-engine to receive OHLCV bars from Redis**,
So that **strategies can react to new candle data**.

## Acceptance Criteria

1. **AC1**: Given the trading-engine starts, when it initializes the Redis adapter, then it subscribes to bar channels based on account symbol filters
2. **AC2**: Given an account is configured to trade XAUUSD, when tv-api publishes a new bar to `bars:XAUUSD:1m`, then the Redis adapter receives the bar data and routes it to the account's strategy
3. **AC3**: Given the bar data format is JSON with symbol, timeframe, time, open, high, low, close, volume, when the strategy receives the bar, then it can access all OHLCV fields for signal generation
4. **AC4**: Given Redis connection is lost, when the adapter detects disconnection, then it attempts reconnection with exponential backoff and re-subscribes to all channels on reconnect
5. **AC5**: The adapter uses asyncio pub/sub from redis-py with `redis.asyncio` module
6. **AC6**: Bar messages are parsed into a Bar model with Pydantic validation
7. **AC7**: Unit tests cover bar parsing, subscription management, and reconnection logic
8. **AC8**: Integration tests verify end-to-end bar flow with running Redis

## Tasks / Subtasks

### Task 1: Create Bar Model (AC: 3, 6)
- [x] Create `src/adapters/redis_models.py` with Bar Pydantic model
- [x] Define fields: symbol, timeframe, time (datetime), open, high, low, close, volume
- [x] Add validation for OHLCV values (positive prices, volume >= 0)
- [x] Add `from_json()` class method for parsing Redis messages
- [x] Add `channel_name` property: `bars:{symbol}:{timeframe}`

### Task 2: Create Redis Configuration (AC: 1, 4)
- [x] Create `src/adapters/redis_config.py` with RedisConfig Pydantic model
- [x] Define fields: redis_url (default redis://localhost:6379), reconnect_delays, recv_timeout_ms
- [x] Use pydantic-settings for environment variable support (`REDIS_URL`)
- [x] Define default reconnect delays: [1, 2, 4, 8, 16, 30] seconds

### Task 3: Create Redis Adapter Core (AC: 1, 2, 5)
- [x] Create `src/adapters/redis_adapter.py` with RedisAdapter class
- [x] Use `redis.asyncio as redis` for async operations
- [x] Implement `connect()` method using `redis.from_url()`
- [x] Implement `disconnect()` method with `await client.aclose()`
- [x] Store subscription list in `_subscriptions: set[str]` for reconnection
- [x] Add `is_connected` property for connection state

### Task 4: Implement Pub/Sub Subscription (AC: 1, 2)
- [x] Implement `subscribe(symbols: list[str], timeframe: str = "1m")` method
- [x] Create channel names: `bars:{symbol}:{timeframe}` for each symbol
- [x] Use `pubsub.subscribe(*channels)` for multiple channels
- [x] Store all channel names in `_subscriptions` for reconnect re-subscription
- [x] Implement `unsubscribe(symbols: list[str], timeframe: str)` method

### Task 5: Implement Bar Listening (AC: 2, 3)
- [x] Implement `listen_bars()` async generator yielding Bar objects
- [x] Use `pubsub.get_message(ignore_subscribe_messages=True, timeout=None)` pattern
- [x] Parse JSON message data into Bar model
- [x] Handle malformed messages with logging (don't raise)
- [x] Yield only valid Bar objects

### Task 6: Implement Reconnection with Backoff (AC: 4)
- [x] Use custom exponential backoff delays from config
- [x] Implement `reconnect()` method with exponential backoff delays
- [x] On reconnect success, re-subscribe to all channels from `_subscriptions`
- [x] Log reconnection attempts and successes
- [x] Track reconnect attempts for delay calculation

### Task 7: Implement Async Context Manager (AC: 5)
- [x] Implement `__aenter__` to connect
- [x] Implement `__aexit__` to disconnect and cleanup pubsub
- [x] Ensure proper cleanup on exception

### Task 8: Create Signal Router Integration Point (AC: 2)
- [x] Add `set_bar_callback(callback: Callable)` method for bar routing
- [x] Document integration point for Story 2.9 signal filtering
- [x] Add `_on_bar_callback: Callable[[Bar], None] | None` attribute

### Task 9: Write Unit Tests (AC: 7)
- [x] Create `tests/unit/test_bar_model.py` - Bar parsing and validation
- [x] Create `tests/unit/test_redis_config.py` - Configuration loading
- [x] Create `tests/unit/test_redis_adapter.py` - Adapter logic with mocked Redis
- [x] Test subscription management (add/remove channels)
- [x] Test reconnection logic with mocked connection failures
- [x] Test bar parsing with valid and invalid JSON

### Task 10: Write Integration Tests (AC: 8)
- [x] Create `tests/integration/test_redis_pubsub.py`
- [x] Test real pub/sub with running Redis container
- [x] Publish test bar, verify receipt via adapter
- [x] Mark with `@pytest.mark.integration`
- [x] Skip if `REDIS_AVAILABLE` is not set

## Dev Notes

### Quick Reference (Executive Summary)

**Key Implementation Points:**
- **RedisAdapter** mirrors the ZmqAdapter pattern from Story 2.4 for consistency
- Use `redis.asyncio` module (NOT sync `redis`) for all operations
- **Channel pattern:** `bars:{symbol}:{timeframe}` (e.g., `bars:XAUUSD:1m`)
- **Reconnection:** Use built-in `redis.retry.Retry` with `ExponentialBackoff`
- Store subscriptions in `_subscriptions: set[str]` for re-subscription on reconnect
- Bar messages from tv-api are JSON-formatted (see format below)

**Redis Pub/Sub Key Pattern:**
| Channel | Publisher | Subscriber | Data |
|---------|-----------|------------|------|
| `bars:XAUUSD:1m` | tv-api | trading-engine | OHLCV bar JSON |
| `bars:BTCUSD:5m` | tv-api | trading-engine | OHLCV bar JSON |

*Note: Symbol names follow broker conventions (e.g., XAUUSD for gold). Architecture examples may use GOLD as shorthand.*

**Async Pattern (from Context7 redis-py 2025-12-23):**
```python
import redis.asyncio as redis

async def main():
    r = redis.from_url("redis://localhost:6379")
    async with r.pubsub() as pubsub:
        await pubsub.subscribe("channel:1", "channel:2")

        async for message in pubsub.listen():
            if message["type"] == "message":
                print(f"Received: {message['data']}")
```

### Architecture Patterns and Constraints

**From Architecture Document (docs/architecture.md):**

```
Data Flow:
┌─────────────┐                    ┌─────────────────┐                    ┌────────────────┐
│   tv-api    │ ──── PUBLISH ────▶ │      Redis      │ ◀──── SUBSCRIBE ── │ trading-engine │
│    (Go)     │ bars:XAUUSD:1m     │   (Hot Cache)   │    bars:XAUUSD:1m  │    (Python)    │
└─────────────┘                    └─────────────────┘                    └────────────────┘
                                          │
                                          │ Pub/Sub Channel
                                          ▼
                                   bars:{symbol}:{timeframe}
```

**Redis Pub/Sub Channels (from docs/architecture.md):**
| Channel | Publisher | Subscriber | Data |
|---------|-----------|------------|------|
| `bars:GOLD:1m` | tv-api | trading-engine | OHLCV candles |
| `bars:BTC:5m` | tv-api | trading-engine | OHLCV candles |
| `alerts:trade` | trading-engine | notification | Trade events |
| `alerts:risk` | trading-engine | notification | Risk warnings |

### Technical Requirements

**From Context7 redis-py Research (2025-12-23):**

The redis-py library provides excellent async pub/sub support. Key patterns:

**1. Async Connection Pattern:**
```python
import redis.asyncio as redis

# Connect using URL
client = redis.from_url("redis://localhost:6379")

# Or with connection pool (recommended for production)
pool = redis.ConnectionPool.from_url(
    "redis://localhost:6379",
    max_connections=20,
    decode_responses=True
)
client = redis.Redis(connection_pool=pool)
```

**2. Pub/Sub Subscription Pattern:**
```python
async def reader(channel: redis.client.PubSub):
    while True:
        message = await channel.get_message(
            ignore_subscribe_messages=True,
            timeout=None
        )
        if message is not None:
            print(f"Received: {message}")
            data = message["data"].decode()  # bytes -> str
            # Parse JSON and process

# Subscribe to channels
async with client.pubsub() as pubsub:
    await pubsub.subscribe("bars:XAUUSD:1m", "bars:BTCUSD:1m")

    # Run reader in background task
    reader_task = asyncio.create_task(reader(pubsub))
```

**3. Retry with Exponential Backoff:**
```python
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

# Configure retry with exponential backoff
retry = Retry(ExponentialBackoff(), 3)  # 3 retries
client = redis.Redis(
    host='localhost',
    port=6379,
    retry=retry,
    retry_on_error=[redis.exceptions.ConnectionError]
)
```

**4. Graceful Disconnection:**
```python
# Always close explicitly for asyncio
await pubsub.unsubscribe()
await pubsub.close()
await client.aclose()
```

### Bar Message Format (from tv-api)

```json
{
  "symbol": "XAUUSD",
  "timeframe": "1m",
  "time": "2025-12-03T14:32:00Z",
  "open": 1850.00,
  "high": 1851.50,
  "low": 1849.80,
  "close": 1850.45,
  "volume": 1234.5
}
```

### File Structure Requirements

```
services/trading-engine/
├── src/
│   ├── adapters/
│   │   ├── __init__.py             # Export RedisAdapter, Bar
│   │   ├── zmq_adapter.py          # EXISTING (Story 2.4)
│   │   ├── zmq_models.py           # EXISTING (Story 2.4)
│   │   ├── redis_adapter.py        # NEW: Redis pub/sub adapter
│   │   ├── redis_models.py         # NEW: Bar model
│   │   └── redis_config.py         # NEW: Redis configuration
│   └── ...
├── tests/
│   ├── unit/
│   │   ├── test_zmq_adapter.py     # EXISTING
│   │   ├── test_bar_model.py       # NEW: Bar model tests
│   │   ├── test_redis_config.py    # NEW: Config tests
│   │   └── test_redis_adapter.py   # NEW: Adapter tests
│   └── integration/
│       ├── test_zmq_integration.py # EXISTING
│       └── test_redis_adapter.py   # NEW: Redis integration tests
└── ...
```

### Expected Implementation Patterns

**Bar Model:**
```python
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import json


class Bar(BaseModel):
    """OHLCV bar data from Redis pub/sub.

    Attributes:
        symbol: Trading symbol (e.g., "XAUUSD")
        timeframe: Bar timeframe (e.g., "1m", "5m")
        time: Bar timestamp
        open: Opening price
        high: Highest price
        low: Lowest price
        close: Closing price
        volume: Trading volume
    """

    symbol: str = Field(..., min_length=1)
    timeframe: str = Field(..., min_length=1)
    time: datetime
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)
    volume: float = Field(..., ge=0)

    @field_validator("high")
    @classmethod
    def high_gte_low(cls, v, info):
        """Validate high >= low."""
        if "low" in info.data and v < info.data["low"]:
            raise ValueError("high must be >= low")
        return v

    @classmethod
    def from_json(cls, data: str | bytes) -> "Bar":
        """Parse Bar from JSON string.

        Args:
            data: JSON string or bytes

        Returns:
            Parsed Bar instance

        Raises:
            ValueError: If JSON is invalid or missing required fields
        """
        if isinstance(data, bytes):
            data = data.decode()
        parsed = json.loads(data)
        return cls(**parsed)

    @property
    def channel_name(self) -> str:
        """Get Redis channel name for this bar.

        Returns:
            Channel name like "bars:XAUUSD:1m"
        """
        return f"bars:{self.symbol}:{self.timeframe}"
```

**Redis Configuration:**
```python
from pydantic import Field
from pydantic_settings import BaseSettings


class RedisConfig(BaseSettings):
    """Redis adapter configuration.

    Attributes:
        redis_url: Redis connection URL
        recv_timeout_ms: Receive timeout in milliseconds (0 = no timeout)
        reconnect_delays: Exponential backoff delays in seconds
    """

    redis_url: str = Field(
        default="redis://localhost:6379",
        validation_alias="REDIS_URL"
    )
    recv_timeout_ms: int = Field(default=0)  # 0 = no timeout for pub/sub
    reconnect_delays: list[int] = Field(
        default=[1, 2, 4, 8, 16, 30]
    )

    class Config:
        env_prefix = ""  # Allow REDIS_URL without prefix
```

**Redis Adapter:**
```python
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Callable

import redis.asyncio as redis
from redis.asyncio.client import PubSub

from .redis_config import RedisConfig
from .redis_models import Bar

logger = logging.getLogger(__name__)


@dataclass
class _ConnectionState:
    """Connection state tracking (internal use only)."""

    connected: bool = False
    connecting: bool = False
    last_error: str | None = None


class RedisAdapter:
    """Redis adapter for market data subscription.

    Provides pub/sub subscription to bar channels from tv-api:
    - Subscribe to bar channels by symbol/timeframe
    - Receive and parse OHLCV bar data
    - Automatic reconnection with exponential backoff

    Example:
        async with RedisAdapter() as adapter:
            await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")
            async for bar in adapter.listen_bars():
                print(f"Bar: {bar.symbol} close={bar.close}")
    """

    def __init__(self, config: RedisConfig | None = None):
        """Initialize Redis adapter.

        Args:
            config: Redis configuration. Uses defaults if not provided.
        """
        self.config = config or RedisConfig()
        self._client: redis.Redis | None = None
        self._pubsub: PubSub | None = None
        self._state = _ConnectionState()
        self._subscriptions: set[str] = set()
        self._reconnect_attempt = 0
        self._on_bar_callback: Callable[[Bar], None] | None = None

    @property
    def is_connected(self) -> bool:
        """Check if adapter is connected."""
        return self._state.connected

    async def connect(self) -> None:
        """Connect to Redis server.

        Raises:
            redis.exceptions.ConnectionError: If connection fails
        """
        if self._state.connected:
            return

        self._state.connecting = True
        try:
            # NOTE: For production with high throughput, consider using ConnectionPool:
            # pool = redis.ConnectionPool.from_url(url, max_connections=20, decode_responses=True)
            # self._client = redis.Redis(connection_pool=pool)
            self._client = redis.from_url(
                self.config.redis_url,
                decode_responses=True,  # Auto-decode bytes to str
            )

            # Test connection
            await self._client.ping()

            # Create pub/sub instance
            self._pubsub = self._client.pubsub(
                ignore_subscribe_messages=True
            )

            self._state.connected = True
            self._state.last_error = None
            self._reconnect_attempt = 0

            logger.info("Redis connected to %s", self.config.redis_url)

        except redis.exceptions.ConnectionError as e:
            self._state.last_error = str(e)
            logger.error("Failed to connect to Redis: %s", e)
            raise
        finally:
            self._state.connecting = False

    async def disconnect(self) -> None:
        """Disconnect and cleanup.

        Closes pub/sub and Redis client gracefully.
        """
        self._state.connected = False

        if self._pubsub:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.close()
            except Exception as e:
                logger.warning("Error closing pubsub: %s", e)
            self._pubsub = None

        if self._client:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.warning("Error closing Redis client: %s", e)
            self._client = None

        logger.info("Redis adapter disconnected")

    async def reconnect(self) -> None:
        """Reconnect with exponential backoff.

        Re-subscribes to all previous channels after successful reconnect.
        """
        delay_idx = min(
            self._reconnect_attempt,
            len(self.config.reconnect_delays) - 1
        )
        delay = self.config.reconnect_delays[delay_idx]

        logger.warning(
            "Redis reconnecting in %d seconds (attempt %d)",
            delay,
            self._reconnect_attempt + 1,
        )

        await asyncio.sleep(delay)
        self._reconnect_attempt += 1

        await self.disconnect()
        await self.connect()

        # Re-subscribe to all previous channels
        if self._subscriptions and self._pubsub:
            await self._pubsub.subscribe(*self._subscriptions)
            logger.info(
                "Re-subscribed to %d channels after reconnect",
                len(self._subscriptions)
            )

    async def subscribe(
        self,
        symbols: list[str],
        timeframe: str = "1m"
    ) -> None:
        """Subscribe to bar channels for given symbols.

        Args:
            symbols: List of symbols (e.g., ["XAUUSD", "BTCUSD"])
            timeframe: Bar timeframe (default "1m")

        Raises:
            RuntimeError: If not connected
        """
        if not self._pubsub:
            raise RuntimeError("Not connected - call connect() first")

        channels = [f"bars:{symbol}:{timeframe}" for symbol in symbols]

        await self._pubsub.subscribe(*channels)
        self._subscriptions.update(channels)

        logger.info(
            "Subscribed to %d bar channels: %s",
            len(channels),
            ", ".join(channels)
        )

    async def unsubscribe(
        self,
        symbols: list[str],
        timeframe: str = "1m"
    ) -> None:
        """Unsubscribe from bar channels.

        Args:
            symbols: List of symbols to unsubscribe
            timeframe: Bar timeframe

        Raises:
            RuntimeError: If not connected
        """
        if not self._pubsub:
            raise RuntimeError("Not connected - call connect() first")

        channels = [f"bars:{symbol}:{timeframe}" for symbol in symbols]

        await self._pubsub.unsubscribe(*channels)
        self._subscriptions.difference_update(channels)

        logger.info("Unsubscribed from %d channels", len(channels))

    async def listen_bars(self) -> AsyncIterator[Bar]:
        """Async generator yielding Bar objects from subscribed channels.

        Handles connection errors by attempting reconnection with backoff.
        Malformed messages are logged and skipped (not raised).

        Yields:
            Bar: Parsed OHLCV bar data

        Raises:
            RuntimeError: If not connected

        Example:
            async for bar in adapter.listen_bars():
                print(f"{bar.symbol}: close={bar.close}")
        """
        if not self._pubsub:
            raise RuntimeError("Not connected - call connect() first")

        while True:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0  # 1 second timeout for cancellation check
                )

                if message is None:
                    continue

                if message["type"] != "message":
                    continue

                try:
                    bar = Bar.from_json(message["data"])

                    # Optional callback for routing
                    if self._on_bar_callback:
                        self._on_bar_callback(bar)

                    yield bar

                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(
                        "Failed to parse bar: %s - %s",
                        e,
                        message["data"][:100]
                    )

            except redis.exceptions.ConnectionError as e:
                logger.error("Redis connection error: %s", e)
                await self.reconnect()

    def set_bar_callback(
        self,
        callback: Callable[[Bar], None] | None
    ) -> None:
        """Set callback for bar routing (used by signal router).

        Args:
            callback: Function to call for each received bar, or None
        """
        self._on_bar_callback = callback

    def get_subscription_count(self) -> int:
        """Get count of active channel subscriptions.

        Returns:
            Number of subscribed channels
        """
        return len(self._subscriptions)

    async def __aenter__(self) -> RedisAdapter:
        """Async context manager entry - connect."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - disconnect."""
        await self.disconnect()
```

### Testing Requirements

**Unit Test Example:**
```python
# tests/unit/test_bar_model.py
import pytest
from datetime import datetime, timezone
from src.adapters.redis_models import Bar


class TestBar:
    def test_valid_bar_creation(self):
        bar = Bar(
            symbol="XAUUSD",
            timeframe="1m",
            time=datetime.now(timezone.utc),
            open=1850.00,
            high=1851.50,
            low=1849.80,
            close=1850.45,
            volume=1234.5
        )
        assert bar.symbol == "XAUUSD"
        assert bar.close == 1850.45

    def test_from_json_valid(self):
        json_data = '''
        {
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "time": "2025-12-03T14:32:00Z",
            "open": 1850.00,
            "high": 1851.50,
            "low": 1849.80,
            "close": 1850.45,
            "volume": 1234.5
        }
        '''
        bar = Bar.from_json(json_data)
        assert bar.symbol == "XAUUSD"
        assert bar.volume == 1234.5

    def test_from_json_bytes(self):
        json_bytes = b'{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":1234.5}'
        bar = Bar.from_json(json_bytes)
        assert bar.symbol == "XAUUSD"

    def test_channel_name(self):
        bar = Bar(
            symbol="BTCUSD",
            timeframe="5m",
            time=datetime.now(timezone.utc),
            open=45000, high=45100, low=44900, close=45050, volume=100
        )
        assert bar.channel_name == "bars:BTCUSD:5m"

    def test_high_must_be_gte_low(self):
        with pytest.raises(ValueError, match="high must be >= low"):
            Bar(
                symbol="XAUUSD",
                timeframe="1m",
                time=datetime.now(timezone.utc),
                open=1850.00,
                high=1849.00,  # Invalid: less than low
                low=1850.00,
                close=1850.00,
                volume=100
            )

    def test_volume_must_be_non_negative(self):
        with pytest.raises(ValueError):
            Bar(
                symbol="XAUUSD",
                timeframe="1m",
                time=datetime.now(timezone.utc),
                open=1850.00,
                high=1851.00,
                low=1849.00,
                close=1850.00,
                volume=-100  # Invalid
            )


# tests/unit/test_redis_adapter.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.adapters.redis_adapter import RedisAdapter
from src.adapters.redis_config import RedisConfig


class TestRedisAdapterSubscription:
    @pytest.fixture
    def mock_redis(self):
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            mock_client.pubsub.return_value = mock_pubsub
            mock.from_url.return_value = mock_client
            yield mock, mock_client, mock_pubsub

    @pytest.mark.asyncio
    async def test_subscribe_creates_channels(self, mock_redis):
        _, mock_client, mock_pubsub = mock_redis

        adapter = RedisAdapter()
        await adapter.connect()
        await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")

        mock_pubsub.subscribe.assert_called_once()
        call_args = mock_pubsub.subscribe.call_args[0]
        assert "bars:XAUUSD:1m" in call_args
        assert "bars:BTCUSD:1m" in call_args
        assert len(adapter._subscriptions) == 2

    @pytest.mark.asyncio
    async def test_reconnect_resubscribes(self, mock_redis):
        _, mock_client, mock_pubsub = mock_redis

        adapter = RedisAdapter()
        adapter.config.reconnect_delays = [0]  # No delay for test
        await adapter.connect()
        await adapter.subscribe(["XAUUSD"], timeframe="1m")

        # Simulate reconnect
        await adapter.reconnect()

        # Should have subscribed twice (initial + reconnect)
        assert mock_pubsub.subscribe.call_count == 2
```

**Integration Test Example:**
```python
# tests/integration/test_redis_adapter.py
import asyncio
import os
import pytest
from src.adapters.redis_adapter import RedisAdapter
from src.adapters.redis_models import Bar


@pytest.fixture
def redis_available():
    """Check if Redis is available for testing."""
    return os.environ.get("REDIS_AVAILABLE", "").lower() == "true"


@pytest.mark.integration
class TestRedisAdapterIntegration:
    @pytest.mark.asyncio
    async def test_pub_sub_round_trip(self, redis_available):
        if not redis_available:
            pytest.skip("REDIS_AVAILABLE not set")

        import redis.asyncio as redis

        adapter = RedisAdapter()
        await adapter.connect()
        await adapter.subscribe(["XAUUSD"], timeframe="1m")

        # Publish test bar in background
        async def publisher():
            client = redis.from_url("redis://localhost:6379")
            await asyncio.sleep(0.1)  # Wait for subscription
            bar_json = '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":1234.5}'
            await client.publish("bars:XAUUSD:1m", bar_json)
            await client.aclose()

        publisher_task = asyncio.create_task(publisher())

        # Receive bar with timeout
        received_bar = None
        async for bar in adapter.listen_bars():
            received_bar = bar
            break  # Got one bar, done

        await publisher_task
        await adapter.disconnect()

        assert received_bar is not None
        assert received_bar.symbol == "XAUUSD"
        assert received_bar.close == 1850.45
```

**Test Execution:**
```bash
# From services/trading-engine directory
cd services/trading-engine

# Run all unit tests
uv run pytest tests/unit/ -v

# Run Redis-specific tests
uv run pytest tests/unit/test_bar_model.py tests/unit/test_redis_adapter.py -v

# Run integration tests (requires running Redis)
# Terminal 1: docker run -p 6379:6379 redis:7-alpine
# Terminal 2:
REDIS_AVAILABLE=true uv run pytest tests/integration/test_redis_adapter.py -v -m integration

# Check code quality
uv run ruff check src/adapters/redis_*.py
```

### Previous Story Learnings (Story 2.5)

From Story 2.5 Order Execution Flow implementation:

**Key Patterns Established:**
- **Pydantic models** for all data structures with validation
- **Async context manager** pattern for adapters (`__aenter__`, `__aexit__`)
- **Connection state tracking** with `_ConnectionState` dataclass
- **Exponential backoff** for reconnection: `[1, 2, 4, 8, 16, 30]` seconds
- **AsyncIterator** pattern for streaming data (see `receive_ticks()` in ZmqAdapter)

**Files Created in Story 2.4/2.5:**
- `src/adapters/zmq_adapter.py` - ZMQ socket operations
- `src/adapters/zmq_models.py` - Order, OrderResult, Tick models
- `src/orders/` - Complete order execution module

**CRITICAL Pattern to Follow (from ZmqAdapter):**
```python
# Connection state tracking
@dataclass
class _ConnectionState:
    connected: bool = False
    connecting: bool = False
    last_error: str | None = None

# Async generator pattern
async def receive_ticks(self) -> AsyncIterator[Tick]:
    while True:
        try:
            message = await self._socket.recv()
            yield self._parse_message(message)
        except ConnectionError:
            await self.reconnect()
```

### Git Intelligence (Recent Commits)

From commit `ec816ee` (Story 2.5):
- Created complete `src/orders/` module
- Order, Signal, Trade, Position models
- OrderExecutionService with ZmqAdapter integration
- 308 unit tests passing

From commit `3497c34` (Story 2.4):
- Created ZmqAdapter with SUB/PUB sockets
- Connection state tracking pattern
- Exponential backoff reconnection
- 58 unit tests for ZmqAdapter

**Pattern for RedisAdapter consistency:**
```python
# Reuse ZmqAdapter patterns for consistency
from src.adapters.zmq_adapter import ZmqAdapter  # Reference for patterns

# Similar structure:
# - __init__ with config
# - connect() / disconnect()
# - reconnect() with backoff
# - async iterator for data
# - context manager support
```

### Environment Variables Required

```bash
# Redis Configuration
REDIS_URL=redis://localhost:6379

# Logging
LOG_LEVEL=INFO

# Testing
REDIS_AVAILABLE=true  # For integration tests
```

### Dependencies (pyproject.toml - Already Configured)

```toml
dependencies = [
    "nautilus_trader>=1.200",
    "redis>=5.0",             # CRITICAL: redis-py with async support
    "pyzmq>=25.0",
    "sqlalchemy>=2.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",  # For RedisConfig with env vars
    "pyyaml>=6.0",
    "typer>=0.9",
]
```

### Project Structure Notes

- New `redis_adapter.py`, `redis_models.py`, `redis_config.py` in `src/adapters/`
- Follows existing adapter pattern from `zmq_adapter.py`
- Bar model prepared for routing to strategies (Story 2.7)
- Subscription management for reconnection resilience

### References

- [Source: docs/architecture.md#Redis-Data-Structures] - Redis channel patterns
- [Source: docs/architecture.md#Inter-Service-Communication] - Pub/sub channels
- [Source: docs/epic-2-context.md#Story-2.6] - Story requirements and patterns
- [Source: docs/epics.md#Story-2.6] - Original story definition
- [Source: docs/sprint-artifacts/2-5-order-execution-flow.md] - Previous story patterns
- [Source: Context7 redis-py 2025-12-23] - Async pub/sub patterns and retry configuration

## Dev Agent Record

### Context Reference

- Epic 2 Context: `docs/epic-2-context.md`
- Architecture: `docs/architecture.md`
- PRD: `docs/prd.md`
- Previous Story: `docs/sprint-artifacts/2-5-order-execution-flow.md`

### Agent Model Used

- Story Creation: Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A

### Completion Notes List

- Story created with comprehensive developer context from artifact analysis
- redis-py async pub/sub patterns researched via Context7 MCP (2025-12-23)
- ZmqAdapter patterns from Story 2.4/2.5 documented for consistency
- All acceptance criteria mapped to specific tasks
- Complete implementation patterns provided with code examples
- Test patterns provided for unit and integration testing
- Reconnection with exponential backoff using redis-py Retry class
- **Implementation completed 2025-12-23:**
  - Created Bar Pydantic model with OHLCV validation
  - Created RedisConfig with pydantic-settings for env var support
  - Created RedisAdapter with async pub/sub, reconnection, and callback support
  - 75 new unit tests covering bar model, config, and adapter
  - Integration tests for real Redis pub/sub round-trip
  - All 383 unit tests passing (no regressions)
  - Linting passes with ruff
- **Code Review completed 2025-12-23:**
  - 2 HIGH, 3 MEDIUM issues identified and fixed
  - Added `alias="REDIS_URL"` with `populate_by_name=True` for proper env var support
  - Added `max_reconnect_attempts` config option (0=unlimited) with `MaxReconnectAttemptsError`
  - Fixed `recv_timeout_ms` to actually be used from config
  - Added async callback support via `inspect.iscoroutinefunction()` check
  - 7 new tests added for new functionality
  - All 390 unit tests passing

### File List

Files created:
- `services/trading-engine/src/adapters/redis_adapter.py`
- `services/trading-engine/src/adapters/redis_models.py`
- `services/trading-engine/src/adapters/redis_config.py`
- `services/trading-engine/tests/unit/test_bar_model.py`
- `services/trading-engine/tests/unit/test_redis_config.py`
- `services/trading-engine/tests/unit/test_redis_adapter.py`
- `services/trading-engine/tests/integration/test_redis_pubsub.py`

Files modified:
- `services/trading-engine/src/adapters/__init__.py` - Export RedisAdapter, RedisConfig, Bar

---

## Verification Checklist

### Manual Test Steps

```bash
# 1. Ensure you're in the trading-engine directory
cd services/trading-engine

# 2. Install dependencies
uv sync

# 3. Run unit tests
uv run pytest tests/unit/test_bar_model.py tests/unit/test_redis_adapter.py -v

# 4. Check code quality
uv run ruff check src/adapters/redis_*.py

# 5. Run integration tests (requires running Redis)
# Terminal 1: docker run -p 6379:6379 redis:7-alpine
# Terminal 2:
REDIS_AVAILABLE=true uv run pytest tests/integration/test_redis_adapter.py -v

# 6. Test bar parsing manually
uv run python -c "
from src.adapters.redis_models import Bar

json_data = '''
{
    \"symbol\": \"XAUUSD\",
    \"timeframe\": \"1m\",
    \"time\": \"2025-12-03T14:32:00Z\",
    \"open\": 1850.00,
    \"high\": 1851.50,
    \"low\": 1849.80,
    \"close\": 1850.45,
    \"volume\": 1234.5
}
'''
bar = Bar.from_json(json_data)
print(f'Symbol: {bar.symbol}')
print(f'Close: {bar.close}')
print(f'Channel: {bar.channel_name}')
"
```

### Acceptance Criteria Verification

- [ ] **AC1**: RedisAdapter subscribes to bar channels on initialization
- [ ] **AC2**: Bars received from tv-api via Redis pub/sub and routed
- [ ] **AC3**: Bar model contains all OHLCV fields accessible
- [ ] **AC4**: Reconnection with exponential backoff and re-subscription
- [ ] **AC5**: Uses redis.asyncio for all operations
- [ ] **AC6**: Bar messages validated with Pydantic
- [ ] **AC7**: Unit tests pass
- [ ] **AC8**: Integration tests pass (with Redis)

---

## Definition of Done

- [ ] `src/adapters/redis_adapter.py` implements async pub/sub adapter
- [ ] `src/adapters/redis_models.py` implements Bar model with validation
- [ ] `src/adapters/redis_config.py` implements configuration with pydantic-settings
- [ ] Subscription to bar channels by symbol/timeframe
- [ ] `listen_bars()` async generator yields parsed Bar objects
- [ ] Reconnection with exponential backoff preserves subscriptions
- [ ] All unit tests pass
- [ ] Integration tests pass with running Redis
- [ ] Linting passes: `uv run ruff check src/adapters/`
- [ ] Story status updated to `done`

---

## Troubleshooting

### Common Issues

**No Messages Received**
```bash
# Check Redis is running
docker ps | grep redis

# Check subscription
redis-cli PUBSUB CHANNELS "bars:*"

# Test publish manually
redis-cli PUBLISH bars:XAUUSD:1m '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":1234.5}'
```

**Connection Errors**
```bash
# Verify Redis URL
echo $REDIS_URL

# Test connection
python -c "import redis; r = redis.Redis(); print(r.ping())"
```

**JSON Parse Errors**
```bash
# Check message format matches expected schema
# Ensure all required fields present: symbol, timeframe, time, open, high, low, close, volume
```

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-23 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-23 | redis-py async pub/sub patterns researched via Context7 MCP |
| 2025-12-23 | Aligned with ZmqAdapter patterns from Story 2.4/2.5 |
| 2025-12-23 | Complete implementation patterns provided with test examples |
| 2025-12-23 | **Validation improvements applied:** (1) Added production ConnectionPool note in connect() method; (2) Added symbol naming convention note clarifying XAUUSD vs GOLD; (3) Validation report created at validation-report-2-6-20251223.md with 86% pass rate |
| 2025-12-23 | **Implementation completed:** All 10 tasks completed. 75 new tests added (383 total passing). RedisAdapter, Bar, RedisConfig created. Status updated to Ready for Review. |
| 2025-12-23 | **Code Review (Claude Opus 4.5):** 2 HIGH, 3 MEDIUM issues found and fixed: (1) Added proper env var alias for REDIS_URL; (2) Added max_reconnect_attempts config with MaxReconnectAttemptsError; (3) recv_timeout_ms now used from config; (4) Async callback support added. 7 new tests added (390 total passing). |
