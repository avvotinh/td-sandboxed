# Multi-Account Trading System - Epic Breakdown

**Author:** BMad
**Date:** 2025-12-17
**Project Level:** High Complexity
**Target Scale:** Multi-Account Trading (2-5 accounts)

---

## Overview

This document provides the complete epic and story breakdown for the Multi-Account Trading System, decomposing the requirements from the [PRD](./prd.md) into implementable stories with full technical context from [Architecture](./architecture.md).

**Context Documents:**
- ✅ PRD: Product Requirements Document (54 FRs, 33 NFRs)
- ✅ Architecture: Technical design and service specifications
- ○ UX Design: Not applicable (CLI tool)

---

## Functional Requirements Inventory

| FR ID | Category | Description | Priority |
|-------|----------|-------------|----------|
| **FR1** | Account Management | Trader can add a new trading account by providing MT5 credentials and account configuration | MVP |
| **FR2** | Account Management | Trader can remove an existing trading account from the system | MVP |
| **FR3** | Account Management | Trader can start an individual account to begin trading operations | MVP |
| **FR4** | Account Management | Trader can stop an individual account to pause trading operations | MVP |
| **FR5** | Account Management | Trader can view the status of all configured accounts (active, paused, stopped, error) | MVP |
| **FR6** | Account Management | Trader can configure each account with a specific trading strategy and parameters | MVP |
| **FR7** | Account Management | Trader can assign a prop firm preset or custom rule set to each account | MVP |
| **FR8** | Account Management | System can manage up to 5 simultaneous trading accounts | MVP |
| **FR9** | Rule Engine | System can load and apply built-in prop firm rule presets (FTMO, The5ers, WeMasterTrade) | MVP |
| **FR10** | Rule Engine | Trader can create custom rules by copying a preset and modifying it | Growth |
| **FR11** | Rule Engine | System can validate rule configurations before applying them | MVP |
| **FR12** | Rule Engine | System can evaluate rules in real-time (every bar) for each account independently | MVP |
| **FR13** | Rule Engine | System can block trade execution when a rule would be violated | MVP |
| **FR14** | Rule Engine | System can track daily P&L for each account against daily loss limits | MVP |
| **FR15** | Rule Engine | System can track total drawdown for each account against max drawdown limits | MVP |
| **FR16** | Rule Engine | System can enforce trading hours restrictions per account | Growth |
| **FR17** | Rule Engine | System can enforce position size limits per account | MVP |
| **FR18** | Rule Engine | System can log every rule check with timestamp, values, and decision | MVP |
| **FR19** | Signal Routing | System can receive trading signals from strategies | MVP |
| **FR20** | Signal Routing | System can route signals to appropriate accounts based on symbol filter | MVP |
| **FR21** | Signal Routing | System can filter signals based on account-specific criteria (spread, session) | Growth |
| **FR22** | Signal Routing | Trader can configure which symbols each account is allowed to trade | MVP |
| **FR23** | Trade Execution | System can send order commands to MT5 via ZeroMQ bridge | MVP |
| **FR24** | Trade Execution | System can receive order execution confirmations from MT5 | MVP |
| **FR25** | Trade Execution | System can track order status (pending, filled, rejected, cancelled) | MVP |
| **FR26** | Trade Execution | System can record trade execution details (entry price, slippage, fill time) | MVP |
| **FR27** | Trade Execution | System can maintain independent MT5 connections per account | MVP |
| **FR28** | Risk Isolation | System can isolate risk state between accounts (one account's breach doesn't affect others) | MVP |
| **FR29** | Risk Isolation | System can continue operating unaffected accounts when one account is paused or stopped | MVP |
| **FR30** | Risk Isolation | System can track per-account equity, balance, and drawdown independently | MVP |
| **FR31** | State Management | System can persist account state to Redis every 5 seconds | MVP |
| **FR32** | State Management | System can recover account state from Redis snapshot after crash | MVP |
| **FR33** | State Management | System can reconcile positions with MT5 after recovery | MVP |
| **FR34** | State Management | System can detect and log discrepancies between snapshot and MT5 positions | MVP |
| **FR35** | State Management | System can resume trading operations after successful recovery | MVP |
| **FR36** | Notifications | Trader can receive Telegram notifications for trade executions | MVP |
| **FR37** | Notifications | Trader can receive Telegram warnings when approaching rule limits | Growth |
| **FR38** | Notifications | Trader can receive Telegram alerts when rules are violated | MVP |
| **FR39** | Notifications | Trader can view account status overview via Telegram bot | Growth |
| **FR40** | Notifications | Trader can trigger emergency stop for all accounts via Telegram command | MVP |
| **FR41** | Notifications | Trader can pause/resume individual accounts via Telegram commands | Growth |
| **FR42** | Audit & Compliance | System can maintain complete audit trail of all rule checks in TimescaleDB | MVP |
| **FR43** | Audit & Compliance | System can record all trade executions with full context per account | MVP |
| **FR44** | Audit & Compliance | System can track rule violations with violation details and context | MVP |
| **FR45** | Audit & Compliance | System can store daily account snapshots for compliance verification | MVP |
| **FR46** | Configuration | Trader can configure accounts via YAML configuration file | MVP |
| **FR47** | Configuration | Trader can configure custom rules via YAML rule files | Growth |
| **FR48** | Configuration | System can validate configuration files before engine start | MVP |
| **FR49** | Configuration | Trader can view resolved configuration via CLI command | MVP |
| **FR50** | System Operations | Trader can start the trading engine via CLI command | MVP |
| **FR51** | System Operations | Trader can stop the trading engine gracefully via CLI command | MVP |
| **FR52** | System Operations | Trader can view engine status and health via CLI command | MVP |
| **FR53** | System Operations | Trader can view logs filtered by account via CLI command | MVP |
| **FR54** | System Operations | System can perform graceful shutdown preserving all state | MVP |

**Total: 54 Functional Requirements**
- MVP: 43 FRs
- Growth: 11 FRs

---

## Epic Structure Overview

| Epic | Title | User Value | FRs Covered |
|------|-------|------------|-------------|
| **1** | Foundation & Infrastructure | System ready for trading services | Enables all |
| **2** | Single Account Trading Core | Run ONE account with MT5 execution | FR1,3-6,19,22-27 |
| **3** | Multi-Account Management | Run 2-5 accounts with isolation | FR2,7-8,20,28-30 |
| **4** | FTMO Compliance Rule Engine | Trade with automatic rule protection | FR9,11-15,17-18 |
| **5** | State Persistence & Crash Recovery | Positions survive crashes | FR31-35,54 |
| **6** | Notifications & Emergency Control | Alerts and emergency stop via Telegram | FR36,38,40 |
| **7** | Audit & Compliance Logging | Complete audit trail for compliance | FR42-45 |

**Dependency Flow:**
```
Epic 1 → Epic 2 → Epic 3 → Epic 4 → Epic 5
                              ↓        ↓
                           Epic 6   Epic 7
```

---

## Technical Context Summary

### Services by Epic

| Service | Language | Epic Coverage |
|---------|----------|---------------|
| **trading-engine** | Python 3.11+ / Nautilus | Epic 2-5, 7 |
| **mt5-bridge** | Rust 1.75+ | Epic 2 |
| **notification** | Go 1.21+ | Epic 6 |
| **tv-api** | Go 1.21+ | Supporting (existing) |

### Infrastructure

| Component | Epic 1 Setup |
|-----------|--------------|
| Redis 7.2+ | Hot cache, pub/sub, state snapshots |
| TimescaleDB (PG16+) | Historical data, audit logs |
| ZeroMQ 4.3+ | MT5 ↔ bridge ↔ engine messaging |
| Docker Compose | Service orchestration |

### Key Architecture Patterns

- **Polyglot Services**: Right language for each service (Go I/O, Rust latency, Python trading logic)
- **ZeroMQ Messaging**: REQ/REP for commands, PUB/SUB for market data
- **Redis Pub/Sub**: Inter-service events (bars, alerts)
- **Per-Account Isolation**: Independent state, connections, rules
- **MT5 Source of Truth**: Position reconciliation always trusts MT5

---

## FR Coverage Map

| FR ID | Description | Epic | Story | Status |
|-------|-------------|------|-------|--------|
| FR1 | Add new trading account | 2 | 2.1 | ✅ MVP |
| FR2 | Remove existing account | 3 | 3.2 | ✅ MVP |
| FR3 | Start individual account | 2 | 2.2 | ✅ MVP |
| FR4 | Stop individual account | 2 | 2.2 | ✅ MVP |
| FR5 | View account status | 2 | 2.2 | ✅ MVP |
| FR6 | Configure strategy per account | 2 | 2.1, 2.8 | ✅ MVP |
| FR7 | Assign prop firm preset | 3 | 3.7 | ✅ MVP |
| FR8 | Manage up to 5 accounts | 3 | 3.1, 3.2 | ✅ MVP |
| FR9 | Load prop firm presets | 4 | 4.5 | ✅ MVP |
| FR10 | Create custom rules | - | - | 🔜 Growth |
| FR11 | Validate rule configurations | 4 | 4.6 | ✅ MVP |
| FR12 | Real-time rule evaluation | 4 | 4.1 | ✅ MVP |
| FR13 | Block violating trades | 4 | 4.6 | ✅ MVP |
| FR14 | Track daily P&L | 4 | 4.2, 4.7 | ✅ MVP |
| FR15 | Track max drawdown | 4 | 4.3 | ✅ MVP |
| FR16 | Trading hours restrictions | - | - | 🔜 Growth |
| FR17 | Position size limits | 4 | 4.4 | ✅ MVP |
| FR18 | Log rule checks | 4 | 4.8 | ✅ MVP |
| FR19 | Receive trading signals | 2 | 2.6, 2.7 | ✅ MVP |
| FR20 | Route signals by symbol | 2, 3 | 2.9, 3.3 | ✅ MVP |
| FR21 | Filter by spread/session | - | - | 🔜 Growth |
| FR22 | Configure allowed symbols | 2 | 2.1, 2.9 | ✅ MVP |
| FR23 | Send orders via ZeroMQ | 2 | 2.3, 2.4 | ✅ MVP |
| FR24 | Receive execution confirmations | 2 | 2.3, 2.4 | ✅ MVP |
| FR25 | Track order status | 2 | 2.5 | ✅ MVP |
| FR26 | Record execution details | 2 | 2.5 | ✅ MVP |
| FR27 | Independent MT5 connections | 2, 3 | 2.3, 3.4 | ✅ MVP |
| FR28 | Risk isolation between accounts | 3 | 3.5 | ✅ MVP |
| FR29 | Continue unaffected accounts | 3 | 3.5 | ✅ MVP |
| FR30 | Per-account metrics | 3 | 3.5, 3.6 | ✅ MVP |
| FR31 | Persist state to Redis | 5 | 5.1, 5.7 | ✅ MVP |
| FR32 | Recover from Redis snapshot | 5 | 5.2, 5.4 | ✅ MVP |
| FR33 | Reconcile positions with MT5 | 5 | 5.3 | ✅ MVP |
| FR34 | Detect/log discrepancies | 5 | 5.3 | ✅ MVP |
| FR35 | Resume trading after recovery | 5 | 5.5 | ✅ MVP |
| FR36 | Trade execution notifications | 6 | 6.1, 6.2, 6.3 | ✅ MVP |
| FR37 | Warning notifications | - | - | 🔜 Growth |
| FR38 | Rule violation alerts | 6 | 6.4 | ✅ MVP |
| FR39 | Status via Telegram | - | - | 🔜 Growth |
| FR40 | Emergency stop via Telegram | 6 | 6.5, 6.6 | ✅ MVP |
| FR41 | Pause/resume via Telegram | - | - | 🔜 Growth |
| FR42 | Audit trail in TimescaleDB | 7 | 7.2 | ✅ MVP |
| FR43 | Record trade executions | 7 | 7.1 | ✅ MVP |
| FR44 | Track rule violations | 7 | 7.3 | ✅ MVP |
| FR45 | Daily account snapshots | 7 | 7.4, 7.6 | ✅ MVP |
| FR46 | YAML account configuration | 2, 3 | 2.1, 3.1 | ✅ MVP |
| FR47 | Custom YAML rules | - | - | 🔜 Growth |
| FR48 | Validate config on start | 4 | 4.6 | ✅ MVP |
| FR49 | View resolved config | 2 | 2.10 | ✅ MVP |
| FR50 | Start engine via CLI | 2 | 2.10 | ✅ MVP |
| FR51 | Stop engine via CLI | 2 | 2.10 | ✅ MVP |
| FR52 | View engine status | 2 | 2.10 | ✅ MVP |
| FR53 | Filter logs by account | 7 | 7.5 | ✅ MVP |
| FR54 | Graceful shutdown | 5 | 5.6 | ✅ MVP |

