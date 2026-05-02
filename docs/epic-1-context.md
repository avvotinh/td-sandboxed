# Epic 1: Foundation & Infrastructure - Technical Context

**Created:** 2025-12-17
**Status:** Ready for Development
**Epic:** 1 of 7
**Stories:** 9

---

## Overview

### Problem Statement

The Multi-Account Trading System requires a complete development and deployment infrastructure before any trading functionality can be built. Currently, only the tv-api service exists as a working component. The remaining services (mt5-bridge, trading-engine, notification) need scaffolding, and infrastructure components (database schema, Makefile, service orchestration) need to be established.

### Solution

Establish the complete monorepo infrastructure with:
- Service scaffolds for mt5-bridge (Rust), trading-engine (Python/Nautilus), notification (Go)
- Docker Compose orchestration for all services
- TimescaleDB schema for multi-account trading data
- Unified Makefile for development workflows
- Environment configuration management

### Scope

**In Scope:**
- Project structure completion (Story 1.1)
- Docker Compose infrastructure stack (Story 1.2)
- TimescaleDB schema initialization (Story 1.3)
- Environment configuration setup (Story 1.4)
- Makefile build commands (Story 1.5)
- Trading Engine Python scaffold with uv (Story 1.6)
- MT5 Bridge Rust scaffold (Story 1.7)
- Notification Go scaffold (Story 1.8)
- Full stack Docker Compose (Story 1.9)

**Out of Scope:**
- Actual trading logic implementation (Epic 2+)
- MT5 ZeroMQ protocol implementation (Epic 2)
- Rule engine implementation (Epic 4)
- Telegram bot commands (Epic 6)

---

## Context for Development

### Current Project State

```
Sandboxed/
├── services/
│   ├── tv-api/              # ✅ COMPLETE - Go service with storage
│   ├── mt5-bridge/          # ❌ EMPTY - Rust scaffold needed
│   │   ├── src/             # Directory exists, no files
│   │   └── tests/           # Directory exists, no files
│   ├── trading-engine/      # ❌ EMPTY - Python scaffold needed
│   │   ├── src/             # Directory exists, no files
│   │   └── tests/           # Directory exists, no files
│   └── notification/        # ❌ EMPTY - Go scaffold needed
│       ├── cmd/             # Directory exists, no files
│       └── internal/        # Directory exists, no files
├── infra/
│   ├── docker/
│   │   └── docker-compose.yml  # ⚠️ PARTIAL - needs update for new services
│   ├── redis/               # ❌ EMPTY - redis.conf needed
│   ├── timescaledb/         # ❌ EMPTY - init.sql needed
│   └── scripts/             # Directory exists
├── configs/
│   ├── .env.example         # ✅ EXISTS
│   ├── dev/.env             # ✅ EXISTS
│   └── prod/                # Directory exists, empty
├── scripts/                 # Directory exists
├── Makefile                 # ❌ MISSING
└── README.md                # Exists
```

### Codebase Patterns

**tv-api (Go) - Reference Implementation:**
- Standard Go project layout: `cmd/`, `internal/`, `pkg/`
- Config via YAML + environment variables
- Uses `gorilla/websocket`, `go-redis`, `pgx`
- Structured logging with levels

**Docker Compose Patterns:**
- Network: `trading-net` (bridge, subnet 172.20.0.0/16)
- Health checks for all infrastructure services
- Volume mounts for persistent data
- Service dependencies with `condition: service_healthy`

**Environment Variables:**
- Infrastructure: `POSTGRES_*`, `REDIS_*`
- Service-specific: `SESSION_ID`, `TELEGRAM_BOT_TOKEN`, etc.
- Use `_env` suffix for password references in YAML configs

### Files to Reference

| File | Purpose |
|------|---------|
| `docs/architecture.md` | Complete architecture specification |
| `docs/prd.md` | Product requirements document |
| `docs/epics.md` | Full epic and story definitions |
| `services/tv-api/` | Reference Go service implementation |
| `infra/docker/docker-compose.yml` | Current Docker Compose (needs update) |

### Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Python package manager | **uv** | Fast, modern, Docker-friendly |
| Rust async runtime | **Tokio** | Industry standard for async Rust |
| Go Telegram library | **go-telegram-bot-api** | Well-maintained, good documentation |
| Database | **TimescaleDB** | Time-series optimized PostgreSQL |
| Cache | **Redis 7.2+** | Pub/sub, hot cache, state snapshots |
| Messaging | **ZeroMQ** | Low-latency inter-process communication |

---

## Implementation Plan

### Story 1.1: Project Structure and Monorepo Setup

**Goal:** Verify and complete monorepo structure with service directories

**Tasks:**
- [ ] Verify existing directory structure matches architecture spec
- [ ] Create missing placeholder files in empty service directories
- [ ] Add `.gitignore` files for each language (Rust, Python, Go)
- [ ] Create README.md for each service with basic description
- [ ] Verify services/tv-api structure is preserved

**Acceptance Criteria:**
- [ ] Given I clone the repository, when I examine the structure, then I see all service directories with proper layout
- [ ] Given each service directory, when I examine it, then it has Dockerfile placeholder, README.md, and language-specific dependency files

**Technical Notes:**
- tv-api already complete - preserve existing structure
- Each service needs: Dockerfile, README.md, language-specific config

---

### Story 1.2: Docker Compose Infrastructure Stack

**Goal:** Redis and TimescaleDB running via Docker Compose

**Tasks:**
- [ ] Update `infra/docker/docker-compose.yml` with architecture spec
- [ ] Rename network from `hft-network` to `trading-net`
- [ ] Add proper Redis config volume mount
- [ ] Verify TimescaleDB health check configuration
- [ ] Test `make infra-up` command (requires Makefile first)

**Acceptance Criteria:**
- [ ] Given Docker is installed, when I run infrastructure up, then Redis 7.2+ starts on port 6379
- [ ] Given infrastructure is running, when I run `redis-cli ping`, then I receive "PONG"
- [ ] Given infrastructure is running, when I connect to TimescaleDB, then I can execute SQL queries

**Technical Notes:**
- Current docker-compose.yml uses `hft-network` - rename to `trading-net`
- Add volume for `redis.conf`
- Update container names to `trading-*` prefix

---

### Story 1.3: TimescaleDB Schema Initialization

**Goal:** Database schema initialized with all required tables

**Tasks:**
- [ ] Create `infra/timescaledb/init.sql` from architecture spec
- [ ] Enable TimescaleDB extension
- [ ] Create tables: prop_firms, accounts, account_snapshots, candles, trades, rule_violations, audit_logs, performance_metrics
- [ ] Create hypertables for time-series tables
- [ ] Insert default prop_firms records (ftmo, the5ers, wmt)
- [ ] Add appropriate indexes per architecture spec

**Acceptance Criteria:**
- [ ] Given TimescaleDB starts, when init.sql executes, then all tables exist
- [ ] Given schema is initialized, when I query `SELECT * FROM prop_firms`, then I see default entries
- [ ] Given candles table exists, when I check configuration, then it is a TimescaleDB hypertable

**Technical Notes:**
- Schema defined in architecture.md "Database Schema (TimescaleDB)" section
- Use `create_hypertable()` for: candles, rule_violations, audit_logs
- Include all indexes specified in architecture

---

### Story 1.4: Environment Configuration Setup

**Goal:** Environment configuration files with all required variables

**Tasks:**
- [ ] Update `configs/.env.example` with all required variables
- [ ] Add documentation comments for each variable
- [ ] Verify `configs/dev/.env` has sensible defaults
- [ ] Create `configs/prod/.env.example` template
- [ ] Update docker-compose to use `env_file` directive

**Acceptance Criteria:**
- [ ] Given I examine `.env.example`, when I read the file, then I see documented variables for all services
- [ ] Given I copy `.env.example` to `.env`, when I fill in credentials, then Docker Compose can read them

**Technical Notes:**
- Never commit actual .env files (verify .gitignore)
- Use `password_env` pattern for MT5 passwords
- Include LOG_LEVEL, LOG_FORMAT defaults

