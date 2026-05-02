# Epic 2: Single Account Trading Core - Technical Context

**Created:** 2025-12-20
**Status:** Ready for Development
**Epic:** 2 of 7
**Stories:** 10

---

## Overview

### Problem Statement

With the foundation infrastructure complete (Epic 1), the trading system now needs its core trading functionality. Traders need to configure a single account, connect to MT5 via the bridge, receive market data, and execute trades based on strategy signals. This epic establishes the complete single-account trading flow from configuration to execution.

### Solution

Implement the complete single-account trading pipeline:
- Account model with Pydantic validation and YAML configuration
- MT5 Bridge ZeroMQ server for tick data and order commands
- Trading Engine ZeroMQ adapter for bidirectional communication
- Redis adapter for receiving OHLCV bars from tv-api
- NautilusTrader-based strategy framework
- MA Crossover strategy implementation
- Symbol filtering and CLI control commands

### Scope

**In Scope:**
- Account configuration model and YAML loader (Story 2.1)
- Account lifecycle management start/stop (Story 2.2)
- MT5 Bridge ZeroMQ server implementation (Story 2.3)
- Trading Engine ZeroMQ adapter (Story 2.4)
- Order execution flow (Story 2.5)
- Redis market data subscription (Story 2.6)
- Base strategy framework (Story 2.7)
- MA Crossover strategy (Story 2.8)
- Signal filtering by symbol (Story 2.9)
- CLI engine commands (Story 2.10)

**Out of Scope:**
- Multi-account orchestration (Epic 3)
- FTMO compliance rules (Epic 4)
- State persistence and crash recovery (Epic 5)
- Telegram notifications (Epic 6)

---

## Context for Development

### Current Project State

Epic 1 has completed all foundational infrastructure:

```
Sandboxed/
├── services/
│   ├── tv-api/              # COMPLETE - Go service with WebSocket data collection
│   ├── mt5-bridge/          # SCAFFOLD COMPLETE - Rust ZeroMQ bridge structure
│   │   ├── src/
│   │   │   ├── main.rs          # Entry point with Tokio runtime
│   │   │   ├── lib.rs           # Library exports
│   │   │   ├── zmq_server.rs    # ZeroMQ server placeholder
│   │   │   ├── protocol.rs      # Message protocol placeholder
│   │   │   ├── config.rs        # Configuration loading
│   │   │   ├── handlers/        # Message handlers
│   │   │   └── models/          # Data models
│   │   ├── Cargo.toml           # Dependencies configured
│   │   └── Dockerfile           # Multi-stage build ready
│   ├── trading-engine/      # SCAFFOLD COMPLETE - Python/Nautilus structure
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── __main__.py      # Entry point with CLI placeholder
│   │   │   ├── engine.py        # Engine placeholder
│   │   │   ├── accounts/        # Account management (empty)
│   │   │   ├── strategies/      # Strategy framework (empty)
│   │   │   ├── adapters/        # ZMQ/Redis adapters (empty)
│   │   │   ├── rules/           # Rule engine (empty - Epic 4)
│   │   │   ├── backtesting/     # Backtesting (empty)
│   │   │   ├── state/           # State management (empty - Epic 5)
│   │   │   └── config/          # Configuration (empty)
│   │   ├── pyproject.toml       # Dependencies with nautilus_trader
│   │   ├── uv.lock              # Locked dependencies
│   │   └── Dockerfile           # Multi-stage uv build
│   └── notification/        # SCAFFOLD COMPLETE - Go Telegram bot structure
├── infra/
│   ├── docker/
│   │   └── docker-compose.yml   # Full stack orchestration
│   ├── redis/
│   │   └── redis.conf           # Redis configuration
│   └── timescaledb/
│       └── init.sql             # Complete database schema
├── configs/
│   ├── .env.example             # Documented environment template
│   └── dev/.env                 # Development environment
└── Makefile                     # Build commands ready
```

### NautilusTrader Integration Patterns

Based on Context7 research of NautilusTrader documentation (2025):

#### Strategy Base Class Pattern