**Coverage Summary:**
- **MVP FRs Covered:** 43/43 (100%)
- **Growth FRs Deferred:** 11 (FR10, FR16, FR21, FR37, FR39, FR41, FR47)

---

## Epic 1: Foundation & Infrastructure

**Goal:** Establish the complete development and deployment infrastructure for the multi-account trading system, enabling all subsequent epics.

**User Value:** System infrastructure is deployed and ready for trading services to be built upon.

**Technical Context:**
- Docker Compose orchestration (Redis 7.2+, TimescaleDB/PostgreSQL 16+)
- Monorepo structure with independent services
- Environment configuration and secrets management
- Database schema initialization

---

### Story 1.1: Project Structure and Monorepo Setup

As a **developer**,
I want **the monorepo structure established with service directories**,
So that **I can develop independent services with clear boundaries**.

**Acceptance Criteria:**

**Given** I clone the repository
**When** I examine the directory structure
**Then** I see the following structure:
```
Sandboxed/
├── services/
│   ├── tv-api/           # Existing Go service
│   ├── mt5-bridge/       # New Rust service
│   ├── trading-engine/   # New Python service
│   └── notification/     # New Go service
├── infra/
│   ├── docker/
│   ├── redis/
│   ├── timescaledb/
│   └── scripts/
├── configs/
│   ├── .env.example
│   ├── dev/
│   └── prod/
├── scripts/
├── Makefile
└── README.md
```

**And** each service directory contains its own:
- Dockerfile
- README.md
- Language-specific dependency files (go.mod, Cargo.toml, pyproject.toml)

**Prerequisites:** None (first story)

**Technical Notes:**
- Follow Architecture section "Monorepo Structure" exactly
- tv-api already exists - preserve existing structure
- Create placeholder directories for new services
- Include .gitignore for each language

---

### Story 1.2: Docker Compose Infrastructure Stack

As a **developer**,
I want **Redis and TimescaleDB running via Docker Compose**,
So that **I have the required data stores for development**.

**Acceptance Criteria:**

**Given** I have Docker 24+ and Docker Compose 2.x installed
**When** I run `make infra-up`
**Then** Redis 7.2+ starts on port 6379
**And** TimescaleDB (PostgreSQL 16+) starts on port 5432
**And** both services are on the `trading-net` Docker network
**And** volumes are created for persistent data (redis_data, timescale_data)

**Given** the infrastructure is running
**When** I run `redis-cli ping`
**Then** I receive "PONG"

**Given** the infrastructure is running
**When** I connect to TimescaleDB with configured credentials
**Then** I can execute SQL queries

**Prerequisites:** Story 1.1

**Technical Notes:**
- Use `infra/docker/docker-compose.yml` from Architecture
- Redis config: `infra/redis/redis.conf` with persistence enabled
- TimescaleDB uses init.sql for schema setup
- Health checks required for both services
- Environment variables from `configs/dev/.env`

---

### Story 1.3: TimescaleDB Schema Initialization

As a **developer**,
I want **the database schema initialized with all required tables**,
So that **services can store trading data and audit logs**.

**Acceptance Criteria:**

**Given** TimescaleDB is running
**When** the container starts for the first time
**Then** the init.sql script executes automatically
**And** the following tables exist:
- `prop_firms` (preset reference)
- `accounts` (trading account configurations)
- `account_snapshots` (daily compliance tracking)
- `candles` (hypertable for OHLCV data)
- `trades` (per-account trade records)
- `rule_violations` (hypertable for violations)
- `audit_logs` (hypertable for rule checks)
- `performance_metrics` (daily metrics per account)

**Given** the schema is initialized
**When** I query `SELECT * FROM prop_firms`
**Then** I see default entries: ftmo, the5ers, wmt

**Given** the candles table exists
**When** I check its configuration
**Then** it is a TimescaleDB hypertable partitioned by time

**Prerequisites:** Story 1.2

**Technical Notes:**
- Schema from Architecture "Database Schema (TimescaleDB)" section
- Enable TimescaleDB extension
- Create hypertables for time-series tables (candles, rule_violations, audit_logs)
- Include appropriate indexes per Architecture spec
- Insert default prop_firms records

---

### Story 1.4: Environment Configuration Setup

As a **developer**,
I want **environment configuration files with all required variables**,
So that **services can be configured without hardcoding secrets**.

**Acceptance Criteria:**

**Given** I examine `configs/.env.example`
**When** I read the file
**Then** I see documented environment variables for:
- Infrastructure: POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, REDIS_PASSWORD
- TV-API: SESSION_ID, SESSION_SIGN
- Trading Engine: TRADING_MODE
- Notification: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- Logging: LOG_LEVEL, LOG_FORMAT

**Given** I copy `.env.example` to `configs/dev/.env`
**When** I fill in my credentials
**Then** Docker Compose can read them via `env_file` directive

**Given** production deployment is needed
**When** I create `configs/prod/.env`
**Then** I can use different credentials for production

**Prerequisites:** Story 1.2

**Technical Notes:**
- Never commit actual .env files (add to .gitignore)
- Use `password_env` pattern for MT5 passwords (reference env var name, not value)
- Document each variable with comments
- Include sensible defaults where appropriate

---

### Story 1.5: Makefile Build Commands

As a **developer**,
I want **unified Makefile commands for common operations**,
So that **I can build, test, and run services consistently**.

**Acceptance Criteria:**

**Given** I am in the project root
**When** I run `make help`
**Then** I see available commands with descriptions

**Given** I run `make infra-up`
**Then** Redis and TimescaleDB start

**Given** I run `make infra-down`
**Then** infrastructure containers stop

**Given** I run `make build`
**Then** all service Docker images are built

**Given** I run `make up`
**Then** all services start with proper dependencies

**Given** I run `make down`
**Then** all services stop gracefully

**Given** I run `make logs`
**Then** I see aggregated logs from all services

**Given** I run `make test`
**Then** tests run for all services

**Prerequisites:** Story 1.2

**Technical Notes:**
- Follow Makefile from Architecture "Makefile Commands" section
- Include per-service build commands: `make build-tv-api`, `make build-mt5-bridge`, etc.
- Include lint command: `make lint`
- Phony targets for all commands

---

### Story 1.6: Trading Engine Service Scaffold

As a **developer**,
I want **the trading-engine Python service scaffolded with uv**,
So that **I can develop the core trading logic with Nautilus Trader**.

**Acceptance Criteria:**

**Given** I navigate to `services/trading-engine`
**When** I examine the directory
**Then** I see:
```
trading-engine/
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── engine.py
│   ├── accounts/
│   ├── strategies/
│   ├── adapters/
│   ├── rules/
│   ├── backtesting/
│   ├── state/
│   └── config/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── Dockerfile
├── pyproject.toml
├── uv.lock
└── README.md
```

**Given** I run `uv sync` in the trading-engine directory
**Then** dependencies install successfully
**And** nautilus_trader is available

**Given** I run `uv run python -m src`
**Then** the engine starts (and exits gracefully with no accounts configured)

**Prerequisites:** Story 1.1

**Technical Notes:**
- Use uv as package manager (not poetry or pip)
- pyproject.toml with Python 3.11+ requirement
- Dependencies: nautilus_trader, redis-py, pyzmq, sqlalchemy, pydantic
- Dockerfile: Multi-stage build with uv
- Include basic logging setup

---

### Story 1.7: MT5 Bridge Service Scaffold

As a **developer**,
I want **the mt5-bridge Rust service scaffolded**,
So that **I can develop the low-latency ZeroMQ bridge**.

**Acceptance Criteria:**

**Given** I navigate to `services/mt5-bridge`
**When** I examine the directory
**Then** I see:
```
mt5-bridge/
├── src/
│   ├── main.rs
│   ├── lib.rs
│   ├── zmq_server.rs
│   ├── protocol.rs
│   ├── config.rs
│   ├── handlers/
│   │   ├── mod.rs
│   │   ├── tick_handler.rs
│   │   └── order_handler.rs
│   └── models/
│       ├── mod.rs
│       ├── tick.rs
│       └── order.rs
├── tests/
├── Dockerfile
├── Cargo.toml
└── README.md
```

**Given** I run `cargo build` in the mt5-bridge directory
**Then** the project compiles successfully

**Given** I run `cargo run`
**Then** the bridge starts and listens on configured ZeroMQ ports

**Prerequisites:** Story 1.1

**Technical Notes:**
- Rust 1.75+ with 2021 edition
- Dependencies: tokio (async runtime), zeromq/tmq, serde, serde_json, tracing
- Dockerfile: Multi-stage build with cargo-chef for caching
- Default ports: 5555 (REQ/REP), 5556 (PUB), 5557 (SUB)

---

### Story 1.8: Notification Service Scaffold

As a **developer**,
I want **the notification Go service scaffolded**,
So that **I can develop the Telegram bot for alerts**.

**Acceptance Criteria:**

**Given** I navigate to `services/notification`
**When** I examine the directory
**Then** I see:
```
notification/
├── cmd/
│   └── bot/
│       └── main.go
├── internal/
│   ├── telegram/
│   │   ├── bot.go
│   │   └── commands.go
│   ├── handlers/
│   │   ├── trade_handler.go
│   │   ├── risk_handler.go
│   │   └── health_handler.go
│   ├── formatters/
│   │   ├── trade_formatter.go
│   │   └── alert_formatter.go
│   └── subscriber/
│       └── redis_subscriber.go
├── Dockerfile
├── go.mod
└── README.md
```

