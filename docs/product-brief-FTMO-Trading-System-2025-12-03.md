# Product Brief: FTMO Trading System (Updated)

**Date:** 2025-12-03
**Author:** BMad
**Context:** Expert Technical Project
**Version:** 2.0 - Monorepo Architecture Update

---

## Executive Summary

An event-driven automated trading system engineered specifically for FTMO prop firm challenges, targeting high-frequency intraday trading on 1m/5m timeframes across GOLD, BTC, and EUR symbols. The system is architected as a **monorepo with independent microservices**, leveraging a polyglot tech stack (Go, Rust, Python) for optimal performance at each layer.

**Key Changes from v1.0:**
- Restructured to monorepo with 4 independent services
- MT5 Bridge: Rust (performance-critical ZeroMQ messaging)
- Notification Service: Go (lightweight, efficient)
- Trading Engine: Python/Nautilus Trader (unchanged)
- TV-API: Go (unchanged)
- Docker-managed infrastructure

---

## System Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SANDBOXED MONOREPO                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐ │
│  │   tv-api    │    │ mt5-bridge  │    │    trading-engine       │ │
│  │    (Go)     │    │   (Rust)    │    │  (Python/Nautilus)      │ │
│  │             │    │             │    │                         │ │
│  │ TradingView │    │ MT5 ↔ ZMQ  │    │ Strategies, Risk,       │ │
│  │ WebSocket   │    │   Bridge    │    │ FTMO Compliance         │ │
│  └──────┬──────┘    └──────┬──────┘    └───────────┬─────────────┘ │
│         │                  │                       │               │
│         │    ┌─────────────┴───────────────────────┘               │
│         │    │                                                     │
│         ▼    ▼                                                     │
│  ┌─────────────────┐    ┌─────────────────┐                       │
│  │     Redis       │    │   TimescaleDB   │                       │
│  │  (Hot Cache)    │    │  (Historical)   │                       │
│  └─────────────────┘    └─────────────────┘                       │
│                                │                                   │
│                                ▼                                   │
│                    ┌─────────────────────┐                        │
│                    │    notification     │                        │
│                    │       (Go)          │                        │
│                    │   Telegram Bot      │                        │
│                    └─────────────────────┘                        │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                      INFRASTRUCTURE (Docker)                        │
│  Redis 7.2+ │ TimescaleDB/PostgreSQL 16+ │ ZeroMQ                  │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
TradingView ──WebSocket──▶ tv-api (Go) ──▶ Redis/TimescaleDB
                                                │
                                                ▼
MT5 Terminal ◀──ZeroMQ──▶ mt5-bridge (Rust) ──▶ trading-engine (Python)
                                                │
                                                ├──▶ Execute Orders ──▶ MT5
                                                │
                                                └──▶ notification (Go) ──▶ Telegram
```

---

## Services Architecture

### 1. TV-API Service (Go)

**Purpose:** TradingView WebSocket data collector and processor

**Responsibilities:**
- Connect to TradingView WebSocket API
- Collect OHLCV candles (1m/5m timeframes)
- Store data in Redis (hot cache) and TimescaleDB (historical)
- Provide REST API for historical data queries

**Tech Stack:**
- Language: Go
- Storage: Redis, TimescaleDB
- Protocol: WebSocket (inbound), REST API (outbound)

**Status:** Existing, operational

---

### 2. MT5-Bridge Service (Rust)

**Purpose:** High-performance bridge between MetaTrader 5 and trading system

**Responsibilities:**
- Receive tick data from MT5 EA via ZeroMQ
- Forward bid/ask spreads to trading engine
- Receive trade commands from trading engine
- Execute orders on MT5 with confirmation tracking
- Monitor execution quality (slippage, latency)

**Tech Stack:**
- Language: Rust
- Messaging: ZeroMQ (REQ/REP + PUB/SUB patterns)
- Async Runtime: Tokio

**Why Rust:**
- Zero-cost abstractions for latency-critical messaging
- Memory safety without GC pauses
- Excellent ZeroMQ ecosystem (zeromq-rs, tmq)
- Bridge runs 24/7 - reliability is paramount

**Interfaces:**
```
MT5 EA ◀──ZMQ REQ/REP──▶ mt5-bridge ◀──ZMQ PUB/SUB──▶ trading-engine
         (Orders/Ticks)                 (Market Data/Commands)