```python
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.enums import OrderSide, TimeInForce

class MyStrategyConfig(StrategyConfig):
    """Strategy configuration with Pydantic validation."""
    instrument_id: InstrumentId
    bar_type: BarType
    fast_period: int = 10
    slow_period: int = 20
    trade_size: Decimal

class MyStrategy(Strategy):
    def __init__(self, config: MyStrategyConfig) -> None:
        super().__init__(config)  # REQUIRED: Initialize parent
        # Custom initialization here

    def on_start(self) -> None:
        """Called when strategy starts."""
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        """Called on each bar update."""
        pass

    def on_stop(self) -> None:
        """Called when strategy stops."""
        pass
```

#### Order Factory Pattern

```python
# Market Order
order = self.order_factory.market(
    instrument_id=self.config.instrument_id,
    order_side=OrderSide.BUY,
    quantity=self.instrument.make_qty(1.0),
    time_in_force=TimeInForce.GTC,
)
self.submit_order(order)

# Limit Order
order = self.order_factory.limit(
    instrument_id=self.config.instrument_id,
    order_side=OrderSide.SELL,
    quantity=Quantity.from_int(20),
    price=Price.from_str("5000.00"),
    time_in_force=TimeInForce.GTC,
)
self.submit_order(order)
```

#### Indicator Registration Pattern

```python
from nautilus_trader.indicators.moving_average import ExponentialMovingAverage

def on_start(self) -> None:
    # CORRECT order: Register BEFORE requesting data
    self.register_indicator_for_bars(self.bar_type, self.fast_ema)
    self.register_indicator_for_bars(self.bar_type, self.slow_ema)

    # Request historical data (indicators auto-updated)
    self.request_bars(self.bar_type)

    # Subscribe to live data
    self.subscribe_bars(self.bar_type)
```

#### Position Management Pattern

```python
@property
def is_flat(self) -> bool:
    return self.position is None

@property
def is_long(self) -> bool:
    return self.position and self.position.side == PositionSide.LONG

@property
def is_short(self) -> bool:
    return self.position and self.position.side == PositionSide.SHORT

def check_signals(self):
    if fast_ema > slow_ema and self.is_flat:
        self.go_long()
    elif fast_ema < slow_ema and self.is_long:
        self.close_position(self.position)
```

### ZeroMQ Communication Patterns

#### MT5 Bridge Ports (Rust)
| Port | Pattern | Direction | Purpose |
|------|---------|-----------|---------|
| 5555 | REQ/REP | MT5 EA → Bridge | Tick data, heartbeats |
| 5556 | PUB | Bridge → Engine | Tick broadcasts |
| 5557 | REQ/REP | Engine → Bridge | Order commands |

#### Message Protocol (JSON)

**Tick Message (MT5 EA → Bridge):**
```json
{
  "type": "tick",
  "account_id": "ftmo-gold-001",
  "symbol": "XAUUSD",
  "bid": 1850.25,
  "ask": 1850.45,
  "timestamp": "2025-12-03T14:32:15.123Z"
}
```

**Order Command (Engine → Bridge):**
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

**Order Result (Bridge → Engine):**
```json
{
  "type": "order_result",
  "order_id": "ORDER-UUID-123",
  "status": "filled",
  "fill_price": 1850.47,
  "slippage": 0.02,
  "timestamp": "2025-12-03T14:32:15.456Z"
}
```

### Redis Data Patterns

**Bar Channel:** `bars:{symbol}:{timeframe}`

**Bar Message Format:**
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

**Account Status Key:** `account:{account_id}:status`

### Files to Reference

| File | Purpose |
|------|---------|
| `docs/architecture.md` | Complete architecture specification |
| `docs/prd.md` | Product requirements document |
| `docs/epics.md` | Full epic and story definitions |
| `docs/epic-1-context.md` | Foundation infrastructure context |
| `services/tv-api/` | Reference Go service implementation |
| `services/trading-engine/pyproject.toml` | Python dependencies |
| `services/mt5-bridge/Cargo.toml` | Rust dependencies |

### Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Python package manager | **uv** | Fast, modern, Docker-friendly |
| Trading framework | **NautilusTrader 1.x** | Event-driven, backtest-live parity |
| Configuration | **Pydantic** | Type validation, env var support |
| CLI framework | **Click or Typer** | Easy to use, good documentation |
| ZMQ Python library | **pyzmq** | Official binding, asyncio support |
| Redis library | **redis-py** | Standard, asyncio pub/sub |
| Rust async runtime | **Tokio** | Industry standard for async Rust |
| Rust ZMQ library | **zeromq or tmq** | Tokio-compatible bindings |