**Given** I run `go build ./cmd/bot` in the notification directory
**Then** the project compiles successfully

**Given** I run the bot with valid TELEGRAM_BOT_TOKEN
**Then** the bot starts and can receive commands

**Prerequisites:** Story 1.1

**Technical Notes:**
- Go 1.21+
- Dependencies: go-telegram-bot-api, go-redis, viper
- Dockerfile: Multi-stage build
- Graceful shutdown handling

---

### Story 1.9: Docker Compose Full Stack

As a **developer**,
I want **all services orchestrated via Docker Compose**,
So that **I can run the complete system locally**.

**Acceptance Criteria:**

**Given** I have built all service images
**When** I run `make up`
**Then** all services start in dependency order:
1. redis, timescaledb (infrastructure)
2. tv-api (data collection)
3. mt5-bridge (MT5 communication)
4. trading-engine (trading logic)
5. notification (alerts)

**Given** all services are running
**When** I run `docker ps`
**Then** I see all containers healthy

**Given** all services are running
**When** I run `make logs`
**Then** I see logs from all services with container names

**Given** I run `make down`
**Then** all services stop gracefully
**And** data volumes are preserved

**Prerequisites:** Stories 1.2, 1.6, 1.7, 1.8

**Technical Notes:**
- Use depends_on with health checks for startup order
- All services on trading-net network
- Restart policy: unless-stopped
- Environment variables from configs/dev/.env

---

**Epic 1 Complete: 9 Stories**

**FR Coverage:** Foundation (enables all FRs)

**Technical Context Used:**
- Architecture: Monorepo Structure, Docker Compose, Database Schema
- All service scaffolds follow Architecture specifications

---

## Epic 2: Single Account Trading Core

**Goal:** Enable a trader to configure ONE trading account and execute trades via MT5.

**User Value:** Trader can run a single account with a trading strategy and execute trades through MT5.

**PRD Coverage:** FR1, FR3-6, FR19, FR22-27

**Technical Context:**
- Account model with MT5 credentials and strategy configuration
- mt5-bridge ZeroMQ implementation (REQ/REP for commands, PUB/SUB for data)
- trading-engine ZMQ adapter for order execution
- Redis subscription for market data from tv-api
- Basic MA Crossover strategy implementation

---

### Story 2.1: Account Model and Configuration

As a **trader**,
I want **to define my trading account configuration in YAML**,
So that **I can specify MT5 credentials, strategy, and trading parameters**.

**Acceptance Criteria:**

**Given** I create an `accounts.yaml` file
**When** I define an account with the following structure:
```yaml
accounts:
  - id: "ftmo-gold-001"
    name: "FTMO Gold Challenge"
    type: "prop_firm"
    prop_firm: "ftmo"
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
    status: "active"
```
**Then** the configuration is valid and can be loaded by the trading engine

**Given** I provide an invalid configuration (missing required fields)
**When** the trading engine attempts to load it
**Then** I receive a clear error message indicating what's wrong

**Given** I reference a password environment variable
**When** the trading engine loads the configuration
**Then** it reads the actual password from the environment variable (not stored in YAML)

**Prerequisites:** Story 1.6

**Technical Notes:**
- Use Pydantic for configuration validation
- Account model in `src/accounts/account.py`
- Config loader in `src/config/loader.py`
- Required fields: id, name, type, mt5.server, mt5.login, mt5.password_env, strategy, signal_filter.symbols
- Optional fields: prop_firm, strategy_params, status (default: "active")

**FR Coverage:** FR1, FR6, FR22

---

### Story 2.2: Account Lifecycle Management (Start/Stop)

As a **trader**,
I want **to start and stop my trading account**,
So that **I can control when the account is actively trading**.

**Acceptance Criteria:**

**Given** I have a configured account in accounts.yaml
**When** I run `trading-engine accounts start ftmo-gold-001`
**Then** the account status changes to "active"
**And** the engine begins processing signals for that account

**Given** an account is active
**When** I run `trading-engine accounts stop ftmo-gold-001`
**Then** the account status changes to "stopped"
**And** the engine stops processing signals for that account
**And** existing positions are NOT closed (remain open on MT5)

**Given** I run `trading-engine accounts status`
**Then** I see a list of all accounts with their current status (active, paused, stopped)

**Given** I run `trading-engine accounts status ftmo-gold-001`
**Then** I see detailed status for that specific account

**Prerequisites:** Story 2.1

**Technical Notes:**
- Account states: active, paused, stopped, error
- Account lifecycle managed in `src/accounts/account_manager.py`
- CLI commands via Click or Typer in `src/__main__.py`
- Status stored in Redis: `account:{account_id}:status`

**FR Coverage:** FR3, FR4, FR5

---

### Story 2.3: MT5 Bridge ZeroMQ Server

As a **developer**,
I want **the mt5-bridge to accept ZeroMQ connections**,
So that **MT5 EAs can send tick data and receive order commands**.

**Acceptance Criteria:**

**Given** the mt5-bridge service is running
**When** an MT5 EA connects to port 5555 (REQ/REP)
**Then** the bridge accepts the connection and responds to heartbeat messages

**Given** a connected MT5 EA sends a tick message:
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
**When** the bridge receives the message
**Then** it publishes the tick on port 5556 (PUB) with topic "tick:XAUUSD"
**And** responds with ACK to the EA

**Given** the trading-engine sends an order command to port 5557 (SUB)
**When** the bridge receives the order
**Then** it forwards to the appropriate MT5 EA via REQ/REP
**And** waits for execution result

**Prerequisites:** Story 1.7

**Technical Notes:**
- ZeroMQ patterns per Architecture: REQ/REP (5555), PUB (5556), SUB (5557)
- Message format: JSON with type field for routing
- Include account_id in all messages for multi-account support
- Implement connection timeout and retry logic
- Log all messages at DEBUG level

**FR Coverage:** FR23, FR24, FR27

---

### Story 2.4: Trading Engine ZeroMQ Adapter

As a **developer**,
I want **the trading-engine to communicate with mt5-bridge via ZeroMQ**,
So that **I can receive tick data and send order commands**.

**Acceptance Criteria:**

**Given** the trading-engine starts
**When** it initializes the ZMQ adapter
**Then** it connects to mt5-bridge on configured ports (SUB: 5556, REQ: 5557)

**Given** the adapter is connected
**When** a tick is published on the mt5-bridge PUB socket
**Then** the adapter receives it and routes to the appropriate account

**Given** a strategy generates a trade signal
**When** the engine calls `zmq_adapter.send_order(order)`
**Then** the order is sent to mt5-bridge via REQ socket
**And** the adapter waits for and returns the execution result

**Given** the connection to mt5-bridge is lost
**When** the adapter detects the disconnection
**Then** it attempts reconnection with exponential backoff
**And** logs the disconnection and reconnection attempts

**Prerequisites:** Story 2.3

**Technical Notes:**
- Adapter in `src/adapters/zmq_adapter.py`
- Use pyzmq with asyncio integration
- Subscribe to "tick:*" for all symbols
- Order request timeout: 5 seconds
- Reconnection backoff: 1s, 2s, 4s, 8s, max 30s

**FR Coverage:** FR23, FR24

---

### Story 2.5: Order Execution Flow

As a **trader**,
I want **my strategy signals to execute as orders on MT5**,
So that **I can automatically enter and exit positions**.

**Acceptance Criteria:**

**Given** a strategy generates a BUY signal for XAUUSD
**When** the signal passes to the execution flow
**Then** an order command is created:
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
**And** the order is sent to mt5-bridge

**Given** MT5 executes the order
**When** the execution result returns:
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
**Then** the trade is recorded in the trading-engine
**And** the position is tracked for the account

**Given** an order is rejected by MT5
**When** the rejection result returns with status "rejected"
**Then** the rejection reason is logged
**And** no position is recorded

**Prerequisites:** Story 2.4

**Technical Notes:**
- Order model in `src/adapters/zmq_adapter.py`
- Track order states: pending, filled, rejected, cancelled
- Record slippage for analysis
- Use UUID for order_id generation
- Implement idempotency check to prevent duplicate orders

**FR Coverage:** FR25, FR26

---

### Story 2.6: Redis Market Data Subscription

As a **developer**,
I want **the trading-engine to receive OHLCV bars from Redis**,
So that **strategies can react to new candle data**.

**Acceptance Criteria:**

**Given** the trading-engine starts
**When** it initializes the Redis adapter
**Then** it subscribes to bar channels based on account symbol filters

**Given** an account is configured to trade XAUUSD
**When** tv-api publishes a new bar to `bars:XAUUSD:1m`
**Then** the Redis adapter receives the bar data
**And** routes it to the account's strategy

**Given** the bar data format is:
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
**When** the strategy receives the bar
**Then** it can access all OHLCV fields for signal generation

**Given** Redis connection is lost
**When** the adapter detects disconnection
**Then** it attempts reconnection with backoff
**And** re-subscribes to all channels on reconnect

**Prerequisites:** Story 1.6

**Technical Notes:**
- Adapter in `src/adapters/redis_adapter.py`
- Use redis-py with asyncio pub/sub
- Channel pattern: `bars:{symbol}:{timeframe}`
- Parse JSON bar data into Bar model
- Maintain subscription list for reconnection

**FR Coverage:** FR19

---

### Story 2.7: Basic Strategy Framework

As a **developer**,
I want **a base strategy class that integrates with Nautilus Trader**,
So that **I can implement trading strategies consistently**.

**Acceptance Criteria:**

**Given** I create a new strategy class
**When** I inherit from `BaseStrategy`
**Then** I have access to:
- `on_bar(bar)` - Called when new bar arrives
- `on_tick(tick)` - Called when new tick arrives
- `generate_signal()` - Returns BUY, SELL, or None
- `get_position_size(signal)` - Returns lot size for the signal
- `account` - Reference to the account this strategy runs on

**Given** a strategy is attached to an account
**When** the account receives market data
**Then** the data is routed to the strategy's appropriate handler

**Given** a strategy generates a signal
**When** `generate_signal()` returns BUY or SELL
**Then** the engine creates an order and sends it for execution

**Prerequisites:** Story 2.6

**Technical Notes:**
- Base class in `src/strategies/base_strategy.py`
- Integration with Nautilus Trader's Strategy class
- Strategies are stateless between bars (state in account)
- Signal enum: BUY, SELL, CLOSE, NONE
- Position sizer in `src/strategies/position_sizer.py`

**FR Coverage:** FR19

---

### Story 2.8: MA Crossover Strategy Implementation

As a **trader**,
I want **a Moving Average Crossover strategy**,
So that **I can trade based on trend-following signals**.

**Acceptance Criteria:**

**Given** I configure an account with strategy "ma_crossover":
```yaml
strategy: "ma_crossover"
strategy_params:
  fast_period: 20
  slow_period: 50
```
**When** the strategy runs
**Then** it calculates 20-period and 50-period Simple Moving Averages

**Given** the fast MA crosses above the slow MA
**When** `on_bar()` is called
**Then** `generate_signal()` returns BUY

