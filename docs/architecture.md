# Architecture

## Executive Summary

Event-driven automated trading system for **multi-account, multi-prop-firm trading**, architected as a **monorepo with independent microservices**. The system leverages a polyglot tech stack optimized for each service's requirements: Go for I/O-bound services, Rust for latency-critical messaging, and Python for trading logic with Nautilus Trader.

**Version:** 3.0 - Multi-Account Architecture
**Last Updated:** 2025-12-07

## Project Context

**Project:** Multi-Account Trading System
**Domain:** Fintech (High Complexity)
**Type:** Developer Tool
**Architecture:** Monorepo with Independent Microservices

**Supported Account Types:**
| Type | Examples | Rules |
|------|----------|-------|
| Prop Firm | FTMO, The5ers, WeMasterTrade | Built-in presets |
| Personal | Own capital accounts | Custom rules |
| Demo/Test | Paper trading, backtesting | Optional rules |

**Core Services:**
| Service | Language | Purpose |
|---------|----------|---------|
| tv-api | Go | TradingView WebSocket data collector |
| mt5-bridge | Rust | MT5 ZeroMQ bridge (latency-critical) |
| trading-engine | Python | Nautilus Trader core, strategies, multi-account management |
| notification | Go | Telegram alerts and notifications |

**What Makes This Special:**
- **Multi-Account Support**: Run multiple accounts simultaneously with independent strategies
- **Pluggable Rule Engine**: Built-in prop firm presets + fully customizable YAML rules
- **Polyglot Optimization**: Right language for each service's requirements
- **Service Independence**: No shared code, independent deployment
- **Risk Isolation**: Account-level risk management, failures don't cascade
- **Backtest-Reality Alignment**: Same codebase for backtest and live trading
- **Docker-Managed Infrastructure**: Reproducible, portable deployment

---

## System Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          SANDBOXED MONOREPO                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────────────────┐  │
│  │   tv-api     │   │  mt5-bridge  │   │      trading-engine        │  │
│  │    (Go)      │   │    (Rust)    │   │    (Python/Nautilus)       │  │
│  │              │   │              │   │                            │  │
│  │ TradingView  │   │  MT5 ↔ ZMQ  │   │  ┌────────────────────┐    │  │
│  │  WebSocket   │   │    Bridge    │   │  │  Account Manager   │    │  │
│  │              │   │  (per acct)  │   │  ├────────────────────┤    │  │
│  │              │   │              │   │  │ Acc1 │ Acc2 │ Acc3 │    │  │
│  │              │   │              │   │  │ FTMO │5ers │Custom│    │  │
│  │              │   │              │   │  └────────────────────┘    │  │
│  │              │   │              │   │  ┌────────────────────┐    │  │
│  │              │   │              │   │  │   Rule Engine      │    │  │
│  │              │   │              │   │  │  (pluggable)       │    │  │
│  │              │   │              │   │  └────────────────────┘    │  │
│  └──────┬───────┘   └──────┬───────┘   └─────────────┬──────────────┘  │
│         │                  │                         │                  │
│         │    ┌─────────────┴─────────────────────────┘                  │
│         │    │                                                          │
│         ▼    ▼                                                          │
│  ┌──────────────────┐    ┌──────────────────┐                          │
│  │      Redis       │    │   TimescaleDB    │                          │
│  │   (Hot Cache)    │    │   (Historical)   │                          │
│  └──────────────────┘    └──────────────────┘                          │
│                                 │                                       │
│                                 ▼                                       │
│                     ┌──────────────────────┐                           │
│                     │     notification     │                           │
│                     │        (Go)          │                           │
│                     │    Telegram Bot      │                           │
│                     └──────────────────────┘                           │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                       INFRASTRUCTURE (Docker)                           │
│   Redis 7.2+ │ TimescaleDB/PostgreSQL 16+ │ ZeroMQ │ Docker Network    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow Diagram

```
┌─────────────────┐                              ┌─────────────────┐
│   TradingView   │                              │   MT5 Terminal  │
│   (External)    │                              │    (Broker)     │
└────────┬────────┘                              └────────┬────────┘
         │ WebSocket                                      │ ZeroMQ
         ▼                                                ▼
┌─────────────────┐                              ┌─────────────────┐
│     tv-api      │                              │   mt5-bridge    │
│      (Go)       │                              │     (Rust)      │
└────────┬────────┘                              └────────┬────────┘
         │                                                │
         │ Store OHLCV                      Tick Data     │ Order Execution
         ▼                                     │          │
┌─────────────────┐                            │          │
│     Redis       │◄───────────────────────────┘          │
│  (Hot Cache)    │                                       │
└────────┬────────┘                                       │
         │                                                │
         │ Bar Events              ┌──────────────────────┘
         ▼                         ▼
┌──────────────────────────────────────────────┐
│              trading-engine                   │
│           (Python/Nautilus)                   │
│                                              │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │
│  │Strategy │  │  Risk   │  │ Compliance  │  │
│  │ Engine  │  │ Manager │  │   Engine    │  │
│  └─────────┘  └─────────┘  └─────────────┘  │
└──────────────────┬───────────────────────────┘
                   │
         ┌─────────┴─────────┐
         │                   │
         ▼                   ▼
┌─────────────────┐  ┌─────────────────┐
│   TimescaleDB   │  │   notification  │
│  (Historical)   │  │      (Go)       │
└─────────────────┘  └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │    Telegram     │
                     │   (External)    │
                     └─────────────────┘
```

---

## Monorepo Structure

```
Sandboxed/
├── .bmad/                          # BMAD framework
├── docs/                           # Documentation
│   ├── architecture.md             # This document
│   ├── prd.md                      # Product Requirements
│   └── product-brief-*.md          # Product Briefs
│
├── services/                       # 🔥 Independent microservices
│   │
│   ├── tv-api/                     # TradingView Data Collector (Go)
│   │   ├── cmd/
│   │   │   └── server/
│   │   │       └── main.go
│   │   ├── internal/
│   │   │   ├── handlers/
│   │   │   ├── models/
│   │   │   ├── storage/
│   │   │   └── websocket/
│   │   ├── pkg/                    # Public packages (if needed)
│   │   ├── Dockerfile
│   │   ├── go.mod
│   │   ├── go.sum
│   │   └── README.md
│   │
│   ├── mt5-bridge/                 # MT5 ZeroMQ Bridge (Rust)
│   │   ├── src/
│   │   │   ├── main.rs
│   │   │   ├── lib.rs
│   │   │   ├── zmq_server.rs
│   │   │   ├── protocol.rs
│   │   │   └── config.rs
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   ├── Cargo.toml
│   │   └── README.md
│   │
│   ├── trading-engine/             # Trading Core (Python/Nautilus)
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── __main__.py
│   │   │   ├── strategies/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base_strategy.py
│   │   │   │   └── ma_crossover.py
│   │   │   ├── adapters/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── redis_adapter.py
│   │   │   │   └── zmq_adapter.py
│   │   │   ├── risk/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── ftmo_rules.py
│   │   │   │   └── position_sizer.py
│   │   │   └── backtesting/
│   │   │       ├── __init__.py
│   │   │       └── execution_model.py
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   ├── pyproject.toml          # Project config (uv compatible)
│   │   ├── uv.lock                 # Lock file (uv)
│   │   └── README.md
│   │
│   └── notification/               # Telegram Bot (Go)
│       ├── cmd/
│       │   └── bot/
│       │       └── main.go
│       ├── internal/
│       │   ├── telegram/
│       │   ├── handlers/
│       │   └── formatters/
│       ├── Dockerfile
│       ├── go.mod
│       └── README.md
│
├── infra/                          # 🔥 Infrastructure configs
│   ├── docker/
│   │   ├── docker-compose.yml      # Base stack (shared)
│   │   ├── docker-compose.dev.yml  # Dev overrides (optional)
│   │   └── docker-compose.prod.yml # Production overrides (create when needed)
│   ├── redis/
│   │   └── redis.conf
│   ├── timescaledb/
│   │   └── init.sql
│   └── scripts/
│       ├── setup.sh
│       └── teardown.sh
│
├── configs/                        # 🔥 Environment configs
│   ├── .env.example
│   ├── dev/
│   │   └── .env
│   └── prod/
│       └── .env
│
├── scripts/                        # Dev utilities
│   ├── build-all.sh
│   ├── lint-all.sh
│   └── test-all.sh
│
├── .gitignore
├── CLAUDE.md
├── Makefile                        # Unified commands
└── README.md
```

### Design Principles

1. **Service Independence**
   - Each service is completely self-contained
   - No shared code between services
   - Independent versioning and deployment
   - Own Dockerfile, dependencies, and README

2. **Polyglot Optimization**
   - Go: I/O-bound services (tv-api, notification) - fast compilation, excellent concurrency
   - Rust: Performance-critical messaging (mt5-bridge) - zero-cost abstractions, no GC
   - Python: Domain logic with Nautilus (trading-engine) - rich ecosystem, Nautilus requirement

3. **Infrastructure as Code**
   - All infra configs in `/infra` directory
   - Docker Compose for local and production
   - Environment configs separated by deployment target

4. **Extensibility**
   - Add new services: create folder in `/services`
   - Add new infra components: extend docker-compose
   - Add new environments: create folder in `/configs`

---

## Services Architecture

### 1. TV-API Service (Go)

**Purpose:** TradingView WebSocket data collector and processor

**Directory Structure:**
```
services/tv-api/
├── cmd/
│   ├── tv-chart/                # Chart data collector
│   │   ├── main.go
│   │   └── main_storage.go
│   ├── tv-quote/                # Quote data collector
│   │   └── main.go
│   ├── tv-cli/                  # CLI utility
│   │   └── main.go
│   ├── benchmark/               # Performance benchmark
│   │   └── main.go
│   └── storage-test/            # Storage testing
│       └── main.go
├── internal/
│   ├── auth/                    # Authentication (credentials, user)
│   ├── config/                  # Configuration loading & validation
│   ├── display/                 # Display manager
│   ├── logging/                 # Logging utilities
│   ├── protocol/                # TradingView protocol (parser, compression)
│   ├── session/                 # Session management (chart, quote, reconnection)
│   ├── store/                   # Storage (Redis, TimescaleDB)
│   └── transport/               # WebSocket transport, heartbeat
├── pkg/
│   └── tradingview/             # Public TradingView client library
│       ├── client.go
│       ├── chart.go
│       ├── quote.go
│       └── types.go
├── bin/                         # Compiled binaries
├── Dockerfile
├── go.mod
├── go.sum
├── config.yaml
└── README.md
```