---

## Implementation Plan

### Story 2.1: Account Model and Configuration

**Goal:** Define trading account configuration in YAML with Pydantic validation

**Tasks:**
- [ ] Create `src/accounts/account.py` with Account Pydantic model
- [ ] Create `src/config/loader.py` for YAML configuration loading
- [ ] Implement environment variable resolution for `password_env` fields
- [ ] Add validation for required fields (id, name, type, mt5 config)
- [ ] Create `configs/accounts.yaml.example` template
- [ ] Write unit tests for configuration loading

**Key Patterns:**
```python
from pydantic import BaseModel, Field
from typing import Optional, List

class MT5Config(BaseModel):
    server: str
    login: int
    password_env: str  # Environment variable name

class AccountConfig(BaseModel):
    id: str
    name: str
    type: str  # prop_firm, personal, demo
    prop_firm: Optional[str] = None
    mt5: MT5Config
    strategy: str
    strategy_params: dict = Field(default_factory=dict)
    signal_filter: dict
    status: str = "active"
```

**Acceptance Criteria:**
- [ ] Configuration loaded from YAML validates correctly
- [ ] Invalid configurations produce clear error messages
- [ ] Environment variables resolved for passwords

**Prerequisites:** Epic 1 (Story 1.6)

---

### Story 2.2: Account Lifecycle Management (Start/Stop)

**Goal:** Control account trading state via CLI and internal API

**Tasks:**
- [ ] Create `src/accounts/account_manager.py` with AccountManager class
- [ ] Implement account state machine (active, paused, stopped, error)
- [ ] Store account status in Redis: `account:{account_id}:status`
- [ ] Add CLI commands: `start`, `stop`, `status`
- [ ] Implement graceful state transitions

**Account States:**
```
active ←→ paused
  ↓         ↓
stopped ← error
```

**Acceptance Criteria:**
- [ ] `trading-engine accounts start <id>` activates account
- [ ] `trading-engine accounts stop <id>` stops without closing positions
- [ ] `trading-engine accounts status` shows all accounts

**Prerequisites:** Story 2.1

---

### Story 2.3: MT5 Bridge ZeroMQ Server

**Goal:** Rust service accepts ZeroMQ connections from MT5 EAs

**Tasks:**
- [ ] Implement REQ/REP server on port 5555 in `src/zmq_server.rs`
- [ ] Implement PUB socket on port 5556 for tick broadcasts
- [ ] Implement message parsing in `src/protocol.rs`
- [ ] Add tick handler in `src/handlers/tick_handler.rs`
- [ ] Implement heartbeat/ACK responses
- [ ] Add connection logging and error handling
- [ ] Write integration tests with mock MT5 client

**ZeroMQ Setup (Rust):**
```rust
use zeromq::{Socket, SocketRecv, SocketSend};
use tokio::sync::mpsc;

pub struct ZmqServer {
    rep_socket: Socket,  // Port 5555 - REQ/REP
    pub_socket: Socket,  // Port 5556 - PUB
}

impl ZmqServer {
    pub async fn new(config: &Config) -> Result<Self> {
        let mut rep = zeromq::RepSocket::new();
        rep.bind(&format!("tcp://0.0.0.0:{}", config.rep_port)).await?;

        let mut pub_socket = zeromq::PubSocket::new();
        pub_socket.bind(&format!("tcp://0.0.0.0:{}", config.pub_port)).await?;

        Ok(Self { rep_socket: rep, pub_socket: pub_socket })
    }
}
```

**Acceptance Criteria:**
- [ ] Bridge accepts connections on port 5555
- [ ] Tick messages published on port 5556 with topic
- [ ] Heartbeats receive ACK responses

**Prerequisites:** Story 1.7

---

### Story 2.4: Trading Engine ZeroMQ Adapter

**Goal:** Python adapter for bidirectional ZeroMQ communication

