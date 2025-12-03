# Architecture

## Executive Summary

Event-driven automated trading system for FTMO prop firm challenges, architected as a **monorepo with independent microservices**. The system leverages a polyglot tech stack optimized for each service's requirements: Go for I/O-bound services, Rust for latency-critical messaging, and Python for trading logic with Nautilus Trader.

**Version:** 2.0 - Monorepo Architecture
**Last Updated:** 2025-12-03

## Project Context

**Project:** FTMO Trading System
**Domain:** Fintech (High Complexity)
**Type:** Developer Tool
**Architecture:** Monorepo with Independent Microservices

**Core Services:**
| Service | Language | Purpose |
|---------|----------|---------|
| tv-api | Go | TradingView WebSocket data collector |
| mt5-bridge | Rust | MT5 ZeroMQ bridge (latency-critical) |
| trading-engine | Python | Nautilus Trader core, strategies, compliance |
| notification | Go | Telegram alerts and notifications |

**What Makes This Special:**
- **Polyglot Optimization**: Right language for each service's requirements
- **Service Independence**: No shared code, independent deployment
- **Compliance-First Architecture**: FTMO rules as first-class architectural concern
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
│  │ TradingView  │   │  MT5 ↔ ZMQ  │   │  Strategies, Risk,         │  │
│  │  WebSocket   │   │    Bridge    │   │  FTMO Compliance           │  │
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
│   │   ├── pyproject.toml
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
│   │   ├── docker-compose.yml      # Development stack
│   │   ├── docker-compose.dev.yml  # Dev overrides
│   │   └── docker-compose.prod.yml # Production overrides
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
│   └── server/
│       └── main.go              # Entry point
├── internal/
│   ├── handlers/                # HTTP/WebSocket handlers
│   ├── models/                  # Data models
│   ├── storage/                 # Redis/TimescaleDB clients
│   ├── websocket/               # TradingView WS client
│   └── config/                  # Configuration loading
├── pkg/                         # Public packages (if needed)
├── Dockerfile
├── go.mod
├── go.sum
├── config.yaml
└── README.md
```

**Responsibilities:**
- Connect to TradingView WebSocket API
- Collect OHLCV candles (1m/5m timeframes)
- Store data in Redis (hot cache) and TimescaleDB (historical)
- Provide REST API for historical data queries

**Technology:**
- Language: Go 1.21+
- WebSocket: gorilla/websocket
- Storage: go-redis/redis, pgx
- Config: viper

**Interfaces:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Inbound | WebSocket | - | TradingView stream |
| Outbound | Redis | 6379 | OHLCV candles |
| Outbound | PostgreSQL | 5432 | Historical data |
| Outbound | HTTP | 8080 | REST API |

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

**Purpose:** Core trading logic with Nautilus Trader framework

**Directory Structure:**
```
services/trading-engine/
├── src/
│   ├── __init__.py
│   ├── __main__.py              # CLI entry point
│   ├── engine.py                # Main engine orchestration
│   │
│   ├── strategies/              # Trading strategies
│   │   ├── __init__.py
│   │   ├── base_strategy.py     # Base class with compliance
│   │   ├── ma_crossover.py      # Example strategy
│   │   └── position_sizer.py    # FTMO-aware sizing
│   │
│   ├── adapters/                # External integrations
│   │   ├── __init__.py
│   │   ├── redis_adapter.py     # Redis data adapter
│   │   └── zmq_adapter.py       # ZeroMQ execution adapter
│   │
│   ├── risk/                    # Risk & compliance
│   │   ├── __init__.py
│   │   ├── ftmo_rules.py        # FTMO rule engine
│   │   ├── validators.py        # Rule validators
│   │   └── audit_logger.py      # Compliance audit trail
│   │
│   ├── backtesting/             # Backtest framework
│   │   ├── __init__.py
│   │   ├── execution_model.py   # Realistic execution
│   │   ├── spread_model.py      # Dynamic spreads
│   │   └── walk_forward.py      # Walk-forward analysis
│   │
│   ├── state/                   # State management
│   │   ├── __init__.py
│   │   ├── redis_snapshots.py   # State persistence
│   │   └── crash_recovery.py    # Recovery logic
│   │
│   └── config/                  # Configuration
│       ├── __init__.py
│       ├── loader.py
│       ├── ftmo_rules.yaml
│       └── symbols.yaml
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── Dockerfile
├── pyproject.toml
└── README.md
```

**Responsibilities:**
- Strategy execution (event-driven signal generation)
- FTMO rule engine (real-time compliance validation)
- Risk management (position sizing, drawdown limits)
- Backtesting with realistic execution model
- Portfolio state management

**Technology:**
- Language: Python 3.11+
- Framework: Nautilus Trader 1.x
- Async: asyncio
- Storage: redis-py, psycopg2
- ZeroMQ: pyzmq

**Key Components:**

| Component | Purpose |
|-----------|---------|
| `strategies/` | Nautilus Strategy implementations |
| `adapters/` | Redis (data) + ZeroMQ (execution) adapters |
| `risk/` | FTMO rule engine, position sizing |
| `backtesting/` | Realistic execution model |
| `state/` | Redis snapshots, crash recovery |

**Interfaces:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Inbound | Redis SUB | 6379 | OHLCV candles |
| Inbound | ZeroMQ SUB | 5556 | Tick data |
| Outbound | ZeroMQ PUB | 5557 | Order commands |
| Outbound | Redis PUB | 6379 | Alerts to notification |
| Outbound | PostgreSQL | 5432 | Trade history, audit |

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

## Data Architecture

### Database Schema (TimescaleDB)

```sql
-- infra/timescaledb/init.sql

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

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
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_trades_time ON trades (entry_time DESC);
CREATE INDEX idx_trades_strategy ON trades (strategy_name, entry_time DESC);

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
    context JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('audit_logs', 'timestamp');