**Given** the fast MA crosses below the slow MA
**When** `on_bar()` is called
**Then** `generate_signal()` returns SELL

**Given** no crossover occurs
**When** `on_bar()` is called
**Then** `generate_signal()` returns NONE

**Given** I have an open BUY position
**When** a SELL signal is generated
**Then** the existing position is closed before opening the new position

**Prerequisites:** Story 2.7

**Technical Notes:**
- Strategy in `src/strategies/ma_crossover.py`
- Use numpy or pandas for MA calculation
- Maintain rolling window of prices for MA calculation
- Crossover detection: fast_ma[i-1] < slow_ma[i-1] AND fast_ma[i] > slow_ma[i]
- Include configurable lookback buffer (default: slow_period + 10)

**FR Coverage:** FR6, FR19

---

### Story 2.9: Signal Filtering by Symbol

As a **trader**,
I want **signals filtered based on my account's allowed symbols**,
So that **I only trade the symbols I've configured**.

**Acceptance Criteria:**

**Given** an account is configured with:
```yaml
signal_filter:
  symbols: ["XAUUSD"]
```
**When** a bar for XAUUSD arrives
**Then** the strategy processes it

**When** a bar for BTCUSD arrives
**Then** the strategy ignores it (not in allowed symbols)

**Given** an account allows multiple symbols:
```yaml
signal_filter:
  symbols: ["XAUUSD", "EURUSD", "GBPUSD"]
```
**When** bars for any of these symbols arrive
**Then** the strategy processes them

**Given** a signal is generated for a symbol not in the filter
**When** the engine processes the signal
**Then** the signal is dropped with a debug log

**Prerequisites:** Story 2.8

**Technical Notes:**
- Symbol filter in account configuration
- Filter check in signal router before strategy invocation
- Log filtered signals at DEBUG level for troubleshooting
- Symbol matching is case-insensitive

**FR Coverage:** FR20, FR22

---

### Story 2.10: CLI Engine Commands

As a **trader**,
I want **CLI commands to control the trading engine**,
So that **I can start, stop, and monitor the system from the command line**.

**Acceptance Criteria:**

**Given** I am in the trading-engine directory
**When** I run `trading-engine start`
**Then** the engine starts and loads all active accounts

**Given** the engine is running
**When** I run `trading-engine stop`
**Then** the engine performs graceful shutdown
**And** all state is persisted

**Given** the engine is running
**When** I run `trading-engine status`
**Then** I see:
- Engine status (running/stopped)
- Number of active accounts
- Connection status (Redis, MT5 bridge)

**Given** I run `trading-engine config dump`
**When** the command executes
**Then** I see the resolved configuration (with secrets masked)

**Given** I run `trading-engine start --dry-run`
**When** the command executes
**Then** configuration is validated
**And** connections are tested
**And** no actual trading occurs

**Prerequisites:** Story 2.2

**Technical Notes:**
- Use Click or Typer for CLI framework
- Commands in `src/__main__.py`
- Subcommands: start, stop, status, accounts, config, logs
- --dry-run flag validates without executing
- --verbose flag for debug output

**FR Coverage:** FR49, FR50, FR51, FR52

---

**Epic 2 Complete: 10 Stories**

**FR Coverage:** FR1, FR3-6, FR19, FR20, FR22-27, FR49-52

**Technical Context Used:**
- Architecture: ZeroMQ messaging patterns, Redis pub/sub
- Service interfaces: mt5-bridge ↔ trading-engine
- Account configuration structure from Architecture

---

## Epic 3: Multi-Account Management

**Goal:** Enable traders to run 2-5 accounts simultaneously with complete risk isolation.

**User Value:** Trader can manage multiple prop firm and personal accounts, each operating independently.

**PRD Coverage:** FR2, FR7-8, FR20, FR28-30

**Technical Context:**
- Account Manager orchestrating multiple account lifecycles
- Signal Router distributing signals to appropriate accounts
- Per-account MT5 connections via port-based routing
- Risk isolation ensuring account failures don't cascade
- accounts.yaml supporting multiple account definitions

---

### Story 3.1: Multi-Account Configuration

As a **trader**,
I want **to configure multiple accounts in a single YAML file**,
So that **I can manage all my trading accounts in one place**.

**Acceptance Criteria:**

**Given** I create an `accounts.yaml` with multiple accounts:
```yaml
accounts:
  - id: "ftmo-gold-001"
    name: "FTMO Gold Challenge"
    type: "prop_firm"
    prop_firm: "ftmo"
    mt5:
      server: "FTMO-Server"
      login: 12345678
      password_env: "FTMO_PASS_001"
    strategy: "ma_crossover"
    signal_filter:
      symbols: ["XAUUSD"]
    status: "active"

  - id: "5ers-btc-001"
    name: "The5ers BTC Account"
    type: "prop_firm"
    prop_firm: "the5ers"
    mt5:
      server: "The5ers-Server"
      login: 87654321
      password_env: "5ERS_PASS_001"
    strategy: "breakout"
    signal_filter:
      symbols: ["BTCUSD"]
    status: "active"

  - id: "personal-001"
    name: "Personal Account"
    type: "custom"
    rules_file: "my_rules.yaml"
    mt5:
      server: "ICMarkets-MT5"
      login: 11111111
      password_env: "PERSONAL_PASS"
    strategy: "scalper"
    signal_filter:
      symbols: ["EURUSD", "GBPUSD"]
    status: "active"
```
**When** the trading engine loads the configuration
**Then** all three accounts are recognized and validated

**Given** I configure more than 5 accounts
**When** the engine loads the configuration
**Then** I receive an error: "Maximum 5 accounts supported"

**Given** two accounts have the same ID
**When** the engine loads the configuration
**Then** I receive an error: "Duplicate account ID: {id}"

**Prerequisites:** Story 2.1

**Technical Notes:**
- Validate unique account IDs
- Maximum 5 accounts enforced at load time
- Each account gets independent MT5 connection
- Different prop_firm values can use different presets

**FR Coverage:** FR8

---

### Story 3.2: Account Manager Multi-Account Orchestration

As a **developer**,
I want **the Account Manager to handle multiple account lifecycles**,
So that **each account operates independently**.

**Acceptance Criteria:**

**Given** the engine starts with 3 configured accounts
**When** all accounts have status "active"
**Then** all 3 accounts are initialized and start processing signals

**Given** Account A is stopped
**When** I run `trading-engine accounts stop ftmo-gold-001`
**Then** Account A stops processing
**And** Accounts B and C continue operating normally

**Given** Account B encounters an error (e.g., MT5 disconnection)
**When** the error is detected
**Then** Account B is set to "error" status
**And** Accounts A and C continue operating normally
**And** an alert is generated for Account B

**Given** I add a new account to accounts.yaml
**When** I run `trading-engine accounts add personal-002`
**Then** the new account is loaded and starts if status is "active"
**And** existing accounts are not affected

**Prerequisites:** Story 2.2, Story 3.1

**Technical Notes:**
- Account Manager in `src/accounts/account_manager.py`
- Each account runs in its own asyncio task
- Account errors are isolated (try/except per account)
- Add/remove accounts without full restart (hot reload)
- Track account health in Redis: `account:{id}:health`

**FR Coverage:** FR2, FR8

---

### Story 3.3: Signal Router Multi-Account Distribution

As a **developer**,
I want **signals routed to appropriate accounts based on symbol filters**,
So that **each account only receives relevant market data**.

**Acceptance Criteria:**

**Given** Account A filters for ["XAUUSD"] and Account B filters for ["BTCUSD"]
**When** a bar for XAUUSD arrives
**Then** only Account A receives the bar

**When** a bar for BTCUSD arrives
**Then** only Account B receives the bar

**Given** Account A and Account C both filter for ["EURUSD"]
**When** a bar for EURUSD arrives
**Then** both Account A and Account C receive the bar

**Given** a bar arrives for a symbol no account is trading
**When** the router processes the bar
**Then** no accounts receive it
**And** a DEBUG log is written

**Prerequisites:** Story 2.9, Story 3.2

**Technical Notes:**
- Signal Router in `src/accounts/signal_router.py`
- Build symbol→accounts mapping on startup and account changes
- Route by symbol first, then apply additional filters
- O(1) routing lookup via hash map

**FR Coverage:** FR20

---

### Story 3.4: Per-Account MT5 Connections

As a **developer**,
I want **each account to have its own MT5 connection**,
So that **multi-broker/multi-prop-firm trading is possible**.

**Acceptance Criteria:**

**Given** Account A uses FTMO-Server and Account B uses The5ers-Server
**When** both accounts are active
**Then** each account maintains a separate ZeroMQ connection to its MT5 instance

**Given** the mt5-bridge supports multiple MT5 instances
**When** Account A sends an order
**Then** the order is routed to the correct MT5 instance based on account_id

**Given** Account A's MT5 connection is lost
**When** the disconnection is detected
**Then** only Account A is affected
**And** Account B continues trading normally

**Given** Account A reconnects to MT5
**When** the connection is re-established
**Then** Account A resumes trading
**And** no duplicate orders are sent

**Prerequisites:** Story 2.3, Story 3.2

**Technical Notes:**
- mt5-bridge supports multiple port bindings or multiplexing
- Option 1: Separate MT5 instances on different ports (5555, 5565, 5575)
- Option 2: Single bridge with account_id routing
- Account ID included in all ZeroMQ messages for routing
- Connection health tracked per account

**FR Coverage:** FR27

---

### Story 3.5: Per-Account Risk Isolation

As a **trader**,
I want **each account's risk state completely isolated**,
So that **one account's problems don't affect my other accounts**.

**Acceptance Criteria:**

**Given** Account A hits a daily loss limit (rule violation)
**When** Account A is paused due to the violation
**Then** Account B and C continue trading normally
**And** only Account A's trading is blocked

**Given** Account B has a losing trade that triggers 80% daily loss warning
**When** the warning is generated
**Then** only Account B's warning threshold is evaluated
**And** Account A and C's thresholds are unaffected

**Given** Account C's equity drops 5%
**When** drawdown is calculated
**Then** only Account C's drawdown tracking is updated
**And** Account A and B's drawdown calculations are independent

**Given** the system tracks these metrics per account:
- Daily P&L
- Daily P&L percentage
- Current equity
- Peak equity (high water mark)
- Total drawdown
**When** I view account status
**Then** each account shows its own isolated metrics

**Prerequisites:** Story 3.2

**Technical Notes:**
- Per-account state in Redis: `compliance:{account_id}:daily:{date}`
- Never aggregate metrics across accounts
- Daily P&L resets at midnight UTC per account
- Peak equity tracked independently per account
- Drawdown calculated from each account's own peak

**FR Coverage:** FR28, FR29, FR30

---

### Story 3.6: Per-Account Equity and Balance Tracking

As a **trader**,
I want **to see each account's equity, balance, and drawdown independently**,
So that **I know the financial state of each account**.

**Acceptance Criteria:**