**Components:**
| Binary | Purpose |
|--------|---------|
| `tv-chart` | Collects OHLCV chart data from TradingView |
| `tv-quote` | Collects real-time quote/tick data |
| `tv-cli` | CLI utility for testing and debugging |

**Responsibilities:**
- Connect to TradingView WebSocket API
- Collect OHLCV candles (1m/5m timeframes) via `tv-chart`
- Collect real-time quotes via `tv-quote`
- Store data in Redis (hot cache) and TimescaleDB (historical)
- Automatic reconnection with exponential backoff

**Technology:**
- Language: Go 1.21+
- WebSocket: gorilla/websocket
- Storage: go-redis/redis, TimescaleDB (pgx)
- Config: YAML-based configuration

**Interfaces:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Inbound | WebSocket | - | TradingView stream |
| Outbound | Redis | 6379 | OHLCV candles, quotes |
| Outbound | PostgreSQL | 5432 | Historical data |

**Status:** Existing, operational

---

### 2. MT5-Bridge Service (Rust)

**Purpose:** High-performance bridge between MetaTrader 5 and trading system

**Directory Structure:**
```
services/mt5-bridge/
├── src/
│   ├── main.rs                  # Entry point
│   ├── lib.rs                   # Library root
│   ├── zmq_server.rs            # ZeroMQ server implementation
│   ├── protocol.rs              # Message protocol definitions
│   ├── handlers/
│   │   ├── mod.rs
│   │   ├── tick_handler.rs      # Handle incoming ticks
│   │   └── order_handler.rs     # Handle order execution
│   ├── models/
│   │   ├── mod.rs
│   │   ├── tick.rs
│   │   └── order.rs
│   └── config.rs                # Configuration
├── tests/
│   ├── integration_tests.rs
│   └── protocol_tests.rs
├── Dockerfile
├── Cargo.toml
└── README.md
```

**Responsibilities:**
- Receive tick data from MT5 EA via ZeroMQ
- Forward bid/ask spreads to trading engine
- Receive trade commands from trading engine
- Execute orders on MT5 with confirmation tracking
- Monitor execution quality (slippage, latency)

**Technology:**
- Language: Rust 1.75+
- Async Runtime: Tokio
- ZeroMQ: zeromq-rs or tmq
- Serialization: serde, serde_json
- Logging: tracing

**Why Rust:**
- Zero-cost abstractions for latency-critical messaging
- Memory safety without GC pauses
- Excellent ZeroMQ ecosystem
- Bridge runs 24/7 - reliability is paramount

**Interfaces:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Inbound | ZeroMQ REQ/REP | 5555 | MT5 EA commands |
| Outbound | ZeroMQ PUB | 5556 | Tick data to engine |
| Inbound | ZeroMQ SUB | 5557 | Orders from engine |

**Message Protocol:**
```rust
// Tick message from MT5
{
    "type": "tick",
    "symbol": "XAUUSD",
    "bid": 1850.25,
    "ask": 1850.45,
    "timestamp": "2025-12-03T14:32:15.123Z"
}

// Order command to MT5
{
    "type": "order",
    "action": "BUY",
    "symbol": "XAUUSD",
    "volume": 0.1,
    "price": 1850.45,
    "sl": 1845.00,
    "tp": 1860.00,
    "order_id": "ORDER-123"
}

// Order response from MT5
{
    "type": "order_result",
    "order_id": "ORDER-123",
    "status": "filled",
    "fill_price": 1850.47,
    "slippage": 0.02,
    "timestamp": "2025-12-03T14:32:15.456Z"
}
```

---

### 3. Trading-Engine Service (Python)

**Purpose:** Core trading logic with Nautilus Trader framework, multi-account management, and pluggable rule engine

**Directory Structure:**
```
services/trading-engine/
├── src/
│   ├── __init__.py
│   ├── __main__.py              # CLI entry point
│   ├── engine.py                # Main engine orchestration
│   │
│   ├── accounts/                # 🔥 NEW: Multi-account management
│   │   ├── __init__.py
│   │   ├── account_manager.py   # Account lifecycle management
│   │   ├── account.py           # Account model
│   │   └── signal_router.py     # Route signals to accounts
│   │
│   ├── strategies/              # Trading strategies
│   │   ├── __init__.py
│   │   ├── base_strategy.py     # Base class with compliance
│   │   ├── ma_crossover.py      # Example strategy
│   │   └── position_sizer.py    # Account-aware sizing
│   │
│   ├── adapters/                # External integrations
│   │   ├── __init__.py
│   │   ├── redis_adapter.py     # Redis data adapter
│   │   └── zmq_adapter.py       # ZeroMQ execution adapter (per account)
│   │
│   ├── rules/                   # 🔥 NEW: Pluggable Rule Engine
│   │   ├── __init__.py
│   │   ├── engine.py            # Rule engine core
│   │   ├── base_rule.py         # Abstract rule interface
│   │   ├── validators.py        # Rule validators
│   │   ├── audit_logger.py      # Compliance audit trail
│   │   ├── presets/             # Built-in prop firm presets
│   │   │   ├── __init__.py
│   │   │   ├── ftmo.yaml        # FTMO rules
│   │   │   ├── the5ers.yaml     # The5ers rules
│   │   │   └── wmt.yaml         # WeMasterTrade rules
│   │   └── types/               # Rule type implementations
│   │       ├── __init__.py
│   │       ├── drawdown.py      # Drawdown rules (daily, max, trailing)
│   │       └── time_based.py    # Trading hours, sessions
│   │
│   ├── backtesting/             # Backtest framework
│   │   ├── __init__.py
│   │   ├── execution_model.py   # Realistic execution
│   │   ├── spread_model.py      # Dynamic spreads
│   │   └── walk_forward.py      # Walk-forward analysis
│   │
│   ├── state/                   # State management
│   │   ├── __init__.py
│   │   ├── redis_snapshots.py   # State persistence (per account)
│   │   └── crash_recovery.py    # Recovery logic
│   │
│   └── config/                  # Configuration
│       ├── __init__.py
│       ├── loader.py
│       ├── accounts.yaml        # 🔥 NEW: Account configurations
│       └── symbols.yaml
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── Dockerfile
├── pyproject.toml              # Project config (uv compatible)
├── uv.lock                     # Lock file (uv)
└── README.md
```

**Responsibilities:**
- **Multi-Account Management**: Run multiple accounts simultaneously
- **Strategy Execution**: Event-driven signal generation (per account)
- **Pluggable Rule Engine**: Built-in presets + custom YAML rules
- **Risk Isolation**: Account-level risk, failures don't cascade
- **Signal Routing**: Each account filters signals independently
- **Backtesting**: Realistic execution model with account context
- **State Management**: Per-account state persistence

**Technology:**
- Language: Python 3.11+
- Package Manager: uv (fast Python package installer)
- Framework: Nautilus Trader 1.x
- Async: asyncio
- Storage: redis-py, psycopg2
- ZeroMQ: pyzmq

**Key Components:**

| Component | Purpose |
|-----------|---------|
| `accounts/` | Multi-account lifecycle, signal routing |
| `strategies/` | Nautilus Strategy implementations |
| `adapters/` | Redis (data) + ZeroMQ (execution per account) |
| `rules/` | Pluggable rule engine with presets + custom rules |
| `backtesting/` | Realistic execution model |
| `state/` | Per-account Redis snapshots, crash recovery |

**Interfaces:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Inbound | Redis SUB | 6379 | OHLCV candles |
| Inbound | ZeroMQ SUB | 5556 | Tick data |
| Outbound | ZeroMQ PUB | 5557 | Order commands (per account) |
| Outbound | Redis PUB | 6379 | Alerts to notification |
| Outbound | PostgreSQL | 5432 | Trade history, audit (per account) |

---

### Backtest Framework (trading-engine sub-system)

The backtest framework lives under `services/trading-engine/src/backtesting/`
and replays historical bars through **the same rule engine** used in live
trading, so FTMO breaches surface before any live account hits them.

**Layering (top-down call order):**

```
typer CLI  →  ParameterSweep / WalkForward  →  run_backtest(job)  →  BacktestRunner  →  Nautilus BacktestEngine
   │                │                               │                      │
   │                │                               │                      └─ FtmoComplianceActor (Nautilus Actor)
   │                │                               │                                │
   │                │                               │                                └─ RuleEngine (Epic 4, unchanged)
   │                │                               │
   │                │                               └─ BacktestJobConfig (Pydantic) → instrument / data / strategy / FTMO
   │                │
   │                └─ grid + random search,
   │                  ProcessPoolExecutor fan-out,
   │                  early-stop skip-record
   │
   └─ `backtest run | sweep | walkforward`
```

**Key design decisions:**

1. **Indicators subclass `nautilus_trader.indicators.base.Indicator`** so the
   same code path updates during live and backtest runs. Custom Supertrend,
   ADX, and session-anchored VWAP live alongside re-exports of Nautilus
   built-ins (ATR, RSI, Bollinger, Donchian).
2. **FTMO rules inject via a Nautilus `Actor`**, not a Strategy hook. The
   `FtmoComplianceActor` subscribes to order/position events, builds
   `AccountState` from Portfolio + Cache each bar, and calls the existing
   `RuleEngine`. Breaches are deduplicated by `(date, rule_name)`.
3. **`BacktestJobConfig` is the single serializable job description** — a
   Pydantic-frozen model with a discriminated-union `data` field
   (synthetic / TimescaleDB / Parquet). It crosses `ProcessPoolExecutor`
   boundaries as JSON; workers reconstruct the `BacktestRunner` in-process
   because Nautilus engines are not pickle-safe.