```

---

### 3. Trading-Engine Service (Python)

**Purpose:** Core trading logic with Nautilus Trader framework

**Responsibilities:**
- Strategy execution (event-driven signal generation)
- FTMO rule engine (real-time compliance validation)
- Risk management (position sizing, drawdown limits)
- Backtesting with realistic execution model
- Portfolio state management

**Tech Stack:**
- Language: Python 3.11+
- Framework: Nautilus Trader 1.x
- Storage: Redis (state cache), TimescaleDB (historical)

**Directory Structure:**
```
trading-engine/
├── src/
│   ├── strategies/      # Trading strategies
│   ├── adapters/        # Data source adapters (TV, MT5)
│   └── risk/            # FTMO rules, risk management
├── tests/
├── Dockerfile
└── pyproject.toml
```

**Key Components:**
- `strategies/` - Nautilus Strategy implementations
- `adapters/` - TradingView adapter (Redis → Nautilus), MT5 adapter (ZeroMQ → Nautilus)
- `risk/` - FTMO rule engine, position sizing, drawdown monitoring

---

### 4. Notification Service (Go)

**Purpose:** Alert and notification delivery via Telegram

**Responsibilities:**
- Trade notifications (entry/exit with P&L)
- FTMO limit warnings (70-80% threshold alerts)
- System health alerts (connection drops, errors)
- Daily/weekly summary reports
- Command interface (status queries, emergency stop)

**Tech Stack:**
- Language: Go
- API: Telegram Bot API
- Storage: Redis (message queue)

**Why Go:**
- Lightweight, efficient for I/O-bound service
- Consistent with tv-api (shared knowledge)
- Fast startup, low memory footprint
- Excellent Telegram bot libraries

---

## Infrastructure

### Docker Composition

All services and dependencies managed via Docker Compose:

```yaml
services:
  # Infrastructure
  redis:          # Hot cache, pub/sub messaging
  timescaledb:    # Historical data, audit logs

  # Application Services
  tv-api:         # TradingView data collector
  mt5-bridge:     # MT5 ZeroMQ bridge
  trading-engine: # Nautilus trading core
  notification:   # Telegram bot
```

### Storage Strategy

| Data Type | Storage | Retention |
|-----------|---------|-----------|
| Real-time ticks | Redis | 24 hours |
| OHLCV candles | TimescaleDB | 3+ years |
| Trade history | TimescaleDB | Permanent |
| System state | Redis + snapshot | Continuous |
| Audit logs | TimescaleDB | 1 year |

### Network Architecture

```
┌─────────────────────────────────────┐
│         Docker Network              │
│         (trading-net)               │
├─────────────────────────────────────┤
│  Internal DNS:                      │
│  - redis:6379                       │
│  - timescaledb:5432                 │
│  - tv-api:8080                      │
│  - mt5-bridge:5555 (REQ/REP)        │
│  - mt5-bridge:5556 (PUB/SUB)        │
│  - trading-engine:8081              │
│  - notification:8082                │
└─────────────────────────────────────┘
```

---

## Monorepo Structure

```
Sandboxed/
├── .bmad/                          # BMAD framework
├── docs/                           # Documentation
│
├── services/                       # Independent microservices
│   ├── tv-api/                     # TradingView (Go)
│   │   ├── cmd/
│   │   ├── internal/
│   │   ├── pkg/
│   │   ├── Dockerfile
│   │   ├── go.mod
│   │   └── README.md
│   │
│   ├── mt5-bridge/                 # MT5 Bridge (Rust)
│   │   ├── src/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   ├── Cargo.toml
│   │   └── README.md
│   │
│   ├── trading-engine/             # Trading Core (Python)
│   │   ├── src/
│   │   │   ├── strategies/
│   │   │   ├── adapters/
│   │   │   └── risk/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   ├── pyproject.toml
│   │   └── README.md
│   │
│   └── notification/               # Telegram Bot (Go)
│       ├── cmd/
│       ├── internal/
│       ├── Dockerfile
│       ├── go.mod
│       └── README.md
│
├── infra/                          # Infrastructure configs
│   ├── docker/
│   │   ├── docker-compose.yml
│   │   ├── docker-compose.dev.yml
│   │   └── docker-compose.prod.yml
│   ├── redis/
│   │   └── redis.conf
│   ├── timescaledb/
│   │   └── init.sql
│   └── scripts/
│       ├── setup.sh
│       └── teardown.sh
│
├── configs/                        # Environment configs
│   ├── .env.example
│   ├── dev/
│   │   └── .env
│   └── prod/
│       └── .env
│
├── scripts/                        # Dev utilities
│   ├── build-all.sh
│   └── lint-all.sh
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
   - Own Dockerfile and dependencies

2. **Polyglot Optimization**
   - Go: I/O-bound services (tv-api, notification)
   - Rust: Performance-critical messaging (mt5-bridge)
   - Python: Domain logic with Nautilus (trading-engine)

3. **Infrastructure as Code**
   - All infra in `/infra` directory
   - Docker Compose for local and production
   - Environment configs separated by deployment target