**Given** Account A has initial balance $100,000 and current equity $98,500
**When** I run `trading-engine accounts status ftmo-gold-001`
**Then** I see:
```
Account: ftmo-gold-001 (FTMO Gold Challenge)
Status: active
Balance: $100,000.00
Equity: $98,500.00
Daily P&L: -$1,500.00 (-1.5%)
Max Drawdown: 1.5%
Peak Equity: $100,000.00
```

**Given** Account B has different financials
**When** I view Account B's status
**Then** I see Account B's metrics (not Account A's)

**Given** I run `trading-engine accounts list`
**When** the command executes
**Then** I see a summary table:
```
ID              Name                  Status  Balance     Daily P&L
ftmo-gold-001   FTMO Gold Challenge   active  $100,000    -1.5%
5ers-btc-001    The5ers BTC           active  $50,000     +0.8%
personal-001    Personal Account      paused  $25,000     0.0%
```

**Prerequisites:** Story 3.5

**Technical Notes:**
- Balance: Last known account balance from MT5
- Equity: Balance + unrealized P&L
- Daily P&L: Calculated from trades since midnight UTC
- Max Drawdown: (Peak - Current) / Peak
- Update equity on every tick/position change

**FR Coverage:** FR30

---

### Story 3.7: Account Rule Assignment

As a **trader**,
I want **to assign different rule sets to each account**,
So that **prop firm accounts use presets and personal accounts use custom rules**.

**Acceptance Criteria:**

**Given** Account A is configured as:
```yaml
type: "prop_firm"
prop_firm: "ftmo"
```
**When** the engine loads the account
**Then** the FTMO preset rules are automatically applied

**Given** Account B is configured as:
```yaml
type: "prop_firm"
prop_firm: "the5ers"
```
**When** the engine loads the account
**Then** The5ers preset rules are automatically applied

**Given** Account C is configured as:
```yaml
type: "custom"
rules_file: "my_rules.yaml"
```
**When** the engine loads the account
**Then** the custom rules from my_rules.yaml are applied

**Given** Account D has no rules specified (type: "demo")
**When** the engine loads the account
**Then** no compliance rules are enforced
**And** trading proceeds without rule checks

**Prerequisites:** Story 3.1

**Technical Notes:**
- Rule assignment logic in Account model
- Preset lookup by prop_firm value
- Custom rules loaded from rules_file path
- Demo accounts skip rule engine entirely
- Rule assignment happens at account initialization

**FR Coverage:** FR7

---

**Epic 3 Complete: 7 Stories**

**FR Coverage:** FR2, FR7-8, FR20, FR27-30

**Technical Context Used:**
- Architecture: Multi-Account Management, Signal Router, Per-Account Isolation
- Account Manager orchestration pattern
- Redis per-account state keys

---

## Epic 4: FTMO Compliance Rule Engine

**Goal:** Implement a pluggable rule engine with FTMO preset to protect traders from rule violations.

**User Value:** Trader's FTMO challenge accounts are protected from compliance violations that would fail the challenge.

**PRD Coverage:** FR9, FR11-15, FR17-18

**Technical Context:**
- Rule Engine framework with pluggable architecture
- FTMO preset (5% daily loss, 10% max drawdown, 10% profit target, min 4 days)
- Pre-trade validation blocking trades that would violate rules
- Real-time P&L tracking per account
- Audit logging for every rule check

---

### Story 4.1: Rule Engine Framework

As a **developer**,
I want **a pluggable rule engine framework**,
So that **I can implement different rule types and presets**.

**Acceptance Criteria:**

**Given** I create a new rule type
**When** I inherit from `BaseRule`
**Then** I implement:
- `validate(account, signal) -> RuleResult` - Check if action is allowed
- `get_current_value(account) -> float` - Get current metric value
- `get_threshold() -> float` - Get configured threshold
- `get_warning_thresholds() -> List[float]` - Get warning percentages

**Given** a rule engine is initialized for an account
**When** a signal is generated
**Then** all applicable rules are evaluated before execution

**Given** any rule returns `BLOCK`
**When** the engine processes the result
**Then** the trade is not executed
**And** the blocking reason is logged

**Given** a rule returns `WARN`
**When** the engine processes the result
**Then** a warning notification is generated
**And** the trade proceeds (unless another rule blocks)

**Prerequisites:** Story 3.7

**Technical Notes:**
- Rule Engine in `src/rules/engine.py`
- Base Rule in `src/rules/base_rule.py`
- RuleResult enum: ALLOW, WARN, BLOCK
- Rules evaluated in priority order (critical rules first)
- Short-circuit on BLOCK (no need to evaluate remaining rules)

**FR Coverage:** FR12

---

### Story 4.2: Daily Loss Limit Rule

As a **trader**,
I want **trades blocked when they would exceed my daily loss limit**,
So that **I don't fail my FTMO challenge due to exceeding the 5% daily loss**.

**Acceptance Criteria:**

**Given** an FTMO account with 5% daily loss limit and $100,000 balance
**When** daily P&L is -$4,500 (-4.5%) and a new trade signal arrives
**Then** the rule calculates potential loss impact
**And** if the trade could push losses beyond 5%, it is BLOCKED

**Given** daily P&L is -$3,500 (-3.5%)
**When** a signal for 0.1 lots arrives (estimated max loss $500)
**Then** the trade is ALLOWED (3.5% + 0.5% = 4% < 5%)

**Given** daily P&L reaches -$3,500 (70% of $5,000 limit)
**When** the rule evaluates
**Then** a WARNING notification is generated at 70% threshold

**Given** it's a new trading day (midnight UTC)
**When** the first bar arrives
**Then** daily P&L resets to $0

**Prerequisites:** Story 4.1

**Technical Notes:**
- Rule in `src/rules/types/drawdown.py`
- Daily P&L tracked in Redis: `compliance:{account_id}:daily:{date}`
- Reset at 00:00 UTC
- Warning thresholds: 70%, 80%, 90% of limit
- Estimate potential loss based on position size and recent volatility

**FR Coverage:** FR14

---

### Story 4.3: Max Drawdown Rule

As a **trader**,
I want **trades blocked when total drawdown would exceed my maximum limit**,
So that **I don't fail my FTMO challenge due to exceeding the 10% max drawdown**.

**Acceptance Criteria:**

**Given** an FTMO account with 10% max drawdown and $100,000 initial balance
**When** equity drops to $91,000 (9% drawdown)
**Then** trading is still ALLOWED

**Given** equity drops to $90,000 (10% drawdown)
**When** any new trade signal arrives
**Then** trading is BLOCKED
**And** reason: "Max drawdown limit reached (10%)"

**Given** equity is at $93,000 (7% drawdown) with 50% warning threshold
**When** the rule evaluates
**Then** a WARNING is generated: "Drawdown at 70% of limit"

**Given** initial balance is $100,000 and peak equity reached $105,000
**When** drawdown is calculated
**Then** it uses initial balance as reference (not peak) per FTMO rules

**Prerequisites:** Story 4.1

**Technical Notes:**
- Max drawdown calculated from initial balance (not trailing)
- Formula: (initial_balance - current_equity) / initial_balance
- Store initial_balance in account configuration
- Different prop firms may use different calculation methods (configurable)
- Warning thresholds: 50%, 70%, 85%

**FR Coverage:** FR15

---

### Story 4.4: Position Size Limit Rule

As a **trader**,
I want **position sizes limited per my account rules**,
So that **I don't take on excessive risk per trade**.

**Acceptance Criteria:**

**Given** an account with max position size of 1.0 lots
**When** a signal requests 1.5 lots
**Then** the trade is BLOCKED
**And** reason: "Position size 1.5 exceeds limit 1.0 lots"

**Given** a signal requests 0.5 lots
**When** the rule evaluates
**Then** the trade is ALLOWED

**Given** an account with scaling rule "1 lot per $10k balance"
**When** balance is $50,000 and signal requests 6.0 lots
**Then** the trade is BLOCKED (max 5.0 lots for this balance)

**Given** I have an existing 0.5 lot position
**When** a signal requests 0.8 lots (total would be 1.3 lots)
**Then** the trade is BLOCKED based on total exposure

**Prerequisites:** Story 4.1

**Technical Notes:**
- Rule in `src/rules/types/position.py`
- Support fixed max_lots and scaling based on balance
- Track total open position size per account
- Consider both new orders and existing positions

**FR Coverage:** FR17

---

### Story 4.5: FTMO Preset Configuration

As a **developer**,
I want **the FTMO rule preset defined in YAML**,
So that **FTMO rules are standardized and version-controlled**.

**Acceptance Criteria:**

**Given** the FTMO preset file exists at `src/rules/presets/ftmo.yaml`
**When** I examine the file
**Then** I see:
```yaml
name: "FTMO Challenge"
version: "2024.1"
description: "FTMO prop firm challenge rules"

rules:
  - type: daily_loss_limit
    threshold_percent: 5.0
    reset_time: "00:00"
    timezone: "UTC"
    action: "block_trading"
    warning_at: [70, 80, 90]

  - type: max_drawdown
    threshold_percent: 10.0
    reference: "initial_balance"
    action: "block_trading"
    warning_at: [50, 70, 85]

  - type: max_position_size
    max_lots: 100.0
    scaling: "per_10k_balance"

  - type: profit_target
    target_percent: 10.0
    action: "notify"

  - type: min_trading_days
    min_days: 4
    action: "notify"
```

**Given** an account with `prop_firm: "ftmo"`
**When** the rule engine initializes
**Then** all rules from ftmo.yaml are loaded and active

**Given** FTMO updates their rules
**When** I update ftmo.yaml
**Then** the version number increments
**And** accounts using FTMO preset use the new rules on restart

**Prerequisites:** Story 4.1

**Technical Notes:**
- Presets in `src/rules/presets/` directory
- YAML schema validated on load
- Version tracking for audit purposes
- profit_target and min_trading_days are notification-only (not blocking)

**FR Coverage:** FR9

---

### Story 4.6: Rule Validation Before Trade

As a **trader**,
I want **every trade validated against my rules before execution**,
So that **I never accidentally violate my compliance rules**.

**Acceptance Criteria:**

**Given** a strategy generates a BUY signal
**When** the execution flow processes the signal
**Then** all account rules are evaluated BEFORE sending to MT5

**Given** all rules return ALLOW
**When** the validation completes
**Then** the order is sent to MT5 for execution

**Given** any rule returns BLOCK
**When** the validation completes
**Then** the order is NOT sent to MT5
**And** the blocking rule and reason are logged
**And** a notification is sent to the trader

**Given** a rule returns WARN but no rules BLOCK
**When** the validation completes
**Then** the order is sent to MT5
**And** the warning is logged and notified

**Given** the rule engine encounters an error
**When** validation cannot be completed
**Then** the order is BLOCKED (fail-safe)
**And** an error is logged

**Prerequisites:** Story 4.2, 4.3, 4.4, 4.5

**Technical Notes:**
- Rule validation in execution flow before ZeroMQ send
- Fail-safe: When in doubt, block the trade
- Log all rule checks with full context
- Validation should complete in < 50ms (NFR2)

**FR Coverage:** FR11, FR13

---

### Story 4.7: Real-Time P&L Tracking

As a **trader**,
I want **my P&L tracked in real-time**,
So that **rule calculations use accurate current values**.