4. **Parameter sweep is skip-record on early-stop**: combos that breach a
   drawdown threshold are retained in the result set with
   `status="early_stop"` so the user still sees the full parameter map.
   Aborting the whole sweep would hide mostly-good regions.
5. **Walk-forward derives per-fold seeds** (`seed + fold_idx`) so random
   search draws different combos on each fold, avoiding correlated
   in-sample selection.
6. **Cache-aside Parquet layer** for backtest data: `CachedBarLoader`
   composes `TimescaleBarLoader` + `ParquetBarLoader`. Cache key includes
   a SHA-256 fingerprint of min/max/count from a TimescaleDB metadata
   query, so late-arriving bar corrections invalidate the cache
   automatically.
7. **`BracketStrategyMixin`** (added in 8.9) collapses the bracket-order
   boilerplate shared by Supertrend, Donchian, RSI MR, Bollinger MR, and
   ORB. Signal generation + reversal policy stay in subclasses; last-bar
   reads, balance reads, and SL/TP/qty math live in the mixin.

**Runbook:** `docs/runbooks/backtesting.md` — CLI walkthroughs, job YAML
schema, common errors.

**Test surface:**

- Unit: 50+ tests covering facade, sweep, walk-forward, metrics, CLI.
- Integration smoke: 1 test per strategy on 500 synthetic bars
  (MACrossover, Supertrend, Donchian, RSI MR, Bollinger MR, ORB) plus
  sweep + walk-forward smokes (<3 s total).

---

### 4. Notification Service (Go)

**Purpose:** Alert and notification delivery via Telegram

**Directory Structure:**
```
services/notification/
├── cmd/
│   └── bot/
│       └── main.go              # Entry point
├── internal/
│   ├── telegram/
│   │   ├── bot.go               # Telegram bot client
│   │   └── commands.go          # Bot commands
│   ├── handlers/
│   │   ├── trade_handler.go     # Trade notifications
│   │   ├── risk_handler.go      # Risk alerts
│   │   └── health_handler.go    # System health
│   ├── formatters/
│   │   ├── trade_formatter.go   # Format trade messages
│   │   └── alert_formatter.go   # Format alerts
│   └── subscriber/
│       └── redis_subscriber.go  # Subscribe to alerts
├── Dockerfile
├── go.mod
└── README.md
```

**Responsibilities:**
- Trade notifications (entry/exit with P&L)
- FTMO limit warnings (70-80% threshold alerts)
- System health alerts (connection drops, errors)
- Daily/weekly summary reports
- Command interface (status queries, emergency stop)

**Technology:**
- Language: Go 1.21+
- Telegram: go-telegram-bot-api
- Redis: go-redis/redis
- Config: viper

**Why Go:**
- Lightweight, efficient for I/O-bound service
- Consistent with tv-api (shared knowledge)
- Fast startup, low memory footprint
- Excellent Telegram bot libraries

**Interfaces:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Inbound | Redis SUB | 6379 | Alert messages |
| Outbound | HTTPS | 443 | Telegram API |

**Alert Message Format:**
```
🔵 TRADE EXECUTED
Symbol: GOLD
Action: BUY 0.10 lots
Entry: $1,850.25
Reason: MA crossover (20/50 SMA)
Daily P&L: -$350.00 (-0.35%)
Time: 14:32:15 UTC

🟡 RISK WARNING
Daily Loss: 4.2% of 5.0% limit
Remaining: 0.8% ($800)
Action: Monitor closely

🔴 SYSTEM ERROR
Component: MT5-Bridge
Error: Connection timeout
Action: Reconnecting (attempt 2/5)
Status: Trading paused
```

---

## Inter-Service Communication

### Communication Matrix

| From | To | Protocol | Port | Data Type | Pattern |
|------|-----|----------|------|-----------|---------|
| tv-api | Redis | Redis Protocol | 6379 | OHLCV Candles | PUBLISH |
| tv-api | TimescaleDB | PostgreSQL | 5432 | Historical Data | INSERT |
| MT5 EA | mt5-bridge | ZeroMQ REQ/REP | 5555 | Ticks, Order Results | Request/Reply |
| mt5-bridge | trading-engine | ZeroMQ PUB/SUB | 5556 | Market Data | Publish |
| trading-engine | mt5-bridge | ZeroMQ REQ/REP | 5557 | Trade Commands | Request/Reply |
| trading-engine | Redis | Redis Protocol | 6379 | State, Alerts | GET/SET/PUBLISH |
| trading-engine | TimescaleDB | PostgreSQL | 5432 | Trades, Audit | INSERT |
| notification | Redis | Redis Protocol | 6379 | Alert Messages | SUBSCRIBE |
| notification | Telegram | HTTPS | 443 | Messages | HTTP POST |

### ZeroMQ Patterns

**REQ/REP Pattern (mt5-bridge ↔ MT5 EA):**
```
MT5 EA                          mt5-bridge
   │                                 │
   │─── REQ: tick_data ────────────▶│
   │◀── REP: ack ──────────────────│
   │                                 │
   │◀── REQ: order_command ────────│ (from trading-engine)
   │─── REP: order_result ─────────▶│
```

**PUB/SUB Pattern (mt5-bridge → trading-engine):**
```
mt5-bridge                    trading-engine
   │                                 │
   │─── PUB: tick_data ────────────▶│ (topic: XAUUSD)
   │─── PUB: tick_data ────────────▶│ (topic: BTCUSD)
   │                                 │
```

### Redis Pub/Sub Channels

| Channel | Publisher | Subscriber | Data |
|---------|-----------|------------|------|
| `bars:GOLD:1m` | tv-api | trading-engine | OHLCV candles |
| `bars:BTC:5m` | tv-api | trading-engine | OHLCV candles |
| `alerts:trade` | trading-engine | notification | Trade events |
| `alerts:risk` | trading-engine | notification | Risk warnings |
| `alerts:system` | any service | notification | System alerts |

---

## Technology Stack Summary

### Core Technologies

| Component | Technology | Version | Justification |
|-----------|------------|---------|---------------|
| **tv-api** | Go | 1.21+ | Existing service, excellent WebSocket handling |
| **mt5-bridge** | Rust | 1.75+ | Zero-latency ZeroMQ, memory safety, reliability |
| **trading-engine** | Python | 3.11+ | Nautilus Trader requirement |
| **notification** | Go | 1.21+ | Lightweight, efficient for I/O-bound service |

### Frameworks & Libraries

| Service | Key Libraries |
|---------|--------------|
| **tv-api** | gorilla/websocket, go-redis, pgx, viper |
| **mt5-bridge** | tokio, zeromq-rs, serde, tracing |
| **trading-engine** | nautilus_trader, redis-py, pyzmq, sqlalchemy |
| **notification** | go-telegram-bot-api, go-redis, viper |

### Infrastructure

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| Cache | Redis | 7.2+ | Hot data, pub/sub messaging |
| Database | TimescaleDB | PG16+ | Historical data, time-series optimized |
| Messaging | ZeroMQ | 4.3+ | Low-latency inter-process communication |
| Container | Docker | 24+ | Deployment consistency |
| Orchestration | Docker Compose | 2.x | Service orchestration |

---

## Infrastructure Architecture

### Docker Network

```yaml
networks:
  trading-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

### Service Configuration

```yaml
# infra/docker/docker-compose.yml
version: '3.8'

services:
  # ================== INFRASTRUCTURE ==================
  redis:
    image: redis:7-alpine
    container_name: trading-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
      - ./redis/redis.conf:/usr/local/etc/redis/redis.conf
    command: redis-server /usr/local/etc/redis/redis.conf
    networks:
      - trading-net
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3

  timescaledb:
    image: timescale/timescaledb:latest-pg16
    container_name: trading-timescaledb
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-trading}
      POSTGRES_USER: ${POSTGRES_USER:-trading}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - timescale_data:/var/lib/postgresql/data
      - ./timescaledb/init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - trading-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-trading}"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ================== APPLICATION SERVICES ==================
  tv-api:
    build:
      context: ../../services/tv-api
      dockerfile: Dockerfile
    container_name: trading-tv-api
    environment:
      REDIS_URL: redis:6379
      TIMESCALE_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@timescaledb:5432/${POSTGRES_DB}
      SESSION_ID: ${SESSION_ID}
      SESSION_SIGN: ${SESSION_SIGN}
    depends_on:
      redis:
        condition: service_healthy
      timescaledb:
        condition: service_healthy
    networks:
      - trading-net
    restart: unless-stopped

  mt5-bridge:
    build:
      context: ../../services/mt5-bridge
      dockerfile: Dockerfile
    container_name: trading-mt5-bridge
    ports:
      - "5555:5555"  # REQ/REP with MT5 EA
      - "5556:5556"  # PUB tick data
      - "5557:5557"  # SUB order commands
    environment:
      RUST_LOG: info
      ZMQ_REQ_PORT: 5555
      ZMQ_PUB_PORT: 5556
      ZMQ_SUB_PORT: 5557
    networks:
      - trading-net
    restart: unless-stopped

  trading-engine:
    build:
      context: ../../services/trading-engine
      dockerfile: Dockerfile
    container_name: trading-engine
    environment:
      REDIS_URL: redis://redis:6379
      TIMESCALE_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@timescaledb:5432/${POSTGRES_DB}
      ZMQ_BRIDGE_HOST: mt5-bridge
      ZMQ_PUB_PORT: 5556
      ZMQ_SUB_PORT: 5557
      TRADING_MODE: ${TRADING_MODE:-paper}
    depends_on:
      redis:
        condition: service_healthy
      timescaledb:
        condition: service_healthy
      mt5-bridge:
        condition: service_started
    volumes:
      - engine_data:/app/data
    networks:
      - trading-net
    restart: unless-stopped

  notification:
    build:
      context: ../../services/notification
      dockerfile: Dockerfile
    container_name: trading-notification
    environment:
      REDIS_URL: redis:6379
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      TELEGRAM_CHAT_ID: ${TELEGRAM_CHAT_ID}
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - trading-net
    restart: unless-stopped