**Tasks:**
- [ ] Create `src/adapters/zmq_adapter.py` with ZmqAdapter class
- [ ] Implement SUB socket connection to port 5556 (tick data)
- [ ] Implement REQ socket connection to port 5557 (orders)
- [ ] Add asyncio integration with pyzmq
- [ ] Implement reconnection with exponential backoff
- [ ] Route received ticks to appropriate account
- [ ] Write unit tests with mock ZMQ sockets

**Adapter Pattern:**
```python
import asyncio
import zmq
import zmq.asyncio

class ZmqAdapter:
    def __init__(self, config: ZmqConfig):
        self.context = zmq.asyncio.Context()
        self.sub_socket = self.context.socket(zmq.SUB)
        self.req_socket = self.context.socket(zmq.REQ)
        self.reconnect_delays = [1, 2, 4, 8, 16, 30]

    async def connect(self):
        self.sub_socket.connect(f"tcp://{self.config.bridge_host}:5556")
        self.sub_socket.subscribe(b"tick:")  # Subscribe to all tick topics
        self.req_socket.connect(f"tcp://{self.config.bridge_host}:5557")

    async def send_order(self, order: dict) -> dict:
        await self.req_socket.send_json(order)
        return await asyncio.wait_for(
            self.req_socket.recv_json(),
            timeout=5.0
        )
```

**Acceptance Criteria:**
- [ ] Adapter receives tick data from mt5-bridge
- [ ] Orders sent and results received within timeout
- [ ] Automatic reconnection on connection loss

**Prerequisites:** Story 2.3

---

### Story 2.5: Order Execution Flow

**Goal:** Complete order lifecycle from signal to MT5 execution

**Tasks:**
- [ ] Create order model with states (pending, filled, rejected, cancelled)
- [ ] Implement order creation from strategy signals
- [ ] Add UUID generation for order IDs
- [ ] Track slippage on fills
- [ ] Record executed trades in account position tracker
- [ ] Implement idempotency check for duplicate prevention
- [ ] Write integration tests for order flow

**Order Flow:**
```
Strategy Signal → Order Creation → ZMQ Send → MT5 Execution → Result Handling
     │                                                              │
     └──────────────── Position Tracking ←─────────────────────────┘
```

**Acceptance Criteria:**
- [ ] BUY/SELL signals create proper order commands
- [ ] Execution results update position tracking
- [ ] Rejected orders logged with reasons

**Prerequisites:** Story 2.4

---

### Story 2.6: Redis Market Data Subscription

**Goal:** Receive OHLCV bars from tv-api via Redis pub/sub

**Tasks:**
- [ ] Create `src/adapters/redis_adapter.py` with RedisAdapter class
- [ ] Implement asyncio pub/sub subscription
- [ ] Parse bar JSON into Bar model
- [ ] Route bars to appropriate account strategies based on symbol filter
- [ ] Maintain subscription list for reconnection
- [ ] Implement reconnection with re-subscription
- [ ] Write unit tests with mock Redis

**Redis Adapter Pattern:**
```python
import redis.asyncio as redis

class RedisAdapter:
    def __init__(self, config: RedisConfig):
        self.redis = redis.Redis.from_url(config.redis_url)
        self.pubsub = self.redis.pubsub()
        self.subscriptions: set[str] = set()

    async def subscribe(self, symbols: list[str], timeframe: str = "1m"):
        channels = [f"bars:{symbol}:{timeframe}" for symbol in symbols]
        await self.pubsub.subscribe(*channels)
        self.subscriptions.update(channels)

    async def listen(self):
        async for message in self.pubsub.listen():
            if message["type"] == "message":
                bar = self._parse_bar(message["data"])
                yield bar
```

**Acceptance Criteria:**
- [ ] Engine receives bars from Redis channels
- [ ] Bars routed to correct account strategy
- [ ] Re-subscription after reconnection

**Prerequisites:** Story 1.6

---

### Story 2.7: Basic Strategy Framework

**Goal:** NautilusTrader-based strategy base class

**Tasks:**
- [ ] Create `src/strategies/base_strategy.py` with BaseStrategy class
- [ ] Inherit from NautilusTrader Strategy class
- [ ] Implement standard lifecycle handlers (on_start, on_stop, on_bar, on_tick)
- [ ] Create signal enum (BUY, SELL, CLOSE, NONE)
- [ ] Create `src/strategies/position_sizer.py` for lot size calculation
- [ ] Add strategy registry for dynamic loading
- [ ] Write unit tests for base class