**Acceptance Criteria:**

**Given** an account has open positions
**When** new ticks arrive
**Then** unrealized P&L is recalculated
**And** equity is updated

**Given** a trade is executed
**When** the execution confirmation returns
**Then** realized P&L is updated
**And** daily P&L is updated
**And** balance is updated

**Given** a position is closed
**When** the close confirmation returns
**Then** the closed P&L is added to daily totals
**And** the position is removed from open positions

**Given** I request account status
**When** I view P&L metrics
**Then** I see:
- Current equity (balance + unrealized P&L)
- Daily P&L (realized + unrealized today)
- Total drawdown percentage

**Prerequisites:** Story 3.5

**Technical Notes:**
- P&L calculations in `src/accounts/pnl_tracker.py`
- Update on every tick for open positions
- Update on every trade execution
- Store in Redis for fast access
- Use MT5's P&L as authoritative on position close

**FR Coverage:** FR14

---

### Story 4.8: Rule Check Audit Logging

As a **trader**,
I want **every rule check logged with full context**,
So that **I can verify compliance and debug issues**.

**Acceptance Criteria:**

**Given** a rule is evaluated
**When** the evaluation completes
**Then** an audit log entry is created:
```json
{
  "timestamp": "2025-12-03T14:32:15.123Z",
  "account_id": "ftmo-gold-001",
  "rule_type": "daily_loss_limit",
  "rule_result": "ALLOW",
  "current_value": 3.5,
  "threshold_value": 5.0,
  "order_id": "ORDER-UUID-123",
  "context": {
    "signal": "BUY",
    "symbol": "XAUUSD",
    "size": 0.1
  }
}
```

**Given** a rule BLOCKS a trade
**When** the audit entry is created
**Then** the `rule_result` is "BLOCK"
**And** the blocking reason is included in context

**Given** I query audit logs for an account
**When** I run `trading-engine logs --account ftmo-gold-001 --type rule_check`
**Then** I see all rule check entries for that account

**Prerequisites:** Story 4.6

**Technical Notes:**
- Audit Logger in `src/rules/audit_logger.py`
- Write to Redis for real-time (TTL: 24 hours)
- Batch write to TimescaleDB for persistence
- Include all context needed for compliance verification
- Log both successful and blocked trades

**FR Coverage:** FR18

---

**Epic 4 Complete: 8 Stories**

**FR Coverage:** FR9, FR11-15, FR17-18

**Technical Context Used:**
- Architecture: Pluggable Rule Engine, FTMO Preset
- Rule types from Architecture rule table
- Audit logging per Architecture data schema

---

## Epic 5: State Persistence & Crash Recovery

**Goal:** Ensure trader positions and account state survive system crashes with zero data loss.

**User Value:** Trader's positions and compliance state are preserved through any system failure, enabling safe recovery.

**PRD Coverage:** FR31-35, FR54

**Technical Context:**
- Redis snapshots every 5 seconds per account
- Crash recovery sequence: load snapshot → connect MT5 → reconcile positions
- MT5 as source of truth for position reconciliation
- Graceful shutdown with state persistence

---

### Story 5.1: Redis State Snapshots

As a **trader**,
I want **my account state saved to Redis every 5 seconds**,
So that **I never lose more than 5 seconds of state on crash**.

**Acceptance Criteria:**

**Given** an account is active and trading
**When** 5 seconds elapse
**Then** a snapshot is saved to Redis with key `snapshot:{account_id}:latest`

**Given** a snapshot is created
**When** I examine the snapshot data
**Then** I see:
```json
{
  "timestamp": "2025-12-03T14:32:15.123456Z",
  "positions": [
    {"symbol": "XAUUSD", "side": "BUY", "volume": 0.1, "entry_price": 1850.25}
  ],
  "pending_orders": [],
  "account_balance": 100000.00,
  "equity": 99850.00,
  "peak_balance": 102500.00,
  "daily_starting_balance": 100500.00,
  "daily_pnl": -650.00,
  "checksum": "sha256:abc123..."
}
```

**Given** a snapshot is saved
**When** I check Redis TTL
**Then** the snapshot has TTL of 1 hour

**Given** multiple accounts are active
**When** snapshots are saved
**Then** each account has its own independent snapshot

**Prerequisites:** Story 3.5

**Technical Notes:**
- State manager in `src/state/redis_snapshots.py`
- Use Redis HSET for atomic field updates
- Include checksum for integrity verification
- Snapshot interval configurable (default: 5 seconds)
- Use asyncio timer for periodic snapshots

**FR Coverage:** FR31

---

### Story 5.2: Crash Detection and Recovery Initiation

As a **developer**,
I want **the engine to detect previous crashes and initiate recovery**,
So that **trading resumes safely after unexpected shutdowns**.

**Acceptance Criteria:**

**Given** the trading engine starts
**When** it checks for crash indicators
**Then** it looks for:
- Existing snapshots without clean shutdown flag
- Stale heartbeat keys in Redis
- Process lock files

**Given** crash indicators are found
**When** recovery mode is initiated
**Then** the log shows: "Recovery mode: Previous session did not shut down cleanly"
**And** normal startup is paused until recovery completes

**Given** no crash indicators are found
**When** the engine starts
**Then** normal startup proceeds
**And** fresh state is initialized

**Given** recovery mode is active
**When** the engine completes recovery
**Then** the crash indicators are cleared
**And** normal operation resumes

**Prerequisites:** Story 5.1

**Technical Notes:**
- Crash recovery in `src/state/crash_recovery.py`
- Set clean shutdown flag on graceful stop
- Clear flag at startup (absence = crash)
- Use Redis lock for single-instance enforcement
- Log all recovery steps for debugging

**FR Coverage:** FR32

---

### Story 5.3: Position Reconciliation with MT5

As a **trader**,
I want **my positions reconciled with MT5 after recovery**,
So that **I know my actual position state matches what the system believes**.

**Acceptance Criteria:**

**Given** recovery mode is active
**When** MT5 connection is established
**Then** the engine queries MT5 for actual open positions

**Given** snapshot shows position A but MT5 does not
**When** reconciliation runs
**Then** position A is removed from local state
**And** a WARNING is logged: "Orphan position removed: {details}"

**Given** MT5 shows position B but snapshot does not
**When** reconciliation runs
**Then** position B is added to local state
**And** a WARNING is logged: "Unknown position found: {details}"

**Given** snapshot and MT5 positions match
**When** reconciliation completes
**Then** the log shows: "Reconciliation complete: X positions verified"
**And** trading can resume

**Given** critical discrepancies are found
**When** reconciliation identifies issues
**Then** trading remains paused
**And** an ALERT is sent: "Manual intervention required"

**Prerequisites:** Story 5.2

**Technical Notes:**
- MT5 is always source of truth
- Compare by symbol, side, volume (allow small float tolerance)
- Log all discrepancies with full details
- Critical: Never duplicate orders during recovery
- Resume trading only after successful reconciliation

**FR Coverage:** FR33, FR34

---

### Story 5.4: Daily P&L Recalculation

As a **trader**,
I want **my daily P&L recalculated from trade history after recovery**,
So that **compliance rules use accurate values**.

**Acceptance Criteria:**

**Given** recovery mode is active
**When** positions are reconciled
**Then** daily P&L is recalculated from:
- Trades executed since midnight UTC
- Current unrealized P&L from open positions

**Given** the snapshot shows daily_pnl = -$500
**When** recalculation from trades shows -$520
**Then** the system uses the recalculated value (-$520)
**And** a log shows: "Daily P&L adjusted from snapshot: -$500 → -$520"

**Given** it's a new day since the last snapshot
**When** daily P&L is recalculated
**Then** only trades from today are included
**And** previous day's P&L is not carried over

**Prerequisites:** Story 5.3

**Technical Notes:**
- Query trades table for today's trades
- Sum realized P&L from closed trades
- Add unrealized P&L from current positions
- Use MT5 timestamps for day boundary
- Store recalculated values in Redis

**FR Coverage:** FR32

---

### Story 5.5: Trading Resume After Recovery

As a **trader**,
I want **trading to automatically resume after successful recovery**,
So that **I don't miss trading opportunities during recovery**.

**Acceptance Criteria:**

**Given** all recovery steps complete successfully:
- Snapshot loaded
- MT5 connected
- Positions reconciled
- P&L recalculated
**When** the recovery sequence finishes
**Then** trading resumes for all previously active accounts

**Given** Account A was "active" before crash
**When** recovery completes
**Then** Account A status is set to "active"
**And** signal processing begins

**Given** Account B was "paused" before crash
**When** recovery completes
**Then** Account B remains "paused"
**And** no signal processing for Account B

**Given** recovery completes
**When** I check account status
**Then** I see: "Recovery successful. Trading resumed for X accounts"

**Prerequisites:** Story 5.4

**Technical Notes:**
- Preserve account status from snapshot
- Only resume accounts that were active
- Send notification on successful recovery
- Include recovery duration in logs

**FR Coverage:** FR35

---

### Story 5.6: Graceful Shutdown with State Persistence

As a **trader**,
I want **the engine to save all state before shutting down**,
So that **clean restarts have accurate state**.

**Acceptance Criteria:**

**Given** I run `trading-engine stop`
**When** the shutdown sequence begins
**Then** the engine:
1. Stops accepting new signals
2. Waits for in-flight orders (up to 30 seconds)
3. Saves final state snapshot for each account
4. Sets clean shutdown flag
5. Closes all connections
6. Exits with code 0

**Given** there are pending orders
**When** graceful shutdown is initiated
**Then** the engine waits for order confirmations
**And** logs: "Waiting for X pending orders..."

**Given** the wait timeout (30s) is exceeded
**When** pending orders remain
**Then** shutdown continues
**And** a WARNING is logged about unconfirmed orders

**Given** I send SIGTERM or SIGINT
**When** the signal is received
**Then** graceful shutdown is initiated (same as `trading-engine stop`)

**Prerequisites:** Story 5.1

**Technical Notes:**
- Signal handlers for SIGTERM, SIGINT
- In-flight order tracking with timeout
- Final snapshot includes all current state
- Clean shutdown flag in Redis
- Log shutdown sequence for debugging

**FR Coverage:** FR54

---

### Story 5.7: TimescaleDB Cold Storage Backup

As a **developer**,
I want **periodic state backups to TimescaleDB**,
So that **there's a fallback if Redis data is lost**.

**Acceptance Criteria:**

**Given** an account is active
**When** 1 minute elapses
**Then** a state snapshot is written to TimescaleDB `state_snapshots` table

**Given** Redis snapshot is unavailable during recovery
**When** the engine attempts recovery
**Then** it falls back to the latest TimescaleDB snapshot
**And** logs: "Redis snapshot unavailable, using TimescaleDB fallback"

**Given** TimescaleDB snapshots are older than 7 days
**When** the retention policy runs
**Then** old snapshots are automatically deleted
**And** the most recent snapshot is always preserved

**Given** both Redis and TimescaleDB snapshots exist
**When** recovery runs
**Then** Redis snapshot is preferred (more recent)

**Prerequisites:** Story 5.1