volumes:
  redis_data:
  timescale_data:
  engine_data:

networks:
  trading-net:
    driver: bridge
```

### Environment Configuration

```bash
# configs/.env.example

# ================== INFRASTRUCTURE ==================
POSTGRES_DB=trading
POSTGRES_USER=trading
POSTGRES_PASSWORD=<secure_password>
REDIS_PASSWORD=<secure_password>

# ================== TV-API ==================
SESSION_ID=<tradingview_session_id>
SESSION_SIGN=<tradingview_session_sign>

# ================== TRADING ENGINE ==================
TRADING_MODE=paper  # paper | live

# ================== NOTIFICATION ==================
TELEGRAM_BOT_TOKEN=<telegram_bot_token>
TELEGRAM_CHAT_ID=<telegram_chat_id>

# ================== LOGGING ==================
LOG_LEVEL=info
LOG_FORMAT=json
```

---

## Multi-Account Architecture

### Account Manager

The Account Manager is responsible for managing multiple trading accounts simultaneously, each with its own strategy and rule configuration.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Account Manager                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐        │
│  │    Account 1    │  │    Account 2    │  │    Account 3    │  ...   │
│  │                 │  │                 │  │                 │        │
│  │  Type: FTMO    │  │  Type: The5ers │  │  Type: Custom   │        │
│  │  Strategy: A   │  │  Strategy: B   │  │  Strategy: C   │        │
│  │  Rules: Preset │  │  Rules: Preset │  │  Rules: YAML   │        │
│  │  Status: Active│  │  Status: Active│  │  Status: Paused│        │
│  │                 │  │                 │  │                 │        │
│  │  ┌───────────┐ │  │  ┌───────────┐ │  │  ┌───────────┐ │        │
│  │  │MT5 Conn   │ │  │  │MT5 Conn   │ │  │  │MT5 Conn   │ │        │
│  │  │Server: A  │ │  │  │Server: B  │ │  │  │Server: C  │ │        │
│  │  └───────────┘ │  │  └───────────┘ │  │  └───────────┘ │        │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘        │
│           │                    │                    │                  │
│           └────────────────────┼────────────────────┘                  │
│                                ▼                                       │
│                    ┌───────────────────────┐                          │
│                    │    Signal Router      │                          │
│                    │  (filter per account) │                          │
│                    └───────────────────────┘                          │
│                                ▲                                       │
│                                │                                       │
│                    ┌───────────────────────┐                          │
│                    │   Market Data Feed    │                          │
│                    │    (shared source)    │                          │
│                    └───────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Account Configuration

```yaml
# accounts.yaml
accounts:
  - id: "ftmo-gold-001"
    name: "FTMO Gold Challenge"
    type: "prop_firm"
    prop_firm: "ftmo"           # Uses preset rules
    mt5:
      server: "FTMO-Server"
      login: 12345678
      password_env: "FTMO_PASS_001"
    strategy: "ma_crossover"
    strategy_params:
      fast_period: 20
      slow_period: 50
    signal_filter:
      symbols: ["XAUUSD"]
      sessions: ["london", "new_york"]
    status: "active"

  - id: "5ers-btc-001"
    name: "The5ers BTC Account"
    type: "prop_firm"
    prop_firm: "the5ers"        # Uses preset rules
    mt5:
      server: "The5ers-Server"
      login: 87654321
      password_env: "5ERS_PASS_001"
    strategy: "breakout"
    strategy_params:
      lookback: 20
    signal_filter:
      symbols: ["BTCUSD"]
    status: "active"

  - id: "personal-001"
    name: "Personal Account"
    type: "custom"
    rules_file: "my_rules.yaml"  # Custom rules
    mt5:
      server: "ICMarkets-MT5"
      login: 11111111
      password_env: "PERSONAL_PASS"
    strategy: "scalper"
    signal_filter:
      symbols: ["EURUSD", "GBPUSD"]
      max_spread_pips: 1.5
    status: "active"
```

---

## Pluggable Rule Engine

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Rule Engine                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        Rule Loader                               │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │   │
│  │  │  Preset Loader  │  │  YAML Loader    │  │  DB Loader      │  │   │
│  │  │  (prop firms)   │  │  (custom files) │  │  (future)       │  │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Rule Registry                               │   │
│  │                                                                  │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐│   │
│  │  │Drawdown  │ │Time-based│ │Position  │ │Symbol    │ │Frequency││   │
│  │  │Rules     │ │Rules     │ │Rules     │ │Rules     │ │Rules   ││   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────┘│   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Rule Validator                              │   │
│  │  - Pre-trade validation (before order)                          │   │
│  │  - Post-trade monitoring (after fill)                           │   │
│  │  - Continuous monitoring (every bar)                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Audit Logger                                │   │
│  │  - All rule checks logged                                       │   │
│  │  - Violation history                                            │   │
│  │  - Compliance reports                                           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Rule Types

| Category | Rule Type | Description | Example |
|----------|-----------|-------------|---------|
| **Drawdown** | `daily_loss_limit` | Max loss per day | 5% of balance |
| | `max_drawdown` | Max total drawdown | 10% from peak |
| | `trailing_drawdown` | Trailing stop on equity | 5% from high water mark |
| **Time-based** | `trading_hours` | Allowed trading hours | 08:00-17:00 UTC |
| | `trading_sessions` | Allowed sessions | London, New York |
| | `trading_days` | Allowed days | Mon-Fri |
| | `news_blackout` | Pause around news | ±30 min from high-impact |
| **Position** | `max_position_size` | Max lots per trade | 1.0 lots |
| | `max_open_positions` | Max concurrent trades | 3 positions |
| | `max_per_symbol` | Max per symbol | 1 position |
| | `max_total_exposure` | Total exposure limit | 5% of balance |
| **Symbol** | `allowed_symbols` | Whitelist symbols | ["XAUUSD", "EURUSD"] |
| | `blocked_symbols` | Blacklist symbols | ["USDJPY"] |
| **Frequency** | `max_trades_per_day` | Daily trade limit | 10 trades |
| | `min_trade_interval` | Cooldown between trades | 5 minutes |
| | `max_trades_per_hour` | Hourly limit | 3 trades |

### Preset Example: FTMO

```yaml
# presets/ftmo.yaml
name: "FTMO Challenge"
version: "2024.1"
description: "FTMO prop firm challenge rules"

rules:
  # Drawdown Rules
  - type: daily_loss_limit
    threshold_percent: 5.0
    reset_time: "00:00"
    timezone: "UTC"
    action: "block_trading"
    warning_at: [70, 80, 90]  # Warn at 70%, 80%, 90% of limit

  - type: max_drawdown
    threshold_percent: 10.0
    reference: "initial_balance"
    action: "block_trading"
    warning_at: [50, 70, 85]

  # Position Rules
  - type: max_position_size
    max_lots: 100.0  # Depends on account size
    scaling: "per_10k_balance"  # 1 lot per $10k

  # Monitoring
  - type: profit_target
    target_percent: 10.0
    action: "notify"

  - type: min_trading_days
    min_days: 4
    action: "notify"
```

### Custom Rule Example

```yaml
# my_rules.yaml
name: "BMad Personal Rules"
version: "1.0"
description: "Custom trading rules for personal account"

rules:
  # Conservative drawdown
  - type: daily_loss_limit
    threshold_percent: 2.0
    action: "block_trading"

  - type: max_drawdown
    threshold_percent: 5.0
    action: "block_trading"

  # Time restrictions
  - type: trading_sessions
    allowed: ["london", "new_york"]
    action: "block_trading"

  - type: trading_hours
    start: "08:00"
    end: "20:00"
    timezone: "UTC"
    action: "block_trading"

  # Position limits
  - type: max_open_positions
    limit: 2
    action: "block_trading"

  - type: max_trades_per_day
    limit: 5
    action: "block_trading"

  # Symbol restrictions
  - type: allowed_symbols
    symbols: ["EURUSD", "GBPUSD", "XAUUSD"]
    action: "block_trading"

  # Custom: Max spread filter
  - type: max_spread
    max_pips: 2.0
    action: "skip_signal"
```

---

## Data Architecture

### Database Schema (TimescaleDB)

```sql
-- infra/timescaledb/init.sql

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ==================== MULTI-ACCOUNT TABLES ====================