**Base Strategy Pattern:**
```python
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.config import StrategyConfig
from enum import Enum

class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    NONE = "NONE"

class BaseStrategyConfig(StrategyConfig):
    instrument_id: str
    bar_type: str
    trade_size: Decimal

class BaseStrategy(Strategy):
    def __init__(self, config: BaseStrategyConfig):
        super().__init__(config)
        self._signal = Signal.NONE

    def on_bar(self, bar: Bar) -> None:
        signal = self.generate_signal(bar)
        if signal != Signal.NONE:
            self._execute_signal(signal)

    def generate_signal(self, bar: Bar) -> Signal:
        """Override in subclass."""
        raise NotImplementedError

    def _execute_signal(self, signal: Signal):
        if signal == Signal.BUY and self.is_flat:
            self._go_long()
        elif signal == Signal.SELL and self.is_flat:
            self._go_short()
        elif signal == Signal.CLOSE and not self.is_flat:
            self.close_all_positions(self.config.instrument_id)
```

**Acceptance Criteria:**
- [ ] BaseStrategy inherits from NautilusTrader Strategy
- [ ] on_bar/on_tick handlers implemented
- [ ] Signal generation framework ready for strategies

**Prerequisites:** Story 2.6

---

### Story 2.8: MA Crossover Strategy Implementation

**Goal:** Moving Average crossover strategy for trend following

**Tasks:**
- [ ] Create `src/strategies/ma_crossover.py` with MACrossoverStrategy
- [ ] Implement fast/slow EMA calculation
- [ ] Detect crossover events (fast crosses above/below slow)
- [ ] Generate BUY on bullish crossover, SELL on bearish
- [ ] Maintain rolling price window for MA calculation
- [ ] Close existing position before reversing
- [ ] Write unit tests with mock bar data

**MA Crossover Pattern:**
```python
class MACrossoverConfig(BaseStrategyConfig):
    fast_period: int = 20
    slow_period: int = 50

class MACrossoverStrategy(BaseStrategy):
    def __init__(self, config: MACrossoverConfig):
        super().__init__(config)
        self.fast_ema = ExponentialMovingAverage(config.fast_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_period)
        self.prev_fast = None
        self.prev_slow = None

    def on_start(self):
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
        self.subscribe_bars(self.config.bar_type)

    def generate_signal(self, bar: Bar) -> Signal:
        if not self.fast_ema.initialized or not self.slow_ema.initialized:
            return Signal.NONE

        fast = self.fast_ema.value
        slow = self.slow_ema.value

        # Detect crossover
        if self.prev_fast and self.prev_slow:
            if self.prev_fast <= self.prev_slow and fast > slow:
                return Signal.BUY  # Bullish crossover
            elif self.prev_fast >= self.prev_slow and fast < slow:
                return Signal.SELL  # Bearish crossover

        self.prev_fast = fast
        self.prev_slow = slow
        return Signal.NONE
```

**Acceptance Criteria:**
- [ ] Strategy calculates fast/slow EMAs correctly
- [ ] Crossover detection generates correct signals
- [ ] Existing positions closed before reversal

**Prerequisites:** Story 2.7

---

### Story 2.9: Signal Filtering by Symbol

**Goal:** Route signals only for configured symbols

**Tasks:**
- [ ] Implement symbol filter in signal router
- [ ] Check account's `signal_filter.symbols` before routing
- [ ] Case-insensitive symbol matching
- [ ] Log filtered signals at DEBUG level
- [ ] Support multiple symbols per account
- [ ] Write unit tests for filtering logic

**Filter Implementation:**
```python
class SignalRouter:
    def __init__(self, accounts: list[Account]):
        self.accounts = {acc.id: acc for acc in accounts}

    def should_process(self, account_id: str, symbol: str) -> bool:
        account = self.accounts.get(account_id)
        if not account:
            return False

        allowed_symbols = [s.upper() for s in account.signal_filter.get("symbols", [])]
        return symbol.upper() in allowed_symbols

    def route_bar(self, bar: Bar, account_id: str):
        if self.should_process(account_id, bar.symbol):
            account.strategy.on_bar(bar)
        else:
            logger.debug(f"Filtered bar for {bar.symbol} - not in account {account_id} filter")
```