**Required Variables:**
```bash
# Infrastructure
POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, REDIS_PASSWORD

# TV-API
SESSION_ID, SESSION_SIGN

# Trading Engine
TRADING_MODE (paper|live)

# Notification
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Logging
LOG_LEVEL, LOG_FORMAT
```

---

### Story 1.5: Makefile Build Commands

**Goal:** Unified Makefile commands for common operations

**Tasks:**
- [ ] Create root `Makefile` with phony targets
- [ ] Add infrastructure commands: `infra-up`, `infra-down`
- [ ] Add build commands: `build`, `build-tv-api`, `build-mt5-bridge`, `build-trading-engine`, `build-notification`
- [ ] Add service commands: `up`, `down`, `logs`
- [ ] Add development commands: `test`, `lint`
- [ ] Add `help` target with command descriptions

**Acceptance Criteria:**
- [ ] Given I am in project root, when I run `make help`, then I see available commands
- [ ] Given I run `make infra-up`, then Redis and TimescaleDB start
- [ ] Given I run `make build`, then all service Docker images are built

**Technical Notes:**
- Follow Makefile from Architecture "Makefile Commands" section
- Use `.PHONY` for all targets
- Include per-service build targets

**Makefile Targets:**
```makefile
help          # Show available commands
infra-up      # Start infrastructure (Redis, TimescaleDB)
infra-down    # Stop infrastructure
build         # Build all service images
build-<svc>   # Build specific service
up            # Start all services
down          # Stop all services
logs          # Show aggregated logs
test          # Run all tests
lint          # Run linters
```

---

### Story 1.6: Trading Engine Service Scaffold

**Goal:** Python service scaffolded with uv and Nautilus Trader

**Tasks:**
- [ ] Create `services/trading-engine/pyproject.toml` with Python 3.11+ requirement
- [ ] Add dependencies: nautilus_trader, redis-py, pyzmq, sqlalchemy, pydantic
- [ ] Create directory structure per architecture spec
- [ ] Create `src/__init__.py`, `src/__main__.py`, `src/engine.py` placeholders
- [ ] Create subdirectories: accounts/, strategies/, adapters/, rules/, backtesting/, state/, config/
- [ ] Create `Dockerfile` with multi-stage uv build
- [ ] Create `README.md` with service description
- [ ] Initialize with `uv init` and `uv sync`

**Acceptance Criteria:**
- [ ] Given I navigate to trading-engine, when I run `uv sync`, then dependencies install
- [ ] Given dependencies are installed, when I run `uv run python -m src`, then engine starts and exits gracefully

**Technical Notes:**
- Use uv as package manager (not poetry or pip)
- Dockerfile: Multi-stage build with uv
- Include basic logging setup in `__main__.py`

**Directory Structure:**
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

---

### Story 1.7: MT5 Bridge Service Scaffold

**Goal:** Rust service scaffolded with ZeroMQ support

**Tasks:**
- [ ] Create `services/mt5-bridge/Cargo.toml` with Rust 1.75+ requirement
- [ ] Add dependencies: tokio, zeromq/tmq, serde, serde_json, tracing
- [ ] Create `src/main.rs`, `src/lib.rs` entry points
- [ ] Create `src/zmq_server.rs`, `src/protocol.rs`, `src/config.rs` placeholders
- [ ] Create `src/handlers/` with mod.rs, tick_handler.rs, order_handler.rs
- [ ] Create `src/models/` with mod.rs, tick.rs, order.rs
- [ ] Create `Dockerfile` with multi-stage cargo-chef build
- [ ] Create `README.md` with service description

**Acceptance Criteria:**
- [ ] Given I navigate to mt5-bridge, when I run `cargo build`, then project compiles
- [ ] Given I run `cargo run`, then bridge starts and listens on configured ZeroMQ ports

**Technical Notes:**
- Rust 1.75+ with 2021 edition
- Default ports: 5555 (REQ/REP), 5556 (PUB), 5557 (SUB)
- Dockerfile: Multi-stage build with cargo-chef for caching

**Directory Structure:**
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

---

### Story 1.8: Notification Service Scaffold