**Technical Notes:**
- Write to TimescaleDB every 60 seconds (not every 5s like Redis)
- Table: `state_snapshots` with account_id, timestamp, state_json
- Retention policy: 7 days
- Fallback only used when Redis fails completely
- Include snapshot source in recovery logs

**FR Coverage:** FR31

---

**Epic 5 Complete: 7 Stories**

**FR Coverage:** FR31-35, FR54

**Technical Context Used:**
- Architecture: State Persistence Flow, Crash Recovery Sequence
- Redis snapshot keys and TTL
- TimescaleDB state_snapshots table
- Graceful shutdown sequence

---

## Epic 6: Notifications & Emergency Control

**Goal:** Enable traders to receive alerts and control the system via Telegram.

**User Value:** Trader stays informed about trades and can emergency stop all accounts instantly.

**PRD Coverage:** FR36, FR38, FR40

**Technical Context:**
- notification service (Go) with Telegram Bot API
- Redis Pub/Sub subscription for alert events
- Emergency stop via /stop_all command
- Trade execution and rule violation notifications

---

### Story 6.1: Notification Service Setup

As a **developer**,
I want **the notification service to connect to Telegram**,
So that **I can send messages to the trader**.

**Acceptance Criteria:**

**Given** the notification service starts
**When** it initializes with valid TELEGRAM_BOT_TOKEN
**Then** it connects to Telegram Bot API
**And** logs: "Telegram bot connected"

**Given** the bot is connected
**When** a user sends `/start` to the bot
**Then** the bot responds with a welcome message
**And** the user's chat_id is logged

**Given** TELEGRAM_CHAT_ID is configured
**When** the service starts
**Then** it can send messages to the configured chat

**Given** invalid credentials are provided
**When** the service attempts to connect
**Then** it logs an error and retries with backoff

**Prerequisites:** Story 1.8

**Technical Notes:**
- Use go-telegram-bot-api library
- Read TELEGRAM_BOT_TOKEN from environment
- Support single chat_id initially (multi-user is Growth)
- Implement reconnection with exponential backoff
- Health check: Telegram API ping

**FR Coverage:** FR36

---

### Story 6.2: Redis Alert Subscription

As a **developer**,
I want **the notification service to subscribe to alert channels**,
So that **it receives events to notify about**.

**Acceptance Criteria:**

**Given** the notification service starts
**When** it connects to Redis
**Then** it subscribes to these channels:
- `alerts:trade:*` (trade executions per account)
- `alerts:risk:*` (rule warnings/violations per account)
- `alerts:system` (system-wide alerts)
- `emergency:stop` (emergency stop commands)

**Given** a message is published to `alerts:trade:ftmo-gold-001`
**When** the subscriber receives it
**Then** the message is parsed and routed to trade handler

**Given** Redis connection is lost
**When** the subscriber detects disconnection
**Then** it reconnects and re-subscribes to all channels

**Prerequisites:** Story 6.1

**Technical Notes:**
- Redis subscriber in `internal/subscriber/redis_subscriber.go`
- Pattern subscription for per-account channels
- Message format: JSON with type and payload
- Route to appropriate handler based on channel

**FR Coverage:** FR36

---

### Story 6.3: Trade Execution Notifications

As a **trader**,
I want **to receive Telegram notifications when trades execute**,
So that **I know what my accounts are doing**.

**Acceptance Criteria:**

**Given** a trade is executed on an account
**When** the trading engine publishes to `alerts:trade:{account_id}`
**Then** the notification service formats and sends:
```
🔵 TRADE EXECUTED
Account: FTMO Gold Challenge
Symbol: XAUUSD
Action: BUY 0.10 lots
Entry: $1,850.25
SL: $1,845.00 | TP: $1,860.00
Reason: MA crossover (20/50 SMA)
Daily P&L: -$350.00 (-0.35%)
Time: 14:32:15 UTC
```

**Given** a trade is closed
**When** the close event is published
**Then** the notification includes P&L result:
```
🟢 TRADE CLOSED - PROFIT
Account: FTMO Gold Challenge
Symbol: XAUUSD
Action: SELL 0.10 lots (close)
Entry: $1,850.25 → Exit: $1,858.50
P&L: +$82.50
Daily P&L: -$267.50 (-0.27%)
```

**Given** notification sending fails
**When** Telegram API is unavailable
**Then** the message is queued for retry
**And** trading is NOT affected (fire-and-forget)

**Prerequisites:** Story 6.2

**Technical Notes:**
- Trade handler in `internal/handlers/trade_handler.go`
- Formatter in `internal/formatters/trade_formatter.go`
- Include account name for multi-account clarity
- Emoji: 🔵 open, 🟢 profit close, 🔴 loss close
- Never block trading on notification failure

**FR Coverage:** FR36

---

### Story 6.4: Rule Violation Alerts

As a **trader**,
I want **to receive alerts when rules are violated**,
So that **I know when and why trades were blocked**.

**Acceptance Criteria:**

**Given** a trade is blocked by a rule
**When** the trading engine publishes to `alerts:risk:{account_id}`
**Then** the notification service sends:
```
🔴 TRADE BLOCKED
Account: FTMO Gold Challenge
Rule: Daily Loss Limit
Current: 4.8% of 5.0% limit
Trade: BUY 0.10 XAUUSD
Reason: Trade would exceed daily loss limit
Action: Trade rejected
Time: 14:32:15 UTC
```

**Given** a warning threshold is reached
**When** the warning event is published
**Then** the notification shows:
```
🟡 RISK WARNING
Account: FTMO Gold Challenge
Rule: Daily Loss Limit
Status: 80% of limit reached
Current: 4.0% of 5.0% limit
Remaining: $1,000 (1.0%)
Action: Trading continues, monitor closely
```

**Given** max drawdown limit is reached
**When** the violation event is published
**Then** the notification shows:
```
🔴 TRADING HALTED
Account: FTMO Gold Challenge
Rule: Max Drawdown
Status: 10% limit reached
Action: All trading paused for this account
Required: Manual review before resuming
```

**Prerequisites:** Story 6.3

**Technical Notes:**
- Risk handler in `internal/handlers/risk_handler.go`
- Emoji: 🟡 warning, 🔴 violation/block
- Include actionable information
- Different severity levels in message formatting

**FR Coverage:** FR38

---

### Story 6.5: Emergency Stop Command

As a **trader**,
I want **to emergency stop all accounts via Telegram**,
So that **I can halt trading instantly in crisis situations**.

**Acceptance Criteria:**

**Given** I am in the Telegram chat with the bot
**When** I send `/stop_all`
**Then** the bot immediately publishes to `emergency:stop` channel
**And** responds: "🛑 Emergency stop initiated..."

**Given** the trading engine receives the emergency stop
**When** it processes the command
**Then** it:
1. Stops all signal processing immediately
2. Cancels all pending orders
3. Sets all accounts to "paused" status
4. Preserves existing positions (no forced close)
**And** publishes confirmation to notification service

**Given** emergency stop completes
**When** the notification service receives confirmation
**Then** it sends:
```
🔴 EMERGENCY STOP COMPLETE
Accounts Paused: 3
Pending Orders Cancelled: 2
Open Positions: 5 (preserved)
Action: Use /resume_all to restart trading
Time: 14:32:15 UTC
```

**Given** I send `/stop_all` when accounts are already stopped
**When** the bot processes it
**Then** it responds: "⚠️ All accounts already stopped"

**Prerequisites:** Story 6.2

**Technical Notes:**
- Emergency stop must complete in < 500ms
- Publish to Redis emergency:stop channel
- Trading engine subscribes to emergency channel
- No confirmation prompt (immediate action)
- Include /resume_all command hint

**FR Coverage:** FR40

---

### Story 6.6: Resume Trading Command

As a **trader**,
I want **to resume trading after emergency stop via Telegram**,
So that **I can restart operations when the crisis is over**.

**Acceptance Criteria:**

**Given** all accounts are paused from emergency stop
**When** I send `/resume_all`
**Then** the bot asks for confirmation:
"⚠️ Resume trading for all accounts? Reply /confirm_resume"

**Given** I send `/confirm_resume`
**When** the bot processes the confirmation
**Then** it publishes resume command
**And** all previously active accounts resume trading

**Given** resume completes
**When** the notification service receives confirmation
**Then** it sends:
```
🟢 TRADING RESUMED
Accounts Restarted: 3
Status: Normal operation
Time: 14:35:00 UTC
```

**Given** I send `/resume ftmo-gold-001`
**When** the bot processes it
**Then** only the specified account resumes

**Prerequisites:** Story 6.5

**Technical Notes:**
- Require confirmation for resume (unlike immediate stop)
- Track which accounts were active before stop
- Support individual account resume
- Include time elapsed since stop in confirmation

**FR Coverage:** FR40

---

**Epic 6 Complete: 6 Stories**

**FR Coverage:** FR36, FR38, FR40

**Technical Context Used:**
- Architecture: Notification Service, Alert Message Formats
- Redis Pub/Sub alert channels
- Telegram Bot API integration
- Emergency stop flow from Architecture

---

## Epic 7: Audit & Compliance Logging

**Goal:** Provide complete audit trail for all trading activity and compliance verification.

**User Value:** Trader has full records for compliance verification with prop firms and personal analysis.

**PRD Coverage:** FR42-45

**Technical Context:**
- TimescaleDB audit_logs hypertable
- Trade execution logging with full context
- Rule violation tracking
- Daily account snapshots for compliance

---

### Story 7.1: Trade Execution Audit Logging

As a **trader**,
I want **every trade execution logged with full details**,
So that **I have complete records for compliance verification**.

**Acceptance Criteria:**

**Given** a trade is executed
**When** the execution confirmation returns
**Then** a record is inserted into TimescaleDB `trades` table:
```sql
INSERT INTO trades (
  trade_id, account_id, strategy_name, symbol, side,
  quantity, entry_price, entry_time, slippage,
  signal_reason, metadata
) VALUES (
  'uuid', 'ftmo-gold-001', 'ma_crossover', 'XAUUSD', 'BUY',
  0.1, 1850.25, '2025-12-03T14:32:15Z', 0.02,
  'MA crossover (20/50)', '{"fast_ma": 1850.10, "slow_ma": 1849.80}'
);
```

**Given** a position is closed
**When** the close confirmation returns
**Then** the trade record is updated:
```sql
UPDATE trades SET
  exit_price = 1858.50,
  exit_time = '2025-12-03T15:45:00Z',
  pnl_dollars = 82.50,
  pnl_percent = 0.0825
WHERE trade_id = 'uuid';
```

**Given** I query trades for an account
**When** I run `SELECT * FROM trades WHERE account_id = 'ftmo-gold-001'`
**Then** I see all trades with complete entry and exit details

**Prerequisites:** Story 2.5

**Technical Notes:**
- Write to TimescaleDB on execution confirmation
- Include strategy signal reason and metadata
- Update on position close with exit details
- Use trade_id for idempotent updates
- Index on account_id and entry_time for queries

**FR Coverage:** FR43

---

### Story 7.2: Comprehensive Audit Log Table