**Acceptance Criteria:**
- [ ] Bars for allowed symbols processed
- [ ] Bars for non-allowed symbols ignored
- [ ] Filtering logged at DEBUG level

**Prerequisites:** Story 2.8

---

### Story 2.10: CLI Engine Commands

**Goal:** Command-line interface for engine control

**Tasks:**
- [ ] Implement CLI with Click or Typer in `src/__main__.py`
- [ ] Add commands: start, stop, status, accounts, config
- [ ] Implement `--dry-run` flag for validation
- [ ] Implement `--verbose` flag for debug output
- [ ] Add config dump with secrets masked
- [ ] Show connection status (Redis, MT5 bridge)
- [ ] Write integration tests for CLI

**CLI Commands:**
```bash
# Start engine
trading-engine start
trading-engine start --dry-run  # Validate only

# Stop engine
trading-engine stop

# Status
trading-engine status

# Account management
trading-engine accounts list
trading-engine accounts start ftmo-gold-001
trading-engine accounts stop ftmo-gold-001
trading-engine accounts status ftmo-gold-001

# Configuration
trading-engine config dump      # Show config (secrets masked)
trading-engine config validate  # Validate configuration
```

**Acceptance Criteria:**
- [ ] All commands execute correctly
- [ ] `--dry-run` validates without trading
- [ ] Status shows connection health

**Prerequisites:** Story 2.2

---

## Additional Context

### Dependencies Between Stories

```
Story 2.1 (Account Model) ──► Story 2.2 (Lifecycle) ──► Story 2.10 (CLI)
                                    │
Story 2.3 (MT5 Bridge ZMQ) ──► Story 2.4 (Engine ZMQ) ──► Story 2.5 (Order Execution)
                                                                │
Story 2.6 (Redis Adapter) ──► Story 2.7 (Strategy Framework) ──┤
                                    │                           │
                                    ▼                           ▼
                              Story 2.8 (MA Crossover) ──► Story 2.9 (Signal Filter)
```

### Testing Strategy

| Story | Test Type | Verification |
|-------|-----------|--------------|
| 2.1 | Unit | Pydantic validation, config loading |
| 2.2 | Unit + Integration | State transitions, Redis storage |
| 2.3 | Integration | ZMQ connections, message parsing |
| 2.4 | Unit + Integration | Socket connections, reconnection |
| 2.5 | Integration | Full order flow, position tracking |
| 2.6 | Unit + Integration | Pub/sub, bar parsing |
| 2.7 | Unit | Strategy lifecycle, signal handling |
| 2.8 | Unit | MA calculation, crossover detection |
| 2.9 | Unit | Symbol filtering logic |
| 2.10 | Integration | CLI commands, dry-run mode |

### Risk Considerations

| Risk | Mitigation |
|------|------------|
| NautilusTrader version compatibility | Pin exact version in pyproject.toml |
| ZeroMQ library differences (Rust) | Test both zeromq-rs and tmq crates |
| Asyncio complexity in Python | Use structured concurrency patterns |
| Order execution latency | Measure and log order round-trip time |
| MT5 EA disconnection | Implement heartbeat monitoring |

### Key NautilusTrader Patterns to Follow

1. **Always call super().__init__(config)** in strategy constructor
2. **Register indicators BEFORE requesting historical data**
3. **Use order_factory for all order creation**
4. **Check is_flat/is_long/is_short before trading**
5. **Subscribe to data in on_start(), unsubscribe in on_stop()**
6. **Handle position events for P&L tracking**

### Environment Variables Required

```bash
# MT5 Credentials (per account)
FTMO_PASS_001=<mt5_password>

# Redis
REDIS_URL=redis://localhost:6379

# ZeroMQ
ZMQ_BRIDGE_HOST=localhost
ZMQ_REP_PORT=5555
ZMQ_PUB_PORT=5556
ZMQ_REQ_PORT=5557

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

---

**Document Generated:** 2025-12-20
**Author:** BMad (via BMAD Framework)
**Status:** Ready for Story Development
**NautilusTrader Documentation:** Researched via Context7 MCP