**Goal:** Go service scaffolded with Telegram bot support

**Tasks:**
- [ ] Create `services/notification/go.mod` with Go 1.21+ requirement
- [ ] Add dependencies: go-telegram-bot-api, go-redis, viper
- [ ] Create `cmd/bot/main.go` entry point
- [ ] Create `internal/telegram/` with bot.go, commands.go
- [ ] Create `internal/handlers/` with trade_handler.go, risk_handler.go, health_handler.go
- [ ] Create `internal/formatters/` with trade_formatter.go, alert_formatter.go
- [ ] Create `internal/subscriber/redis_subscriber.go`
- [ ] Create `Dockerfile` with multi-stage Go build
- [ ] Create `README.md` with service description

**Acceptance Criteria:**
- [ ] Given I navigate to notification, when I run `go build ./cmd/bot`, then project compiles
- [ ] Given I run bot with valid TELEGRAM_BOT_TOKEN, then bot starts and can receive commands

**Technical Notes:**
- Go 1.21+
- Follow tv-api patterns for project structure
- Dockerfile: Multi-stage build

**Directory Structure:**
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

---

### Story 1.9: Docker Compose Full Stack

**Goal:** All services orchestrated via Docker Compose

**Tasks:**
- [ ] Add mt5-bridge service to docker-compose.yml
- [ ] Add trading-engine service to docker-compose.yml
- [ ] Add notification service to docker-compose.yml
- [ ] Configure proper `depends_on` with health checks
- [ ] Add ZeroMQ port mappings for mt5-bridge
- [ ] Add engine_data volume for trading-engine
- [ ] Test full stack startup with `make up`

**Acceptance Criteria:**
- [ ] Given all images are built, when I run `make up`, then all services start in dependency order
- [ ] Given all services running, when I run `docker ps`, then I see all containers healthy
- [ ] Given I run `make down`, then all services stop gracefully

**Technical Notes:**
- Startup order: redis, timescaledb → tv-api → mt5-bridge → trading-engine → notification
- Use `depends_on` with `condition: service_healthy`
- All services on `trading-net` network
- Restart policy: `unless-stopped`

---

## Additional Context

### Dependencies Between Stories

```
Story 1.1 (Structure) ──┬──► Story 1.6 (trading-engine)
                        ├──► Story 1.7 (mt5-bridge)
                        └──► Story 1.8 (notification)
                                     │
Story 1.2 (Docker Infra) ◄───────────┤
         │                           │
         ▼                           │
Story 1.3 (TimescaleDB Schema)       │
         │                           │
         ▼                           │
Story 1.4 (Environment Config) ◄─────┤
         │                           │
         ▼                           ▼
Story 1.5 (Makefile) ────────► Story 1.9 (Full Stack)
```

### Testing Strategy

| Story | Test Type | Verification |
|-------|-----------|--------------|
| 1.1 | Manual | Directory structure inspection |
| 1.2 | Integration | `docker compose up` + health checks |
| 1.3 | Integration | SQL queries after container start |
| 1.4 | Manual | Environment variable loading |
| 1.5 | Integration | `make help`, `make infra-up` |
| 1.6 | Unit + Integration | `uv sync`, `uv run python -m src` |
| 1.7 | Unit + Integration | `cargo build`, `cargo run` |
| 1.8 | Unit + Integration | `go build`, run with mock token |
| 1.9 | Integration | Full stack up/down cycle |

### Risk Considerations

| Risk | Mitigation |
|------|------------|
| Nautilus Trader version compatibility | Pin specific version in pyproject.toml |
| ZeroMQ library differences (Rust) | Test with zeromq-rs and tmq, pick working one |
| Docker build times | Use multi-stage builds with caching |
| Port conflicts | Use configurable ports, document defaults |

### Notes

- tv-api is already complete - do not modify unless necessary
- Current docker-compose uses `hft-*` naming - update to `trading-*`
- All services should have graceful shutdown handling
- Include health check endpoints in all services (future stories)

---

**Document Generated:** 2025-12-17
**Author:** BMad (via BMAD Framework)
**Status:** Ready for Story Development