As a **developer**,
I want **all rule checks and system events logged to a single audit table**,
So that **compliance queries are efficient**.

**Acceptance Criteria:**

**Given** any auditable event occurs
**When** it is logged
**Then** an entry is created in `audit_logs` hypertable:
```sql
INSERT INTO audit_logs (
  log_id, account_id, timestamp, event_type,
  rule_name, rule_result, current_value, threshold_value,
  order_id, context
) VALUES (...);
```

**Given** event types include:
- `rule_check` - Every rule evaluation
- `trade_blocked` - Trade rejected by rule
- `warning_triggered` - Warning threshold reached
- `trade_executed` - Trade confirmation
- `position_closed` - Position exit
- `system_event` - Startup, shutdown, recovery

**When** I query audit logs
**Then** I can filter by event_type, account_id, and time range

**Given** audit logs older than 90 days
**When** retention policy runs
**Then** old logs are automatically removed (TimescaleDB policy)

**Prerequisites:** Story 1.3

**Technical Notes:**
- Use TimescaleDB hypertable for time-series efficiency
- Partition by time (automatic)
- Create continuous aggregate for daily summaries
- Retention policy: 90 days for raw, 1 year for aggregates
- Include context JSONB for flexible additional data

**FR Coverage:** FR42

---

### Story 7.3: Rule Violation Tracking

As a **trader**,
I want **rule violations tracked separately with details**,
So that **I can analyze what caused blocked trades**.

**Acceptance Criteria:**

**Given** a rule blocks a trade
**When** the violation is recorded
**Then** an entry is created in `rule_violations` table:
```sql
INSERT INTO rule_violations (
  id, account_id, timestamp, rule_type, rule_name,
  current_value, threshold_value, action_taken,
  order_id, context
) VALUES (
  'uuid', 'ftmo-gold-001', '2025-12-03T14:32:15Z',
  'daily_loss_limit', 'FTMO Daily Loss 5%',
  4.8, 5.0, 'blocked',
  'order-uuid', '{"signal": "BUY", "symbol": "XAUUSD", "size": 0.1}'
);
```

**Given** I query violations for an account
**When** I run:
```sql
SELECT * FROM rule_violations
WHERE account_id = 'ftmo-gold-001'
  AND timestamp > NOW() - INTERVAL '7 days'
ORDER BY timestamp DESC;
```
**Then** I see all violations with full context

**Given** I want violation summary
**When** I query:
```sql
SELECT rule_type, COUNT(*) as violations, MAX(current_value) as peak
FROM rule_violations
WHERE account_id = 'ftmo-gold-001'
GROUP BY rule_type;
```
**Then** I see aggregated violation statistics

**Prerequisites:** Story 4.6

**Technical Notes:**
- Use TimescaleDB hypertable
- Index on account_id and rule_type
- Include order_id for correlation with trades table
- Context includes full signal details
- Track both blocks and warnings (action_taken field)

**FR Coverage:** FR44

---

### Story 7.4: Daily Account Snapshots

As a **trader**,
I want **daily snapshots of my account status stored**,
So that **I can track compliance over time**.

**Acceptance Criteria:**

**Given** it's midnight UTC
**When** the day ends
**Then** a snapshot is created for each account:
```sql
INSERT INTO account_snapshots (
  id, account_id, snapshot_date,
  opening_balance, closing_balance,
  daily_pnl, daily_pnl_percent,
  peak_balance, drawdown_percent,
  trades_count
) VALUES (
  'uuid', 'ftmo-gold-001', '2025-12-03',
  100000.00, 99350.00,
  -650.00, -0.65,
  102500.00, 3.07,
  8
);
```

**Given** I want to see my FTMO challenge progress
**When** I query:
```sql
SELECT snapshot_date, closing_balance, daily_pnl_percent, drawdown_percent
FROM account_snapshots
WHERE account_id = 'ftmo-gold-001'
ORDER BY snapshot_date;
```
**Then** I see daily progress through my challenge

**Given** FTMO requires minimum 4 trading days
**When** I query:
```sql
SELECT COUNT(*) as trading_days
FROM account_snapshots
WHERE account_id = 'ftmo-gold-001' AND trades_count > 0;
```
**Then** I can verify my trading days requirement

**Prerequisites:** Story 3.6

**Technical Notes:**
- Create snapshot at 00:00 UTC (configurable per prop firm)
- Include all metrics needed for prop firm verification
- Unique constraint on (account_id, snapshot_date)
- Historical snapshots never modified (append-only)
- Query by date range for challenge period analysis

**FR Coverage:** FR45

---

### Story 7.5: CLI Audit Query Commands

As a **trader**,
I want **CLI commands to query my audit history**,
So that **I can review my trading activity**.

**Acceptance Criteria:**

**Given** I run `trading-engine audit trades --account ftmo-gold-001 --days 7`
**When** the command executes
**Then** I see:
```
Trades for ftmo-gold-001 (last 7 days)
=====================================
Date        Symbol   Side  Size   Entry     Exit      P&L
2025-12-03  XAUUSD   BUY   0.10   $1850.25  $1858.50  +$82.50
2025-12-03  XAUUSD   SELL  0.10   $1858.00  $1852.00  -$60.00
...
Total: 15 trades | Net P&L: +$450.00
```

**Given** I run `trading-engine audit violations --account ftmo-gold-001`
**When** the command executes
**Then** I see:
```
Rule Violations for ftmo-gold-001
=================================
Date        Rule                 Value   Limit   Action
2025-12-03  daily_loss_limit     4.8%    5.0%    BLOCKED
2025-12-02  max_position_size    1.2     1.0     BLOCKED
...
Total: 3 violations (last 30 days)
```

**Given** I run `trading-engine audit daily --account ftmo-gold-001`
**When** the command executes
**Then** I see daily snapshot summary

**Prerequisites:** Story 7.1, 7.2, 7.3, 7.4

**Technical Notes:**
- CLI commands in `src/__main__.py`
- Query TimescaleDB for audit data
- Support --format json for programmatic access
- Support --export csv for spreadsheet analysis
- Default time ranges: trades (7d), violations (30d), daily (all)

**FR Coverage:** FR53

---

### Story 7.6: Compliance Report Generation

As a **trader**,
I want **to generate compliance reports for my prop firm accounts**,
So that **I can verify my challenge progress**.

**Acceptance Criteria:**

**Given** I run `trading-engine report --account ftmo-gold-001 --format pdf`
**When** the report generates
**Then** I receive a PDF with:
- Account summary (balance, equity, drawdown)
- Daily P&L chart
- Trading days count
- Rule violation summary
- Trade history

**Given** I run `trading-engine report --account ftmo-gold-001 --format json`
**When** the report generates
**Then** I receive structured JSON data

**Given** I run `trading-engine report --account ftmo-gold-001 --compare-dashboard`
**When** the command executes
**Then** it shows metrics to compare with prop firm dashboard:
```
FTMO Dashboard Comparison
=========================
Metric           System      FTMO (manual)
Daily Loss       -1.5%       [Enter value]
Max Drawdown     3.2%        [Enter value]
Trading Days     6           [Enter value]
Profit Target    4.8%        [Enter value]
```

**Prerequisites:** Story 7.4

**Technical Notes:**
- Report generation in `src/reports/compliance_report.py`
- PDF generation via reportlab or weasyprint
- Include all FTMO-relevant metrics
- Suggest comparing with prop firm dashboard
- Export formats: PDF, JSON, CSV

**FR Coverage:** FR45

---

**Epic 7 Complete: 6 Stories**

**FR Coverage:** FR42-45, FR53

**Technical Context Used:**
- Architecture: TimescaleDB schema (trades, audit_logs, rule_violations, account_snapshots)
- Audit Trail Requirements from PRD
- Hypertable time-series optimization

---

## Summary

### Epic Overview

| Epic | Title | Stories | Key FRs | User Value |
|------|-------|---------|---------|------------|
| 1 | Foundation & Infrastructure | 9 | Enables all | System ready for development |
| 2 | Single Account Trading Core | 10 | FR1,3-6,19-27,49-52 | Run ONE account with trades |
| 3 | Multi-Account Management | 7 | FR2,7-8,20,27-30 | Run 2-5 accounts simultaneously |
| 4 | FTMO Compliance Rule Engine | 8 | FR9,11-15,17-18,48 | Protected from rule violations |
| 5 | State Persistence & Crash Recovery | 7 | FR31-35,54 | Survive crashes safely |
| 6 | Notifications & Emergency Control | 6 | FR36,38,40 | Stay informed, emergency stop |
| 7 | Audit & Compliance Logging | 6 | FR42-45,53 | Complete audit trail |

**Total: 53 Stories across 7 Epics**

---

### Implementation Order

```
Week 1-2: Epic 1 (Foundation)
     ├── Infrastructure setup
     ├── Service scaffolds
     └── Database schema

Week 3-4: Epic 2 (Single Account)
     ├── Account model
     ├── MT5 bridge
     ├── ZeroMQ communication
     └── Basic trading

Week 5-6: Epic 3 (Multi-Account)
     ├── Account Manager
     ├── Signal routing
     └── Risk isolation

Week 7-8: Epic 4 (Rule Engine)
     ├── Rule framework
     ├── FTMO preset
     └── Pre-trade validation

Week 9: Epic 5 (Crash Recovery)
     ├── Redis snapshots
     ├── Position reconciliation
     └── Graceful shutdown

Week 10: Epic 6 (Notifications)
     ├── Telegram bot
     ├── Trade alerts
     └── Emergency stop

Week 11: Epic 7 (Audit)
     ├── Trade logging
     ├── Violation tracking
     └── Compliance reports
```

---

### User Journey Alignment

| PRD Persona | Primary Epics | Key Stories |
|-------------|---------------|-------------|
| **Marcus** (Multi-Prop Trader) | 2, 3, 4 | 3.1, 3.5, 4.2, 4.3 |
| **Sarah** (Custom Rules) | 4 | 4.5 (base for Growth FR10) |
| **Alex** (Crisis Recovery) | 5 | 5.2, 5.3, 5.5 |
| **Emergency User** | 6 | 6.5, 6.6 |

---

### Technical Debt Considerations

1. **Testing Strategy**: Each story should include unit tests; integration tests added in Epic 1
2. **Documentation**: API documentation generated from code comments
3. **Monitoring**: Add Prometheus metrics in Growth phase
4. **Scaling**: Current design supports 5 accounts; Growth phase considers multi-user

---

### Growth Phase Deferred Items

| FR | Feature | Rationale |
|----|---------|-----------|
| FR10 | Custom rule creation | FTMO preset covers 80% of users |
| FR16 | Trading hours restrictions | Low priority for initial MVP |
| FR21 | Spread/session filtering | Nice-to-have optimization |
| FR37 | Warning notifications | Basic alerts in MVP |
| FR39 | Status via Telegram | CLI status sufficient for MVP |
| FR41 | Pause/resume via Telegram | Emergency stop is critical path |
| FR47 | Custom YAML rules | Depends on FR10 |

---

**Document Generated:** 2025-12-17
**Author:** John (PM Agent)
**Status:** Ready for Implementation