4. **Extensibility**
   - Add new services: create folder in `/services`
   - Add new infra: extend docker-compose
   - Add new environments: create folder in `/configs`

---

## Technology Stack Summary

| Component | Technology | Version | Justification |
|-----------|------------|---------|---------------|
| **tv-api** | Go | 1.21+ | Existing, WebSocket handling |
| **mt5-bridge** | Rust | 1.75+ | Zero-latency ZeroMQ, reliability |
| **trading-engine** | Python | 3.11+ | Nautilus Trader requirement |
| **notification** | Go | 1.21+ | Lightweight, Telegram bot |
| **Trading Framework** | Nautilus Trader | 1.x | Event-driven, backtest/live unified |
| **Message Queue** | ZeroMQ | 4.3+ | Low-latency inter-process comm |
| **Cache** | Redis | 7.2+ | Hot data, pub/sub |
| **Database** | TimescaleDB | PG16+ | Time-series optimized |
| **Container** | Docker | 24+ | Deployment consistency |

---

## MVP Scope (Unchanged from v1.0)

### Core Features

1. **Data Integration Layer** - TradingView + MT5 adapters
2. **FTMO Rule Engine** - Real-time compliance validation
3. **Strategy Framework** - Nautilus-based, 3 symbols (GOLD/BTC/EUR)
4. **Realistic Backtesting** - Spread, slippage, latency simulation
5. **State Management** - Redis + PostgreSQL persistence
6. **Monitoring & Alerts** - Telegram notifications
7. **Execution Integration** - MT5 via ZeroMQ bridge

### Success Criteria (Unchanged)

- Real-time data flowing without gaps
- FTMO rules enforced with zero false negatives
- Backtesting on 2+ years data
- Walk-forward analysis consistency
- 30-day paper trading validation
- Paper trading within 20% of backtest metrics

---

## Risks and Mitigations

### New Risks (Architecture Update)

**Risk: Polyglot Complexity**
- **Impact:** Multiple languages increase cognitive load
- **Mitigation:** Clear service boundaries, no shared code
- **Benefit:** Each service uses optimal language for its task

**Risk: Inter-service Communication**
- **Impact:** ZeroMQ/Redis messaging failures
- **Mitigation:** Health checks, auto-reconnect, message persistence
- **Monitoring:** Connection status in notification service

**Risk: Rust Learning Curve (mt5-bridge)**
- **Impact:** Development time for bridge service
- **Mitigation:** Bridge logic is straightforward (message forwarding)
- **Validation:** Prototype ZeroMQ echo server in Week 1

### Existing Risks (From v1.0)

- FTMO Rule Violations → Conservative thresholds (70-80%)
- Backtest-Live Divergence → Realistic execution model + paper trading
- System Reliability → State persistence + crash recovery
- Strategy Performance → Focus on infrastructure first

---

## Development Phases (Updated)

### Phase 1: Foundation (Weeks 1-4)
- Week 1-2: Monorepo structure, Docker setup, Nautilus learning
- Week 2-3: mt5-bridge (Rust) basic implementation
- Week 3-4: TradingView adapter integration
- Week 4: End-to-end data flow validation

### Phase 2: Core Systems (Weeks 5-6)
- Week 5: FTMO rule engine in trading-engine
- Week 6: notification service + Telegram integration

### Phase 3: Validation (Weeks 7-8)
- Week 7: Realistic execution model
- Week 8: Walk-forward analysis, validation reports

### Phase 4: Paper Trading (Weeks 9-12+)
- 30+ days paper trading
- Daily monitoring and iteration

### Phase 5: Live FTMO (Week 13+)
- Conservative position sizes
- Manual monitoring initially

---

## Appendix: Service Communication Matrix

| From → To | Protocol | Port | Data |
|-----------|----------|------|------|
| MT5 EA → mt5-bridge | ZeroMQ REQ/REP | 5555 | Ticks, Orders |
| mt5-bridge → trading-engine | ZeroMQ PUB/SUB | 5556 | Market Data |
| trading-engine → mt5-bridge | ZeroMQ REQ/REP | 5555 | Trade Commands |
| tv-api → Redis | Redis Protocol | 6379 | OHLCV Candles |
| tv-api → TimescaleDB | PostgreSQL | 5432 | Historical Data |
| trading-engine → Redis | Redis Protocol | 6379 | State Cache |
| trading-engine → notification | Redis PUB/SUB | 6379 | Alerts |
| notification → Telegram | HTTPS | 443 | Messages |

---

_This Product Brief v2.0 reflects the updated monorepo architecture with independent microservices._

_Next: Create directory structure and implement services._