-- Prop Firms (presets reference)
CREATE TABLE prop_firms (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    rules_preset VARCHAR(50) NOT NULL,  -- References YAML preset
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default prop firms
INSERT INTO prop_firms (id, name, rules_preset) VALUES
    ('ftmo', 'FTMO', 'ftmo'),
    ('the5ers', 'The5ers', 'the5ers'),
    ('wmt', 'WeMasterTrade', 'wmt');

-- Trading Accounts
CREATE TABLE accounts (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    account_type VARCHAR(20) NOT NULL,  -- 'prop_firm', 'personal', 'demo'
    prop_firm_id VARCHAR(50) REFERENCES prop_firms(id),
    custom_rules_file VARCHAR(255),      -- For custom accounts
    mt5_server VARCHAR(100) NOT NULL,
    mt5_login BIGINT NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    strategy_params JSONB,
    signal_filter JSONB,                 -- Symbols, sessions, etc.
    status VARCHAR(20) DEFAULT 'active', -- 'active', 'paused', 'stopped'
    initial_balance DECIMAL(18, 2),
    current_balance DECIMAL(18, 2),
    peak_balance DECIMAL(18, 2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_accounts_status ON accounts (status);
CREATE INDEX idx_accounts_type ON accounts (account_type);

-- Account Daily Snapshots (for compliance tracking)
CREATE TABLE account_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) REFERENCES accounts(id),
    snapshot_date DATE NOT NULL,
    opening_balance DECIMAL(18, 2),
    closing_balance DECIMAL(18, 2),
    daily_pnl DECIMAL(18, 2),
    daily_pnl_percent DECIMAL(8, 4),
    peak_balance DECIMAL(18, 2),
    drawdown_percent DECIMAL(8, 4),
    trades_count INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(account_id, snapshot_date)
);

CREATE INDEX idx_snapshots_account_date ON account_snapshots (account_id, snapshot_date DESC);

-- ==================== MARKET DATA TABLES ====================

-- OHLCV Candles (hypertable for time-series)
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

SELECT create_hypertable('candles', 'time');
CREATE INDEX idx_candles_symbol_time ON candles (symbol, time DESC);

-- ==================== TRADING TABLES ====================

-- Trades (per account)
CREATE TABLE trades (
    trade_id UUID PRIMARY KEY,
    account_id VARCHAR(50) REFERENCES accounts(id),  -- 🔥 NEW
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
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trades_time ON trades (entry_time DESC);
CREATE INDEX idx_trades_account ON trades (account_id, entry_time DESC);  -- 🔥 NEW
CREATE INDEX idx_trades_strategy ON trades (strategy_name, entry_time DESC);

-- ==================== COMPLIANCE TABLES ====================

-- Rule Violations (per account)
CREATE TABLE rule_violations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) REFERENCES accounts(id),
    timestamp TIMESTAMPTZ NOT NULL,
    rule_type VARCHAR(50) NOT NULL,
    rule_name VARCHAR(100) NOT NULL,
    current_value DECIMAL(18, 4),
    threshold_value DECIMAL(18, 4),
    action_taken VARCHAR(50),  -- 'blocked', 'warned', 'notified'
    order_id UUID,
    context JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('rule_violations', 'timestamp');
CREATE INDEX idx_violations_account ON rule_violations (account_id, timestamp DESC);
CREATE INDEX idx_violations_rule ON rule_violations (rule_type, timestamp DESC);

-- Audit Logs (per account)
CREATE TABLE audit_logs (
    log_id UUID PRIMARY KEY,
    account_id VARCHAR(50) REFERENCES accounts(id),  -- 🔥 NEW
    timestamp TIMESTAMPTZ NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    rule_name VARCHAR(100),
    rule_result VARCHAR(20),
    current_value DECIMAL(18, 4),
    threshold_value DECIMAL(18, 4),
    order_id UUID,
    context JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('audit_logs', 'timestamp');
CREATE INDEX idx_audit_account ON audit_logs (account_id, timestamp DESC);  -- 🔥 NEW
CREATE INDEX idx_audit_rule ON audit_logs (rule_name, timestamp DESC);

-- ==================== PERFORMANCE TABLES ====================

-- Performance Metrics (daily, per account)
CREATE TABLE performance_metrics (
    date DATE NOT NULL,
    account_id VARCHAR(50) REFERENCES accounts(id),  -- 🔥 NEW
    strategy_name VARCHAR(100) NOT NULL,
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    net_profit DECIMAL(18, 2),
    win_rate DECIMAL(8, 4),
    max_drawdown_percent DECIMAL(8, 4),
    sharpe_ratio DECIMAL(8, 4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (date, account_id, strategy_name)  -- 🔥 UPDATED
);

CREATE INDEX idx_metrics_account ON performance_metrics (account_id, date DESC);
```

### Redis Data Structures

```
# ==================== PER-ACCOUNT STATE ====================

# Account State Snapshots (Hash) - per account
Key: snapshot:{account_id}:latest
Example: snapshot:ftmo-gold-001:latest
Fields:
  timestamp: "2025-12-03T14:32:15.123456Z"
  positions: JSON array of open positions
  pending_orders: JSON array
  account_balance: 100000.00
  equity: 99850.00
  peak_balance: 102500.00
  daily_starting_balance: 100500.00
  checksum: SHA256 hash
TTL: 1 hour

# Account Compliance Metrics (Hash) - per account, per day
Key: compliance:{account_id}:daily:{YYYY-MM-DD}
Example: compliance:ftmo-gold-001:daily:2025-12-03
Fields:
  daily_pnl: -350.00
  daily_pnl_percent: -0.35
  peak_balance_today: 101200.00
  trades_count: 5
  max_drawdown_today: 1.2
  rule_violations: 0
  last_trade_time: "2025-12-03T14:32:15Z"
TTL: 7 days

# Account Status (String) - per account
Key: account:{account_id}:status
Example: account:ftmo-gold-001:status
Value: "active" | "paused" | "stopped" | "error"
TTL: None (persistent)

# Account Connection Health (Hash) - per account
Key: account:{account_id}:health
Example: account:ftmo-gold-001:health
Fields:
  mt5_connected: true
  last_tick_time: "2025-12-03T14:32:15.123Z"
  last_heartbeat: "2025-12-03T14:32:10.000Z"
  error_count: 0
  last_error: null
TTL: 60 seconds (heartbeat refresh)

# ==================== SHARED DATA ====================

# Candle Cache (Sorted Set) - shared across accounts
Key: candles:{symbol}:{timeframe}
Example: candles:XAUUSD:1m
Score: timestamp (unix milliseconds)
Value: JSON {open, high, low, close, volume, time}
TTL: 24 hours
Note: Use ZRANGEBYSCORE for time-range queries

# Latest Tick (Hash) - shared, per symbol
Key: tick:{symbol}:latest
Example: tick:XAUUSD:latest
Fields:
  bid: 1850.25
  ask: 1850.45
  spread: 0.20
  time: "2025-12-03T14:32:15.123Z"
TTL: 60 seconds

# ==================== MESSAGING ====================

# Alert Channels (Pub/Sub)
Channel: alerts:trade:{account_id}     # Trade notifications per account
Channel: alerts:risk:{account_id}      # Risk warnings per account
Channel: alerts:system                 # System-wide alerts
Channel: emergency:stop                # Emergency stop signal

# Bar Events (Pub/Sub)
Channel: bars:{symbol}:{timeframe}     # New bar events
Example: bars:XAUUSD:1m

# ==================== SERVICE HEALTH ====================

# Service Health (String) - per service
Key: health:{service_name}
Example: health:tv-api, health:mt5-bridge, health:trading-engine
Value: "healthy" | "degraded" | "unhealthy"
TTL: 30 seconds (heartbeat refresh)

# Service Metadata (Hash) - per service
Key: service:{service_name}:info
Example: service:trading-engine:info
Fields:
  version: "1.0.0"
  started_at: "2025-12-03T08:00:00Z"
  accounts_active: 3
  last_heartbeat: "2025-12-03T14:32:15Z"
TTL: None (persistent, updated on heartbeat)
```

---

## Deployment Architecture

### Development Environment

```bash
# Prerequisites
- Docker 24+
- Docker Compose 2.x
- Make (optional, for Makefile commands)

# Setup
cd Sandboxed
cp configs/.env.example configs/dev/.env
# Edit configs/dev/.env with your credentials

# Start infrastructure
make infra-up  # or: docker compose -f infra/docker/docker-compose.yml up -d redis timescaledb

# Build and start services
make build     # Build all service images
make up        # Start all services
make logs      # View logs
make down      # Stop all services
```

### Production Environment

```bash
# VPS Specifications
- Provider: Digital Ocean, AWS EC2, or similar
- Specs: 8GB RAM, 4 CPU cores, 100GB SSD
- OS: Ubuntu 22.04 LTS
- Cost: ~$50-100/month

# Deployment
ssh user@vps
git clone <repo> /opt/sandboxed
cd /opt/sandboxed
cp configs/.env.example configs/prod/.env
# Configure production credentials

# Start with base compose (production settings via .env)
docker compose -f infra/docker/docker-compose.yml up -d

# Or with production overrides (when docker-compose.prod.yml exists)
# docker compose -f infra/docker/docker-compose.yml \
#                -f infra/docker/docker-compose.prod.yml \
#                up -d
```

**Note:** `docker-compose.prod.yml` should be created when specific production overrides are needed (e.g., resource limits, replicas, external networks). For MVP, the base `docker-compose.yml` with production `.env` is sufficient.

### Makefile Commands

```makefile
# Makefile (root level)

.PHONY: all build up down logs test lint clean help \
        infra-up infra-down infra-logs infra-status \
        build-tv-api build-mt5-bridge build-trading-engine build-notification \
        test-tv-api test-mt5-bridge test-trading-engine test-notification \
        lint-tv-api lint-mt5-bridge lint-trading-engine lint-notification \
        restart

# Variables
COMPOSE_FILE := infra/docker/docker-compose.yml
DOCKER_COMPOSE := docker compose -f $(COMPOSE_FILE)

# Infrastructure
infra-up:
	$(DOCKER_COMPOSE) up -d redis timescaledb

infra-down:
	$(DOCKER_COMPOSE) down

# Build all services
build:
	$(DOCKER_COMPOSE) build

# Start all services
up:
	$(DOCKER_COMPOSE) up -d

# Stop all services
down:
	$(DOCKER_COMPOSE) down

# View logs
logs:
	$(DOCKER_COMPOSE) logs -f

# Restart all services
restart: down up

# Individual service commands
build-tv-api:
	cd services/tv-api && go build -o bin/tv-chart ./cmd/tv-chart
	cd services/tv-api && go build -o bin/tv-quote ./cmd/tv-quote

build-mt5-bridge:
	cd services/mt5-bridge && cargo build --release

build-trading-engine:
	cd services/trading-engine && uv build

build-notification:
	cd services/notification && go build -o bin/bot ./cmd/bot

# Testing
test:
	cd services/trading-engine && uv run pytest
	cd services/tv-api && go test ./...
	cd services/mt5-bridge && cargo test
	cd services/notification && go test ./...

# Linting
lint:
	cd services/trading-engine && uv run ruff check .
	cd services/tv-api && golangci-lint run
	cd services/mt5-bridge && cargo clippy
	cd services/notification && golangci-lint run
```

---

## Security Architecture

### Credential Management

- All secrets via environment variables
- `.env` files never committed to git
- Different credentials for dev/prod environments
- Secrets rotatable without service restart

### Network Security

- All services on internal Docker network
- Only necessary ports exposed to host
- ZeroMQ binds to internal network only
- External APIs over HTTPS

### Data Protection

- Database connections use SSL/TLS
- Redis password authentication
- Audit logs append-only
- Trade data encrypted at rest (filesystem level)

---

## Error Handling Strategy

### Error Categories

| Category | Examples | Handling |
|----------|----------|----------|
| **Transient** | Network timeout, Redis connection lost | Retry with exponential backoff |
| **Recoverable** | MT5 disconnection, WebSocket drop | Reconnect, restore state |
| **Fatal** | Invalid config, DB corruption | Log, alert, shutdown gracefully |
| **Business** | Rule violation, insufficient margin | Block action, notify user |

### Per-Service Error Handling

#### tv-api (Go)
```go
// Retry policy for TradingView WebSocket
type RetryConfig struct {
    MaxAttempts     int           // 5
    InitialBackoff  time.Duration // 1s
    MaxBackoff      time.Duration // 30s
    BackoffFactor   float64       // 2.0
}

// On disconnect:
// 1. Log warning
// 2. Retry with backoff
// 3. After max attempts: alert via Redis, pause data collection
// 4. Continue retrying in background
```

#### mt5-bridge (Rust)
```rust
// ZeroMQ error handling
enum BridgeError {
    ConnectionLost,      // Reconnect, buffer messages
    MessageTimeout,      // Retry, log latency
    InvalidMessage,      // Log, skip, continue
    AccountDisconnected, // Notify engine, pause account
}

// Critical: Never lose order confirmations
// - Buffer unconfirmed orders in memory
// - Persist to Redis on graceful shutdown
// - Replay on restart
```

#### trading-engine (Python)
```python
# Hierarchical error handling
class ErrorHandler:
    def handle(self, error: Exception, context: dict):
        if isinstance(error, TransientError):
            return self.retry_with_backoff(context)
        elif isinstance(error, AccountError):
            return self.pause_account(context["account_id"])
        elif isinstance(error, RuleViolation):
            return self.block_and_notify(context)
        else:
            return self.fatal_shutdown(error)
```

#### notification (Go)
```go
// Telegram API error handling
// - Rate limiting: queue messages, batch send
// - API errors: retry with backoff
// - Never block trading operations
// - Fall back to logging if Telegram unavailable
```

### Circuit Breaker Pattern

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Circuit Breaker States                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌─────────┐         failures > threshold         ┌─────────┐         │
│   │ CLOSED  │ ──────────────────────────────────▶ │  OPEN   │         │
│   │ (normal)│                                      │ (fail)  │         │
│   └────┬────┘                                      └────┬────┘         │
│        │                                                │              │
│        │ success                          timeout       │              │
│        │                                                ▼              │
│        │                                         ┌───────────┐         │
│        └──────────────────────────────────────── │HALF-OPEN │         │
│                                                  │  (test)   │         │
│                                                  └───────────┘         │
│                                                                         │
│   Applied to: MT5 connections, Redis, TimescaleDB                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Recovery & Failover

### State Persistence

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         State Persistence Flow                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   Runtime State (Memory)                                                │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ - Open positions per account                                  │     │
│   │ - Pending orders per account                                  │     │
│   │ - Daily P&L per account                                       │     │
│   │ - Rule engine state                                           │     │
│   └──────────────────────────────────────────────────────────────┘     │
│                              │                                          │
│                              │ Every 5 seconds                          │
│                              ▼                                          │
│   Redis Snapshots (Hot)                                                 │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ Key: snapshot:{account_id}:latest                            │     │
│   │ TTL: 1 hour                                                   │     │
│   └──────────────────────────────────────────────────────────────┘     │
│                              │                                          │
│                              │ Every 1 minute                           │
│                              ▼                                          │
│   TimescaleDB (Cold)                                                    │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ Table: state_snapshots (per account, timestamped)            │     │
│   │ Retention: 7 days                                             │     │
│   └──────────────────────────────────────────────────────────────┘     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Crash Recovery Sequence

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Crash Recovery Sequence                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   1. Engine Startup                                                     │
│      │                                                                  │
│      ▼                                                                  │
│   2. Load account configurations from YAML                              │
│      │                                                                  │
│      ▼                                                                  │
│   3. For each account:                                                  │
│      ├── Check Redis snapshot exists?                                   │
│      │   ├── YES: Load snapshot, validate checksum                     │
│      │   └── NO: Query TimescaleDB for latest state                    │
│      │                                                                  │
│      ▼                                                                  │
│   4. Connect to MT5 (per account)                                       │
│      │                                                                  │
│      ▼                                                                  │
│   5. Reconcile positions:                                               │
│      ├── Compare snapshot positions vs MT5 actual                      │
│      ├── Log discrepancies                                             │
│      └── Use MT5 as source of truth                                    │
│      │                                                                  │
│      ▼                                                                  │
│   6. Recalculate daily P&L from trade history                          │
│      │                                                                  │
│      ▼                                                                  │
│   7. Resume normal operation                                            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Failover Scenarios

| Scenario | Detection | Recovery |
|----------|-----------|----------|
| **Engine crash** | Process exit | Systemd restart, state recovery from Redis |
| **Redis failure** | Connection error | Fallback to TimescaleDB, degraded mode |
| **TimescaleDB failure** | Connection error | Continue with Redis only, queue writes |
| **MT5 disconnect (single)** | ZeroMQ timeout | Pause account, reconnect, resume |
| **MT5 disconnect (all)** | Multiple timeouts | Alert, wait for reconnect, no new trades |
| **Network partition** | Multiple failures | Graceful degradation, preserve positions |

### Position Safety

```python
# CRITICAL: Position safety during recovery
class PositionRecovery:
    """
    Golden Rule: When in doubt, trust MT5 positions over local state.

    Recovery priorities:
    1. Never duplicate orders (check MT5 first)
    2. Never miss exits (sync positions immediately)
    3. Always know current exposure (calculate from MT5)
    """

    def reconcile(self, account_id: str):
        local_positions = self.load_snapshot(account_id)
        mt5_positions = self.query_mt5(account_id)

        for mt5_pos in mt5_positions:
            if mt5_pos not in local_positions:
                self.log_warning(f"Unknown position found: {mt5_pos}")
                self.add_to_local(mt5_pos)

        for local_pos in local_positions:
            if local_pos not in mt5_positions:
                self.log_warning(f"Orphan position in snapshot: {local_pos}")
                self.remove_from_local(local_pos)
```

---

## Graceful Shutdown

### Shutdown Sequence

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Graceful Shutdown Sequence                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   Signal Received (SIGTERM/SIGINT)                                      │
│      │                                                                  │
│      ▼                                                                  │
│   1. Set shutdown flag (atomic)                                         │
│      │                                                                  │
│      ▼                                                                  │
│   2. Stop accepting new signals                                         │
│      ├── Unsubscribe from Redis channels                               │
│      └── Stop processing new bars                                       │
│      │                                                                  │
│      ▼                                                                  │
│   3. Wait for in-flight orders (timeout: 30s)                          │
│      ├── Pending orders: wait for confirmation                         │
│      └── Timeout: log warning, continue shutdown                       │
│      │                                                                  │
│      ▼                                                                  │
│   4. Persist final state                                                │
│      ├── Snapshot all accounts to Redis                                │
│      └── Flush to TimescaleDB                                          │
│      │                                                                  │
│      ▼                                                                  │
│   5. Close connections                                                  │
│      ├── ZeroMQ sockets                                                │
│      ├── Redis connection                                              │
│      └── TimescaleDB connection                                        │
│      │                                                                  │
│      ▼                                                                  │
│   6. Exit with code 0                                                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Signal Handling

```python
# trading-engine signal handling
import signal
import asyncio

class GracefulShutdown:
    def __init__(self):
        self.shutdown_event = asyncio.Event()
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown")
        self.shutdown_event.set()

    async def wait_for_shutdown(self):
        await self.shutdown_event.wait()
        await self._shutdown_sequence()

    async def _shutdown_sequence(self):
        # 1. Stop new signal processing
        await self.signal_router.stop()

        # 2. Wait for in-flight orders (per account)
        for account in self.accounts:
            await account.wait_pending_orders(timeout=30)

        # 3. Persist state
        for account in self.accounts:
            await self.state_manager.snapshot(account.id)

        # 4. Close connections
        await self.close_all_connections()
```

### Emergency Stop

```
Telegram Command: /stop_all

┌─────────────────────────────────────────────────────────────────────────┐
│                         Emergency Stop Flow                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   /stop_all received                                                    │
│      │                                                                  │
│      ▼                                                                  │
│   1. Publish to Redis: "emergency:stop"                                 │
│      │                                                                  │
│      ▼                                                                  │
│   2. Trading Engine receives:                                           │
│      ├── Immediately stop all signal processing                        │
│      ├── Cancel all pending orders (per account)                       │
│      └── Set all accounts to "paused" state                            │
│      │                                                                  │
│      ▼                                                                  │
│   3. Notify user:                                                       │
│      "🔴 EMERGENCY STOP: All accounts paused, X pending orders cancelled"│
│      │                                                                  │
│      ▼                                                                  │
│   4. Positions remain open (manual close if needed)                     │
│                                                                         │
│   Resume: /resume_all (requires confirmation)                           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## MT5 EA Architecture

### EA Component Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     MT5 Expert Advisor (EA)                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   Location: MT5 Terminal (Windows/Wine)                                 │
│   Language: MQL5                                                        │
│   Purpose: Bridge between MT5 and trading system via ZeroMQ             │
│                                                                         │
│   ┌───────────────────────────────────────────────────────────────┐    │
│   │                     ZMQ_Bridge_EA.mq5                          │    │
│   ├───────────────────────────────────────────────────────────────┤    │
│   │                                                                │    │
│   │   OnInit()                                                     │    │
│   │   ├── Initialize ZeroMQ context                               │    │
│   │   ├── Connect REQ socket to mt5-bridge:5555                   │    │
│   │   ├── Subscribe PUB socket to mt5-bridge:5557                 │    │
│   │   └── Start tick forwarding                                    │    │
│   │                                                                │    │
│   │   OnTick()                                                     │    │
│   │   ├── Pack tick data (bid, ask, time)                         │    │
│   │   ├── Send via REQ socket                                     │    │
│   │   └── Wait for ACK (non-blocking)                             │    │
│   │                                                                │    │
│   │   OnTimer() [100ms]                                            │    │
│   │   ├── Check for incoming orders (SUB socket)                  │    │
│   │   ├── Execute order via OrderSend()                           │    │
│   │   └── Send execution result back                               │    │
│   │                                                                │    │
│   │   OnDeinit()                                                   │    │
│   │   ├── Close all ZeroMQ sockets                                │    │
│   │   └── Cleanup context                                          │    │
│   │                                                                │    │
│   └───────────────────────────────────────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Multi-Account MT5 Setup

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   Multi-Account MT5 Deployment                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   Option 1: Multiple MT5 Instances (Recommended for < 5 accounts)       │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                                                                  │  │
│   │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │  │
│   │   │ MT5 Instance │  │ MT5 Instance │  │ MT5 Instance │         │  │
│   │   │   (FTMO)     │  │  (The5ers)   │  │  (Personal)  │         │  │
│   │   │ Port: 5555   │  │ Port: 5565   │  │ Port: 5575   │         │  │
│   │   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │  │
│   │          │                 │                 │                  │  │
│   │          └─────────────────┼─────────────────┘                  │  │
│   │                            │                                    │  │
│   │                            ▼                                    │  │
│   │               ┌────────────────────────┐                        │  │
│   │               │      mt5-bridge        │                        │  │
│   │               │  (multi-port support)  │                        │  │
│   │               └────────────────────────┘                        │  │
│   │                                                                  │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│   Option 2: Single MT5 with Multi-Symbol EA                             │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │   - One MT5 instance, one broker                                │  │
│   │   - EA runs on multiple charts                                  │  │
│   │   - Limited to single broker/prop firm                          │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│   Recommendation: Option 1 for multi-prop-firm trading                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### EA Configuration

```mql5
// ZMQ_Bridge_EA.mq5 - Input parameters
input string   BridgeHost = "localhost";     // mt5-bridge host
input int      ReqPort = 5555;               // REQ/REP port
input int      SubPort = 5557;               // SUB port for orders
input string   AccountID = "ftmo-gold-001";  // Account identifier
input int      TickBufferSize = 100;         // Buffer size for tick batching
input int      HeartbeatMs = 1000;           // Heartbeat interval
```

### Message Flow

```
┌───────────────┐         ┌───────────────┐         ┌───────────────┐
│    MT5 EA     │         │  mt5-bridge   │         │trading-engine │
│   (MQL5)      │         │    (Rust)     │         │   (Python)    │
└───────┬───────┘         └───────┬───────┘         └───────┬───────┘
        │                         │                         │
        │ ──── Tick Data ───────▶ │                         │
        │ {"symbol":"XAUUSD",     │                         │
        │  "bid":1850.25,         │ ──── PUB Tick ────────▶ │
        │  "ask":1850.45}         │                         │
        │                         │                         │
        │ ◀──── ACK ──────────── │                         │
        │                         │                         │
        │                         │ ◀──── Order Request ─── │
        │                         │ {"action":"BUY",        │
        │ ◀──── Order Command ─── │  "symbol":"XAUUSD",     │
        │                         │  "volume":0.1}          │
        │                         │                         │
        │ ──── Execution Result ─▶│                         │
        │ {"status":"filled",     │ ──── Order Result ────▶ │
        │  "fill_price":1850.47}  │                         │
        │                         │                         │
```

---

## Monitoring & Observability

### Health Checks

Each service implements `/health` endpoint or equivalent:

| Service | Health Check |
|---------|--------------|
| tv-api | HTTP GET /health |
| mt5-bridge | ZeroMQ heartbeat |
| trading-engine | Redis heartbeat key |
| notification | Telegram API ping |

### Logging

- All services: Structured JSON logging
- Log levels: DEBUG, INFO, WARN, ERROR
- Centralized via Docker logging driver
- Future: ELK stack or Grafana Loki

### Alerting

- Trading alerts: Telegram (notification service)
- System alerts: Telegram + structured logs
- Critical alerts: Immediate notification

---

## Architecture Decision Records (ADRs)

### ADR-001: Monorepo with Independent Services

**Status:** Accepted

**Context:** Need to organize multiple services (Go, Rust, Python) in a maintainable structure.

**Decision:** Use monorepo structure with completely independent services in `/services` directory.

**Rationale:**
- Single repository simplifies version control and CI/CD
- Independent services enable polyglot development
- No shared code reduces coupling
- Each service has own Dockerfile and dependencies

**Consequences:**
- Positive: Unified codebase, easy navigation, consistent tooling
- Negative: Larger repo size, need careful dependency management

---

### ADR-002: Polyglot Tech Stack

**Status:** Accepted

**Context:** Different services have different performance and development requirements.

**Decision:**
- Go: I/O-bound services (tv-api, notification)
- Rust: Latency-critical messaging (mt5-bridge)
- Python: Trading logic with Nautilus (trading-engine)

**Rationale:**
- Go: Fast development, excellent concurrency, good for web services
- Rust: Zero-cost abstractions, no GC pauses, perfect for bridge
- Python: Nautilus Trader requirement, rich ecosystem

**Consequences:**
- Positive: Optimal performance per service
- Negative: Multiple languages to maintain, different tooling

---

### ADR-003: ZeroMQ for MT5 Communication

**Status:** Accepted

**Context:** Need low-latency communication between MT5 and trading system.

**Decision:** Use ZeroMQ with REQ/REP and PUB/SUB patterns.

**Rationale:**
- Sub-millisecond messaging
- Language-agnostic (works with MQL5, Rust, Python)
- Proven in financial systems
- Simple deployment (no broker required)

**Consequences:**
- Positive: Low latency, reliable messaging
- Negative: Need to implement custom protocol

---

### ADR-004: Redis for Inter-Service Messaging

**Status:** Accepted

**Context:** Services need to communicate events (candles, alerts) efficiently.

**Decision:** Use Redis Pub/Sub for event distribution.

**Rationale:**
- Already using Redis for caching
- Simple Pub/Sub model
- Low latency
- No additional infrastructure

**Consequences:**
- Positive: Simple, fast, unified infrastructure
- Negative: Messages not persisted (acceptable for real-time events)

---

### ADR-005: Docker Compose for Orchestration

**Status:** Accepted

**Context:** Need to orchestrate multiple services and infrastructure.

**Decision:** Use Docker Compose for both development and production.

**Rationale:**
- Simple configuration
- Works for single-node deployment (sufficient for MVP)
- Easy local development
- Future: Migrate to Kubernetes if needed

**Consequences:**
- Positive: Simple deployment, reproducible environments
- Negative: Single-node only (acceptable for MVP)

---

## Testing Strategy

### Testing Pyramid

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Testing Pyramid                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│                            ┌─────────┐                                  │
│                            │  E2E    │  ← Few, slow, high confidence    │
│                            │ Tests   │    (Full system validation)      │
│                          ┌─┴─────────┴─┐                                │
│                          │ Integration │  ← Medium count, service        │
│                          │   Tests     │    boundaries                   │
│                        ┌─┴─────────────┴─┐                              │
│                        │   Unit Tests    │  ← Many, fast, isolated       │
│                        │                 │    (Business logic)           │
│                        └─────────────────┘                              │
│                                                                         │
│   Ratio Target: 70% Unit / 20% Integration / 10% E2E                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Per-Service Testing

#### trading-engine (Python)

```python
# Test structure
services/trading-engine/
├── tests/
│   ├── unit/
│   │   ├── test_account_manager.py    # Account lifecycle
│   │   ├── test_rule_engine.py        # Rule validation logic
│   │   ├── test_signal_router.py      # Signal filtering
│   │   ├── test_position_sizer.py     # Position calculations
│   │   └── test_strategies/           # Strategy logic
│   ├── integration/
│   │   ├── test_redis_adapter.py      # Redis operations
│   │   ├── test_zmq_adapter.py        # ZeroMQ messaging
│   │   ├── test_db_operations.py      # TimescaleDB queries
│   │   └── test_rule_presets.py       # Preset loading
│   ├── e2e/
│   │   └── test_full_trade_flow.py    # Signal → Order → Fill
│   ├── fixtures/
│   │   ├── accounts.yaml              # Test account configs
│   │   ├── rules/                     # Test rule files
│   │   └── market_data/               # Sample OHLCV data
│   └── conftest.py                    # Pytest fixtures

# Key test commands
pytest tests/unit -v                   # Unit tests only
pytest tests/integration -v            # Requires Redis/DB
pytest tests/e2e -v                    # Requires full stack
pytest --cov=src --cov-report=html     # Coverage report
```

#### mt5-bridge (Rust)

```rust
// Test structure
services/mt5-bridge/
├── tests/
│   ├── unit_tests.rs              // Protocol parsing, message handling
│   ├── integration_tests.rs       // ZeroMQ socket operations
│   └── mock_mt5.rs                // Mock MT5 EA for testing

// Key test commands
cargo test                         // All tests
cargo test --lib                   // Unit tests only
cargo test -- --ignored            // Integration tests
cargo llvm-cov                     // Coverage report
```

#### tv-api & notification (Go)

```go
// Test structure
services/tv-api/
├── internal/
│   ├── handlers/
│   │   └── handlers_test.go       // HTTP handlers
│   ├── websocket/
│   │   └── client_test.go         // WebSocket client
│   └── storage/
│       └── redis_test.go          // Redis operations

// Key test commands
go test ./...                      // All tests
go test -race ./...                // With race detector
go test -cover ./...               // Coverage
go test -v -run TestSpecific       // Single test
```

### Critical Test Scenarios

| Category | Scenario | Expected Behavior |
|----------|----------|-------------------|
| **Rule Engine** | Daily loss limit at 4.9% | Allow trade |
| **Rule Engine** | Daily loss limit at 5.1% | Block trade, notify |
| **Rule Engine** | Max drawdown at 9.9% | Allow trade |
| **Rule Engine** | Max drawdown at 10.1% | Block all trading |
| **Multi-Account** | Account A breaches rule | Only Account A paused |
| **Multi-Account** | Account B continues | Unaffected by A |
| **Recovery** | Engine crash with positions | Recover from Redis |
| **Recovery** | Redis unavailable | Fallback to TimescaleDB |
| **Signal Routing** | Signal for XAUUSD | Only XAUUSD accounts receive |
| **Emergency** | /stop_all command | All accounts paused immediately |

### Mocking Strategy

```python
# Mock external dependencies for unit tests
class MockMT5Connection:
    """Mock MT5 for testing without real broker connection"""
    def __init__(self):
        self.positions = []
        self.orders = []

    def get_positions(self) -> List[Position]:
        return self.positions

    def send_order(self, order: Order) -> OrderResult:
        # Simulate fill with configurable slippage
        return OrderResult(
            status="filled",
            fill_price=order.price + random.uniform(-0.5, 0.5),
            slippage=0.02
        )

class MockRedis:
    """In-memory Redis mock for unit tests"""
    def __init__(self):
        self._data = {}
        self._pubsub = defaultdict(list)

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def publish(self, channel: str, message: str):
        for callback in self._pubsub[channel]:
            callback(message)
```

### CI/CD Testing

```yaml
# .github/workflows/test.yml
name: Test Suite

on: [push, pull_request]

jobs:
  test-trading-engine:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
      timescaledb:
        image: timescale/timescaledb:latest-pg16
        ports: ["5432:5432"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
      - run: |
          cd services/trading-engine
          uv sync
          uv run pytest --cov=src

  test-mt5-bridge:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - run: |
          cd services/mt5-bridge
          cargo test

  test-go-services:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: "1.21"
      - run: |
          cd services/tv-api && go test -race ./...
          cd ../notification && go test -race ./...
```

### Performance Testing

```python
# Benchmark critical paths
import pytest

@pytest.mark.benchmark
def test_rule_validation_performance(benchmark):
    """Rule validation must complete in < 50ms"""
    engine = RuleEngine()
    engine.load_preset("ftmo")

    result = benchmark(
        engine.validate_trade,
        account_id="test-001",
        trade=sample_trade
    )

    assert result.duration_ms < 50

@pytest.mark.benchmark
def test_signal_routing_performance(benchmark):
    """Signal routing for 5 accounts must complete in < 10ms"""
    router = SignalRouter(accounts=create_test_accounts(5))

    result = benchmark(
        router.route_signal,
        signal=sample_signal
    )

    assert result.duration_ms < 10
```

---

## Architecture Decision Records (Continued)

### ADR-006: MT5 Multi-Instance Deployment

**Status:** Accepted

**Context:** Need to support multiple prop firm accounts with different brokers.

**Decision:** Deploy separate MT5 instances per account (Option 1 in MT5 EA Architecture).

**Rationale:**
- Each prop firm requires its own MT5 server connection
- Isolation prevents cross-account issues
- Port-based routing is simple and reliable
- Resource overhead acceptable for < 5 accounts

**Consequences:**
- Positive: Complete isolation, simple debugging
- Negative: Higher resource usage, multiple MT5 installations

---

### ADR-007: State Recovery Priority

**Status:** Accepted

**Context:** Need to recover state after crashes without duplicating orders or missing exits.

**Decision:** Use Redis as primary recovery source, TimescaleDB as fallback, MT5 as source of truth for positions.

**Rationale:**
- Redis: Fast, recent state (5-second snapshots)
- TimescaleDB: Durable, 1-minute snapshots
- MT5: Actual positions (authoritative)

**Consequences:**
- Positive: Fast recovery, guaranteed position accuracy
- Negative: Slight complexity in reconciliation logic

---

### ADR-008: Per-Account Redis Keys

**Status:** Accepted

**Context:** Multi-account support requires isolated state in Redis.

**Decision:** Use `{category}:{account_id}:{key}` pattern for all per-account data.

**Rationale:**
- Clear namespace separation
- Easy to query by account
- Supports Redis key pattern matching
- Consistent across all state types

**Consequences:**
- Positive: Clean isolation, easy debugging
- Negative: Slightly longer key names

---

---

## Epic 10 Additions — Operational Hardening (2026-05-01)

The following modules were introduced in Epic 10 and are not reflected in the original directory tree above. All live under `services/trading-engine/`.

### Engine refactor — god-object split (10.1 + 10.2)

`src/engine/` now contains:

| File | Purpose |
|------|---------|
| `config.py` | `EngineConfig` frozen dataclass — DI container replacing 9 optional deps |
| `collaborators.py` | Typed collaborator bundles passed into lifecycle components |
| `lifecycle.py` | `EngineLifecycle` — top-level coordinator: recovery → live → graceful shutdown |
| `recovery_orchestrator.py` | `RecoveryOrchestrator` — cold-start: snapshot load, reconcile, rearm |
| `live_orchestrator.py` | `LiveOrchestrator` — per-account `LiveAccountSession` management |
| `account_session.py` | `LiveAccountSession` state machine (start/stop/add/remove/reload/crash) |
| `actors.py` | Shared `build_compliance_actor` factory used by live + backtest |
| `lock_lost.py` | `LockLostMediator` — Redis lock-lost event propagation |
| `clients/bar_translator.py` | Timeframe parse + Pydantic Bar → Nautilus Bar conversion |
| `clients/order_translator.py` | Nautilus Order → internal `Order`; MARKET only |
| `clients/submit_dispatcher.py` | validate/send/translate → Nautilus filled/rejected/denied/timeout events |
| `clients/redis_data_client.py` | `RedisDataClient` Nautilus `LiveDataClient` subclass; pubsub drain |
| `clients/zmq_execution_client.py` | `ZmqExecutionClient` Nautilus `LiveExecutionClient` subclass |

Original `engine.py` reduced to thin wrapper (~200 LOC); logic split into components above.

### Audit double-entry (10.3)

`src/audit/audit_writer.py` — `AuditWriter` replaces the fire-and-forget `asyncio.create_task(audit.log_*(...))` pattern:

- `log_sync()` — blocks caller until DB commit; required on all `account.*` write paths.
- `log_async()` — enqueues to bounded `asyncio.Queue(10_000)`; back-pressure if full.
- `worker()` — drain loop; batch INSERT every 100 entries or 0.5s.
- `drain()` — called by `GracefulShutdown._persist_final_state()` before DB close.

### Atomic exposure gate (10.4)

`src/execution/exposure_reservation.py` + `src/execution/lua_scripts/`:

- `atomic_reserve.lua` — compare-and-set: read snapshot, check `used + required ≤ max`, write atomically.
- `atomic_release.lua` — rollback reservation on MT5 timeout/reject.
- `ExposureReservation` Python wrapper integrated into `ValidatedZmqAdapter` via opt-in `max_lots_provider`.

### Kill-switch flat positions (10.7)

`src/state/emergency_stop_handler.py` — `EmergencyStopHandler`:

- Subscribes to `emergency:stop` Redis channel.
- For each active account: `query_positions` → opposite-side MARKET close per position → `pause_account`.
- Writes sync audit rows: `EMERGENCY_STOP_TRIGGERED` + `EMERGENCY_STOP_COMPLETE`.
- Wired into `EngineConfig.feature_flags.emergency_stop` + `EngineLifecycle.start/stop`.

### Orders package

`src/orders/close_order_builder.py` — builds opposite-side MARKET close orders for flat-positions flow.

### News blackout rule (10.8)

`src/calendar/` — new package:

| File | Purpose |
|------|---------|
| `calendar_models.py` | `CalendarEvent` + `EventIndex` (bisect-based `active_events_at`) |
| `forex_factory_parser.py` | Tolerant ForexFactory weekly XML parser |
| `economic_calendar_service.py` | Background fetch (1×/day) + Redis 26h TTL cache + static fallback + refresh loop |

`src/rules/types/news_blackout.py` — `NewsBlackoutRule(BaseRule)`:

- Registered in rule parser; late-binds `snapshot_provider`.
- Fail-open WARN when calendar unavailable (never hard-blocks on feed failure).
- Configurable `blackout_minutes_before/after`, `impact_levels`, `symbols_filter`.

### Backtest spread parity (10.9)

`src/backtesting/spread_fee_model.py` — `SpreadAwareFeeModel(FeeModel)` Nautilus subclass:

- Charges `per_lot_usd + spread_pips × pip_value × fill_qty` per fill.
- `commission_profile_to_fee_model` dispatches to `SpreadAwareFeeModel` when `spread_pips` is non-empty; falls back to legacy `PerContractFeeModel`.
- Per-symbol `pip_value` mapping with default 10 USD/pip/lot.
- Swap accrual (`swap_long`/`swap_short`) deferred to 10.9b — requires Nautilus `SimulationModule` for rollover-time accrual.

### Alembic bootstrap (10.10)

`services/trading-engine/alembic/` — replaces raw SQL migration workflow:

| Path | Purpose |
|------|---------|
| `alembic.ini` | Points `sqlalchemy.url` to `DATABASE_URL` env; `postgres+asyncpg→postgres` coercion in `env.py` |
| `alembic/env.py` | Manual revisions only (autogenerate disabled) |
| `alembic/versions/005_state_snapshots.py` … `010_rename_ftmo_audit_events.py` | 6 ported revisions; `upgrade()` executes original SQL; `downgrade()` raises `NotImplementedError` for hypertable-destructive paths |

Run `alembic stamp 010` on an existing DB (already manually migrated) to mark head without re-running. Fresh DB: `alembic upgrade head` runs all 6 revisions.

---

_This Architecture Document v3.0 reflects the complete multi-account trading system design._
_Epic 10 additions appended 2026-05-01._

_Last Updated: 2025-12-07 (original); Epic 10 section added 2026-05-01_
_Author: Winston (Architect Agent)_