CREATE INDEX idx_audit_rule ON audit_logs (rule_name, timestamp DESC);

-- Performance Metrics (daily)
CREATE TABLE performance_metrics (
    date DATE NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    net_profit DECIMAL(18, 2),
    win_rate DECIMAL(8, 4),
    max_drawdown_percent DECIMAL(8, 4),
    sharpe_ratio DECIMAL(8, 4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (date, strategy_name)
);
```

### Redis Data Structures

```
# State Snapshots (Hash)
Key: snapshot:latest
Fields:
  timestamp: "2025-12-03T14:32:15.123456Z"
  positions: JSON array
  orders: JSON array
  account_balance: 100000.00
  peak_balance: 102500.00
  checksum: SHA256 hash
TTL: 24 hours

# Candle Cache (Sorted Set)
Key: candles:GOLD:1m
Score: timestamp (unix)
Value: JSON {open, high, low, close, volume}
TTL: 24 hours

# Compliance Metrics (Hash)
Key: compliance:daily:2025-12-03
Fields:
  daily_pnl: -350.00
  daily_loss_percent: 0.35
  peak_balance_today: 101200.00
TTL: 7 days

# Connection Health (String)
Key: health:tv-api, health:mt5-bridge, health:trading-engine
Value: "connected" | "disconnected"
TTL: 60 seconds (heartbeat)
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
make infra-up  # or: docker-compose -f infra/docker/docker-compose.yml up -d redis timescaledb

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

# Start with production overrides
docker-compose -f infra/docker/docker-compose.yml \
               -f infra/docker/docker-compose.prod.yml \
               up -d
```

### Makefile Commands

```makefile
# Makefile (root level)

.PHONY: all build up down logs test lint

# Infrastructure
infra-up:
	docker-compose -f infra/docker/docker-compose.yml up -d redis timescaledb

infra-down:
	docker-compose -f infra/docker/docker-compose.yml down

# Build all services
build:
	docker-compose -f infra/docker/docker-compose.yml build

# Start all services
up:
	docker-compose -f infra/docker/docker-compose.yml up -d

# Stop all services
down:
	docker-compose -f infra/docker/docker-compose.yml down

# View logs
logs:
	docker-compose -f infra/docker/docker-compose.yml logs -f

# Individual service commands
build-tv-api:
	cd services/tv-api && go build -o bin/server ./cmd/server

build-mt5-bridge:
	cd services/mt5-bridge && cargo build --release

build-trading-engine:
	cd services/trading-engine && poetry build

build-notification:
	cd services/notification && go build -o bin/bot ./cmd/bot

# Testing
test:
	cd services/trading-engine && poetry run pytest
	cd services/tv-api && go test ./...
	cd services/mt5-bridge && cargo test
	cd services/notification && go test ./...

# Linting
lint:
	cd services/trading-engine && poetry run ruff check .
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

_This Architecture Document v2.0 reflects the monorepo structure with independent microservices._

_Last Updated: 2025-12-03_
_Author: Winston (Architect Agent)_
