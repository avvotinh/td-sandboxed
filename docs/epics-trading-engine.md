# Trading Engine - Epic Breakdown

**Author:** BMad
**Date:** 2025-12-03
**Service:** trading-engine (Python/Nautilus Trader)
**Scope:** Single service focus within FTMO Trading System

---

## Overview

This document provides the complete epic and story breakdown for the **trading-engine** service - the core Python/Nautilus Trader component of the FTMO Trading System.

**Service Purpose:** Strategy execution, FTMO compliance validation, risk management, backtesting, and state management.

**Tech Stack:**
- Python 3.11+
- Nautilus Trader 1.x
- Redis (state, pub/sub)
- TimescaleDB (historical data, audit)
- ZeroMQ (communication with mt5-bridge)

---

## Context Validation

**Documents Loaded:**
- ✅ PRD v2.0 - 100+ Functional Requirements across 13 capability areas
- ✅ Architecture v2.0 - Monorepo structure, 4 services, Docker infrastructure
- ○ UX Design - N/A (developer tool, no UI required)

**Scope Boundaries:**
- **IN SCOPE:** trading-engine service implementation only
- **OUT OF SCOPE:** tv-api (Go), mt5-bridge (Rust), notification (Go) - separate implementation phases

**Service Interfaces (from Architecture):**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Inbound | Redis SUB | 6379 | OHLCV candles from tv-api |
| Inbound | ZeroMQ SUB | 5556 | Tick data from mt5-bridge |
| Outbound | ZeroMQ PUB | 5557 | Order commands to mt5-bridge |
| Outbound | Redis PUB | 6379 | Alerts to notification service |
| Outbound | PostgreSQL | 5432 | Trade history, audit logs |

**Dependencies for Development:**
- Redis (can run locally via Docker)
- TimescaleDB (can run locally via Docker)
- mt5-bridge: Mock adapter for development, real integration later

---

## Functional Requirements Inventory

### trading-engine Owned FRs (67 total):

| Category | FRs | Count |
|----------|-----|-------|
| FTMO Compliance | FR8-17 | 10 |
| Strategy Execution | FR18-26 | 9 |
| Backtesting | FR27-35 | 9 |
| State Management | FR36-43 | 8 |
| Risk Management | FR44-51 | 8 |
| Data Integration | FR3-7 | 5 |
| Monitoring | FR52, 57-58 | 3 |
| Execution | FR60, 62-63 | 3 |
| Paper/Live Trading | FR66-70 | 5 |
| Configuration | FR71-74, 82-83 | 6 |
| Testing | FR85-89 | 5 |

---

## Epic Structure

### Epic Overview

| Epic | Title | User Value | FRs Covered |
|------|-------|------------|-------------|
| 1 | Foundation & Project Setup | Developer can run trading-engine locally | FR71-74, FR82 |
| 2 | Adapters & External Integration | Engine connects to Redis, TimescaleDB, ZeroMQ | FR3-7, FR60 |
| 3 | FTMO Compliance Engine | Zero rule violations through architecture | FR8-17 |
| 4 | Strategy Framework | Developer can create and run trading strategies | FR18-26 |
| 5 | Backtesting & Validation | Confidence in strategy before risking capital | FR27-35 |
| 6 | State Management & Recovery | System survives crashes without data loss | FR36-43 |
| 7 | Risk Management & Safety | Prevent financial errors and system failures | FR44-51 |
| 8 | Paper Trading & CLI | Developer can validate strategy with real data | FR66-70, FR82-83 |
| 9 | Testing & Quality | Comprehensive test coverage | FR85-89 |

### Epic Dependencies

```
Epic 1 (Foundation)
    │
    ├──► Epic 2 (Adapters)
    │        │
    │        ├──► Epic 3 (Compliance) ◄── CRITICAL PATH
    │        │        │
    │        │        └──► Epic 4 (Strategy)
    │        │                 │
    │        │                 └──► Epic 5 (Backtesting)
    │        │
    │        └──► Epic 6 (State Management)
    │                 │
    │                 └──► Epic 7 (Risk)
    │
    └──► Epic 8 (Paper Trading) ◄── Requires 4, 5, 6, 7
              │
              └──► Epic 9 (Testing) ◄── Runs throughout
```

---

## Epic 1: Foundation & Project Setup

**Goal:** Developer can set up, configure, and run the trading-engine service locally with proper project structure and dependencies.

**User Value:** A working development environment with clear project structure, enabling rapid iteration and development.

**FRs Covered:** FR71, FR72, FR73, FR74, FR82

**Technical Context:**
- Python 3.11+ with Poetry for dependency management
- Pydantic for configuration validation
- structlog for JSON logging
- Click for CLI framework

---

### Story 1.1: Initialize Project Structure

As a developer,
I want a properly structured Python project with Poetry configuration,
So that I can manage dependencies and build the service.

**Acceptance Criteria:**

**Given** I clone the repository
**When** I navigate to `services/trading-engine`
**Then** I see the following structure:
```
trading-engine/
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── config/
│   ├── adapters/
│   ├── risk/
│   ├── strategies/
│   ├── backtesting/
│   └── state/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── pyproject.toml
├── Dockerfile
├── README.md
└── .env.example
```

**And** `pyproject.toml` includes:
- nautilus_trader >= 1.200
- redis >= 5.0
- psycopg2-binary >= 2.9
- pyzmq >= 25.0
- pydantic >= 2.5
- pydantic-settings >= 2.1
- structlog >= 24.1
- click >= 8.1

**Technical Notes:**
- Follow Architecture section 3 (trading-engine structure)
- Use src layout for proper package imports
- Include dev dependencies: pytest, pytest-asyncio, ruff, mypy

**Prerequisites:** None (first story)

---

### Story 1.2: Configuration System with Validation

As a developer,
I want to load configuration from YAML files and environment variables,
So that I can configure the engine without code changes.

**Acceptance Criteria:**

**Given** I have a `config/settings.yaml` file
**When** the engine starts
**Then** it loads configuration from YAML

**And Given** environment variables are set (e.g., `REDIS_URL`)
**When** the engine starts
**Then** environment variables override YAML values

**And Given** a required configuration is missing
**When** the engine starts
**Then** it fails fast with a clear error message like:
```
ConfigurationError: Missing required field 'redis_url'
```

**And Given** a configuration value is invalid (e.g., negative risk percent)
**When** the engine starts
**Then** it fails with validation error:
```
ValidationError: risk_per_trade_percent must be between 0 and 100
```

**Technical Notes:**
- Use Pydantic Settings for validation (Architecture 3)
- Support nested configuration for different components
- Configuration schema:
```python
class EngineConfig(BaseSettings):
    redis_url: str
    timescale_url: str
    zmq_bridge_host: str = "localhost"
    zmq_pub_port: int = 5556
    zmq_sub_port: int = 5557
    trading_mode: Literal["backtest", "paper", "live"] = "paper"
    log_level: str = "INFO"
```

**Prerequisites:** Story 1.1

---

### Story 1.3: Structured Logging Setup

As a developer,
I want structured JSON logging for all events,
So that I can debug issues and analyze system behavior.

**Acceptance Criteria:**

**Given** the engine is running
**When** any event occurs (startup, trade, error)
**Then** a structured JSON log entry is written:
```json
{
  "timestamp": "2025-12-03T14:32:15.123Z",
  "level": "INFO",
  "event": "engine_started",
  "service": "trading-engine",
  "trading_mode": "paper",
  "version": "0.1.0"
}
```

**And Given** different log levels configured
**When** LOG_LEVEL=DEBUG
**Then** debug logs are visible

**When** LOG_LEVEL=INFO
**Then** only INFO and above are visible

**Technical Notes:**
- Use structlog with JSON renderer
- Include context: timestamp, level, event, service name
- Add correlation IDs for request tracing
- Configure log rotation for production

**Prerequisites:** Story 1.2

---

### Story 1.4: CLI Entry Point

As a developer,
I want CLI commands for common operations,
So that I can run backtests and start trading from command line.

**Acceptance Criteria:**

**Given** I am in the trading-engine directory
**When** I run `python -m src --help`
**Then** I see available commands:
```
Usage: src [OPTIONS] COMMAND [ARGS]...

  FTMO Trading Engine CLI

Commands:
  run       Start the trading engine
  backtest  Run a backtest
  validate  Validate configuration
  version   Show version information
```

**And When** I run `python -m src run --mode paper`
**Then** the engine starts in paper trading mode

**And When** I run `python -m src validate`
**Then** configuration is validated and reported

**Technical Notes:**
- Use Click for CLI framework
- Support --config flag for custom config path
- Support --verbose flag for debug logging
- Exit codes: 0 success, 1 config error, 2 runtime error

**Prerequisites:** Story 1.3

---

### Story 1.5: Docker Configuration

As a developer,
I want a Dockerfile for the trading-engine,
So that I can build and deploy the service in containers.

**Acceptance Criteria:**

**Given** the Dockerfile exists
**When** I run `docker build -t trading-engine .`
**Then** the image builds successfully

**And Given** the image is built
**When** I run `docker run trading-engine --help`
**Then** I see the CLI help output

**And** the image size is < 500MB (optimized)

**Technical Notes:**
- Multi-stage build (builder + runtime)
- Use python:3.11-slim as base
- Install only production dependencies in final image
- Set proper ENTRYPOINT and CMD
- Include health check

**Prerequisites:** Story 1.4

---

## Epic 2: Adapters & External Integration

**Goal:** Trading-engine can connect to external systems (Redis, TimescaleDB, ZeroMQ) through clean adapter interfaces.

**User Value:** Engine receives market data and can execute orders through standardized interfaces that can be mocked for testing.

**FRs Covered:** FR3, FR4, FR5, FR6, FR7, FR60

**Technical Context:**
- Adapter pattern for external integrations
- Async interfaces with asyncio
- Connection pooling and reconnection logic

---

### Story 2.1: Redis Data Adapter

As a trading engine,
I want to subscribe to OHLCV candles from Redis,
So that I can receive market data from tv-api service.

**Acceptance Criteria:**

**Given** Redis is running with candle data published
**When** I subscribe to channel `bars:GOLD:1m`
**Then** I receive OHLCV data as Nautilus Bar events

**And Given** a message is received
**Then** it is parsed from JSON:
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

**And Given** Redis connection is lost
**When** connection is restored
**Then** adapter automatically reconnects and resubscribes

**And Given** invalid message format received
**When** parsing fails
**Then** error is logged but adapter continues operating

**Technical Notes:**
- Use redis-py async client
- Implement RedisDataAdapter class with interface:
  - `connect()`, `disconnect()`
  - `subscribe_bars(symbol, timeframe, callback)`
- Convert to Nautilus Bar objects
- Handle reconnection with exponential backoff

**Prerequisites:** Story 1.3

---

### Story 2.2: TimescaleDB Adapter

As a trading engine,
I want to load historical data from TimescaleDB,
So that I can run backtests on 2-3 years of data.

**Acceptance Criteria:**

**Given** TimescaleDB has historical candle data
**When** I call `load_bars("GOLD", "1m", start, end)`
**Then** I receive a list of Nautilus Bar objects

**And Given** I request 2 years of 1-minute data
**When** the query executes
**Then** it completes in < 30 seconds (indexed query)

**And Given** a trade is executed
**When** I call `save_trade(trade)`
**Then** the trade is persisted to `trades` table

**And Given** a compliance check occurs
**When** I call `save_audit_log(log)`
**Then** the audit entry is persisted (append-only)

**Technical Notes:**
- Use psycopg2 or asyncpg for async
- Connection pooling (min 2, max 10)
- Use TimescaleDB schema from Architecture (section 7)
- Batch inserts for performance
- Implement:
  - `load_bars()`, `load_trades()`
  - `save_trade()`, `save_audit_log()`
  - `save_performance_metrics()`

**Prerequisites:** Story 1.3

---

### Story 2.3: ZeroMQ Execution Adapter

As a trading engine,
I want to send orders to mt5-bridge via ZeroMQ,
So that orders can be executed on the broker.

**Acceptance Criteria:**

**Given** mt5-bridge is running
**When** I call `submit_order(order)`
**Then** a ZeroMQ message is sent:
```json
{
  "type": "order",
  "action": "BUY",
  "symbol": "XAUUSD",
  "volume": 0.1,
  "order_id": "ORDER-123"
}
```

**And Given** mt5-bridge responds
**When** order is filled
**Then** I receive order result:
```json
{
  "type": "order_result",
  "order_id": "ORDER-123",
  "status": "filled",
  "fill_price": 1850.47,
  "slippage": 0.02
}
```

**And Given** I subscribe to tick data
**When** mt5-bridge publishes ticks
**Then** I receive QuoteTick events

**And Given** ZeroMQ connection fails
**When** sending order
**Then** order is queued and retried (max 3 attempts)

**Technical Notes:**
- Use pyzmq for ZeroMQ
- REQ/REP for order submission (port 5557)
- SUB for tick data (port 5556)
- Timeout: 2 seconds for order acknowledgment
- Message protocol from Architecture section 2

**Prerequisites:** Story 1.3

---

### Story 2.4: Mock Adapters for Testing

As a developer,
I want mock adapters for Redis, TimescaleDB, and ZeroMQ,
So that I can run tests without external dependencies.

**Acceptance Criteria:**

**Given** I run unit tests
**When** using MockRedisAdapter
**Then** I can simulate receiving bar data

**And Given** MockZMQAdapter is used
**When** I submit an order
**Then** I can simulate fill responses with configurable slippage

**And Given** MockTimescaleAdapter is used
**When** I load historical data
**Then** I receive pre-configured test data

**Technical Notes:**
- Implement same interfaces as real adapters
- Support configurable responses
- Support failure injection for error testing
- Use pytest fixtures for easy test setup

**Prerequisites:** Stories 2.1, 2.2, 2.3

---

### Story 2.5: Data Quality Validation

As a trading engine,
I want to validate data quality automatically,
So that I detect gaps, anomalies, and bad data before trading.

**Acceptance Criteria:**

**Given** I load historical data
**When** there are gaps > 5 minutes in 1m data
**Then** I receive a DataQualityWarning with gap details

**And Given** a price is impossible (e.g., negative, or 10x previous)
**When** validation runs
**Then** I receive an AnomalyDetected alert

**And Given** timestamps are inconsistent (future dates, duplicates)
**When** validation runs
**Then** I receive a TimestampError

**And Given** data source is unavailable
**When** I try to load data
**Then** I use cached data (for backtest) or pause trading (for live)

**Technical Notes:**
- Implement DataValidator class
- Configurable thresholds for anomaly detection
- Gap detection based on expected bar frequency
- Cross-validation between TradingView and MT5 data if both available

**Prerequisites:** Story 2.2

---

## Epic 3: FTMO Compliance Engine

**Goal:** Real-time FTMO rule validation with preventive order blocking - zero violations through architecture.

**User Value:** Never fail an FTMO challenge due to rule violations. System prevents violations before they happen.

**FRs Covered:** FR8, FR9, FR10, FR11, FR12, FR13, FR14, FR15, FR16, FR17

**Technical Context:**
- Declarative YAML rule configuration
- Multi-layer validation (strategy, account, system)
- Immutable audit trail
- This is the CRITICAL DIFFERENTIATOR of the system

---

### Story 3.1: YAML Rule Configuration Loader

As a trading engine,
I want to load FTMO rules from YAML configuration,
So that rules can be changed without code modifications.

**Acceptance Criteria:**

**Given** a file `config/ftmo_rules.yaml`:
```yaml
version: "1.0"
challenge_type: "phase1"

rules:
  daily_loss:
    enabled: true
    max_loss_percent: 5.0
    warning_threshold: 70
    blocking_threshold: 95

  total_drawdown:
    enabled: true
    max_drawdown_percent: 10.0
    warning_threshold: 70
    blocking_threshold: 95

  profit_target:
    enabled: true
    target_percent: 10.0

  minimum_trading_days:
    enabled: true
    required_days: 4
```

**When** engine starts
**Then** rules are loaded and validated

**And Given** I want to use FTUK rules
**When** I create `config/ftuk_rules.yaml`
**Then** I can switch by changing config without code changes

**Technical Notes:**
- Use Pydantic for rule schema validation
- Support rule inheritance (base + override)
- Validate rule consistency on load
- Support hot reload for development (FR83)

**Prerequisites:** Story 1.2

---

### Story 3.2: Daily Loss Validator

As a trading engine,
I want to enforce the 5% maximum daily loss rule,
So that I never violate FTMO daily loss limits.

**Acceptance Criteria:**

**Given** starting balance is $100,000
**And** daily P&L is -$3,500 (3.5% loss)
**When** compliance check runs
**Then** status is PASS with 70% of limit used

**And Given** daily P&L reaches -$3,850 (3.85% loss)
**When** compliance check runs
**Then** status is WARNING (77% of limit)
**And** alert is published to Redis

**And Given** daily P&L reaches -$4,750 (4.75% loss)
**When** I try to submit new order
**Then** order is BLOCKED (95% blocking threshold)
**And** audit log records the blocked order

**And Given** it's a new trading day (00:00 UTC)
**When** daily metrics reset
**Then** daily P&L resets to 0

**Technical Notes:**
- Calculate intraday P&L in real-time
- Include unrealized P&L in calculation
- Use configurable thresholds from YAML
- Persist daily metrics to Redis for recovery

**Prerequisites:** Story 3.1

---

### Story 3.3: Total Drawdown Validator

As a trading engine,
I want to enforce the 10% maximum drawdown rule,
So that I never violate FTMO total drawdown limits.

**Acceptance Criteria:**

**Given** starting balance is $100,000
**And** peak balance reached $105,000
**And** current balance is $96,000
**When** compliance check runs
**Then** drawdown is calculated as ($105,000 - $96,000) / $100,000 = 9%

**And Given** drawdown reaches 7% of 10% limit
**When** compliance check runs
**Then** status is WARNING
**And** alert published

**And Given** drawdown reaches 9.5% of 10% limit
**When** I try to submit new order
**Then** order is BLOCKED

**Technical Notes:**
- Track peak balance (high water mark)
- Calculate drawdown from starting balance (not peak)
- FTMO uses initial balance as denominator
- Persist peak balance to Redis

**Prerequisites:** Story 3.1

---

### Story 3.4: Profit Target & Trading Days Tracker

As a trading engine,
I want to track profit target progress and minimum trading days,
So that I know my challenge completion status.

**Acceptance Criteria:**

**Given** Phase 1 profit target is 10%
**And** current profit is 8%
**When** I query progress
**Then** I see 80% of target achieved

**And Given** I have traded on 3 unique days
**And** minimum required is 4 days
**When** I query progress
**Then** I see 3/4 trading days completed

**And Given** I reach 10% profit with only 3 trading days
**When** compliance check runs
**Then** status shows "Profit target met, need 1 more trading day"

**Technical Notes:**
- Track unique calendar days with at least 1 trade
- Persist trading days to database
- Include in daily summary reports
- Support different targets per challenge type

**Prerequisites:** Story 3.1

---

### Story 3.5: Multi-Layer Compliance Validation

As a trading engine,
I want multi-layer risk validation before every order,
So that orders are checked at strategy, account, and system levels.

**Acceptance Criteria:**

**Given** a strategy generates a BUY signal
**When** order is submitted
**Then** validation runs in order:

1. **Strategy-level**: Position size within strategy limits
2. **Account-level**: FTMO rules (daily loss, drawdown)
3. **System-level**: Connection health, aggregate exposure

**And Given** any layer fails
**Then** order is rejected with specific reason:
```python
ValidationResult(
    passed=False,
    layer="account",
    rule="daily_loss",
    reason="Would exceed 95% of daily loss limit",
    current_value=4.8,
    threshold=4.75
)
```

**Technical Notes:**
- Implement RuleEngine with pluggable validators
- Each validator returns ValidationResult
- Aggregate results for comprehensive check
- Log all validation steps to audit trail

**Prerequisites:** Stories 3.2, 3.3, 3.4

---

### Story 3.6: Immutable Audit Logger

As a trading engine,
I want an immutable audit trail of all compliance checks,
So that I can review every decision for debugging and accountability.

**Acceptance Criteria:**

**Given** a compliance check runs
**Then** an audit entry is created:
```json
{
  "timestamp": "2025-12-03T14:32:15.123Z",
  "event_type": "compliance_check",
  "rule_name": "daily_loss",
  "rule_result": "PASS",
  "current_value": 3.5,
  "threshold_value": 5.0,
  "context": {
    "daily_pnl": -3500,
    "starting_balance": 100000
  }
}
```

**And Given** an order is blocked
**Then** audit entry includes order details and block reason

**And Given** audit entries exist
**When** I try to modify or delete them
**Then** operation is rejected (append-only)

**Technical Notes:**
- Use TimescaleDB audit_logs table
- Include checksum for tamper detection
- Batch writes for performance (flush every 1 second)
- Retain for 2+ years per NFR

**Prerequisites:** Story 2.2

---

### Story 3.7: Emergency Stop Mechanism

As a trading engine,
I want an emergency stop that immediately halts all trading,
So that I can stop the system in critical situations.

**Acceptance Criteria:**

**Given** trading is active
**When** I trigger emergency stop (via CLI or Telegram command)
**Then** all pending orders are cancelled
**And** no new orders are accepted
**And** positions remain open (manual closure)
**And** alert is sent via notification service

**And Given** a critical violation is detected (>100% of limit)
**When** violation occurs
**Then** emergency stop is automatically triggered

**And Given** emergency stop is active
**When** I run `python -m src run --mode paper`
**Then** engine refuses to start until stop is cleared

**Technical Notes:**
- Store emergency stop flag in Redis
- Check flag before every order submission
- Provide CLI command: `python -m src emergency-stop`
- Provide CLI command: `python -m src clear-stop`

**Prerequisites:** Story 3.5

---

## Epic 4: Strategy Framework

**Goal:** Developer can create, configure, and run trading strategies using Nautilus Trader patterns.

**User Value:** A clean framework for implementing trading strategies with built-in FTMO compliance integration.

**FRs Covered:** FR18, FR19, FR20, FR21, FR22, FR23, FR24, FR25, FR26

**Technical Context:**
- Inherit from Nautilus Strategy class
- Event-driven signal generation
- FTMO-aware position sizing

---

### Story 4.1: FTMO Base Strategy Class

As a strategy developer,
I want a base strategy class with FTMO compliance built-in,
So that all strategies automatically respect FTMO rules.

**Acceptance Criteria:**

**Given** I create a new strategy
**When** I inherit from `FTMOBaseStrategy`
**Then** I get:
- Automatic compliance validation on order submission
- FTMO-aware position sizing
- Structured logging for trade decisions
- Access to account state and positions

**And** the base class provides:
```python
class FTMOBaseStrategy(Strategy):
    def submit_order_with_compliance(self, order: Order) -> bool:
        """Submit order only if passes all compliance checks"""

    def get_position_size(self, entry, stop_loss) -> Decimal:
        """Calculate FTMO-compliant position size"""

    def publish_alert(self, alert_type: str, data: dict) -> None:
        """Publish alert to notification service"""
```

**Technical Notes:**
- Inherit from nautilus_trader.trading.Strategy
- Inject FTMORuleEngine dependency
- Provide helper methods for common operations
- Log every trade decision with reasoning

**Prerequisites:** Epic 3

---

### Story 4.2: FTMO Position Sizer

As a strategy,
I want to calculate position sizes that respect FTMO constraints,
So that a single trade cannot violate risk limits.

**Acceptance Criteria:**

**Given** account balance is $100,000
**And** risk per trade is 1%
**And** entry price is $1850.00
**And** stop loss is $1840.00 (10 point risk)
**When** I calculate position size
**Then** size = ($100,000 × 1%) / $10 = 100 units (0.1 lots)

**And Given** calculated size exceeds max position limit
**When** sizing runs
**Then** size is capped at maximum

**And Given** daily loss is already at 4%
**When** I calculate position size
**Then** size is reduced to prevent exceeding 5% limit

**Technical Notes:**
- Implement FTMOPositionSizer class
- Consider current drawdown in sizing
- Support different pip values per symbol
- Cap at configured maximum position size

**Prerequisites:** Story 4.1

---

### Story 4.3: MA Crossover Example Strategy

As a developer,
I want an example strategy implementation,
So that I understand the framework patterns and can validate the infrastructure.

**Acceptance Criteria:**

**Given** the MACrossoverStrategy is configured
**When** fast EMA crosses above slow EMA
**Then** a BUY signal is generated

**When** fast EMA crosses below slow EMA
**Then** a SELL signal is generated

**And** the strategy:
- Subscribes to bar data on start
- Calculates EMAs on each bar
- Uses FTMOPositionSizer for sizing
- Logs signal reasoning
- Publishes trade alerts

**Configuration:**
```yaml
strategy:
  name: ma_crossover
  fast_period: 20
  slow_period: 50
  risk_per_trade_percent: 1.0
  symbols: ["GOLD", "BTC", "EUR"]
```

**Technical Notes:**
- Use Nautilus EMA indicator
- Implement on_bar() handler
- Track position state (flat, long, short)
- Include stop loss and take profit logic

**Prerequisites:** Story 4.2

---

### Story 4.4: Multi-Symbol Management

As a trading engine,
I want to manage positions for multiple symbols concurrently,
So that I can trade GOLD, BTC, and EUR simultaneously.

**Acceptance Criteria:**

**Given** strategy is configured for ["GOLD", "BTC", "EUR"]
**When** engine starts
**Then** it subscribes to data for all symbols

**And Given** GOLD generates a signal
**When** order is submitted
**Then** it does not affect BTC or EUR positions

**And Given** all three symbols have open positions
**When** aggregate exposure check runs
**Then** total exposure is calculated across all positions

**Technical Notes:**
- Track positions per symbol independently
- Calculate aggregate metrics for FTMO compliance
- Support per-symbol configuration (different timeframes, sizes)
- Log per-symbol performance

**Prerequisites:** Story 4.3

---

### Story 4.5: Trade Decision Logging

As a trading engine,
I want to log every trade decision with full context,
So that I can analyze and debug strategy behavior.

**Acceptance Criteria:**

**Given** a trade signal is generated
**When** the decision is made (enter, exit, or skip)
**Then** a detailed log entry is created:
```json
{
  "timestamp": "2025-12-03T14:32:15.123Z",
  "event": "trade_decision",
  "decision": "ENTER_LONG",
  "symbol": "GOLD",
  "strategy": "ma_crossover",
  "signal": {
    "fast_ema": 1850.25,
    "slow_ema": 1848.50,
    "crossover": "bullish"
  },
  "market": {
    "bid": 1850.20,
    "ask": 1850.30,
    "spread": 0.10
  },
  "order": {
    "side": "BUY",
    "size": 0.1,
    "entry": 1850.30,
    "stop_loss": 1845.00,
    "take_profit": 1860.00
  },
  "compliance": {
    "daily_loss_used": "35%",
    "drawdown_used": "20%"
  }
}
```

**And Given** a signal is skipped (already in position, compliance block)
**Then** the skip reason is logged

**Technical Notes:**
- Log to both structured logs and database
- Include enough context to replay decision
- Enable/disable verbose logging via config

**Prerequisites:** Story 4.4

---

## Epic 5: Backtesting & Validation

**Goal:** Run backtests with realistic execution modeling to validate strategies before risking capital.

**User Value:** Confidence that strategy will perform similarly in live trading as in backtests.

**FRs Covered:** FR27, FR28, FR29, FR30, FR31, FR32, FR33, FR34, FR35

**Technical Context:**
- Nautilus BacktestEngine integration
- Dynamic spread modeling
- Slippage simulation
- Walk-forward analysis

---

### Story 5.1: Nautilus Backtest Integration

As a developer,
I want to run backtests using Nautilus BacktestEngine,
So that I can test strategies on historical data.

**Acceptance Criteria:**

**Given** historical data is loaded (2 years of 1m GOLD data)
**When** I run `python -m src backtest --strategy ma_crossover --start 2023-01-01 --end 2024-12-31`
**Then** backtest executes and produces results

**And** results include:
- Total return
- Win rate
- Maximum drawdown
- Sharpe ratio
- Trade count

**And** the same strategy code runs in backtest and live mode (no divergence)

**Technical Notes:**
- Use BacktestEngine from nautilus_trader
- Load data from TimescaleDB
- Configure venue as simulated exchange
- Output results to console and file

**Prerequisites:** Epic 4, Story 2.2

---

### Story 5.2: Dynamic Spread Model

As a backtesting engine,
I want to model dynamic spreads based on time and volatility,
So that backtests reflect realistic trading costs.

**Acceptance Criteria:**

**Given** I backtest during London session (08:00-16:00 UTC)
**When** spread is calculated
**Then** spread is at base level (e.g., 0.3 pips for GOLD)

**And Given** I backtest during Asian session (00:00-07:00 UTC)
**When** spread is calculated
**Then** spread is 1.5-2x base level

**And Given** high volatility (ATR > 1.5x average)
**When** spread is calculated
**Then** spread is increased proportionally

**Configuration:**
```yaml
spread_model:
  GOLD:
    base_spread: 0.30
    asian_multiplier: 1.8
    london_multiplier: 1.0
    ny_multiplier: 1.2
    volatility_multiplier: 0.5  # Additional spread per ATR unit
```

**Technical Notes:**
- Implement SpreadModel class
- Use time-of-day lookup for session
- Calculate ATR for volatility adjustment
- Apply spread to fill prices

**Prerequisites:** Story 5.1

---

### Story 5.3: Slippage Simulation

As a backtesting engine,
I want to simulate realistic slippage on market orders,
So that backtests account for execution costs.

**Acceptance Criteria:**

**Given** I submit a market BUY order
**When** order is filled
**Then** fill price = ask + slippage

**And** slippage is calculated as:
- Base: 0.5x spread
- Adjustments: +0.5x spread per lot above 0.5 lots
- Random factor: ±20% variation

**And Given** low liquidity conditions (e.g., news events)
**When** order is filled
**Then** slippage is 2-3x normal

**Technical Notes:**
- Implement SlippageModel class
- Use order size in calculation
- Add configurable random seed for reproducibility
- Log actual vs expected slippage

**Prerequisites:** Story 5.2

---

### Story 5.4: Latency Simulation

As a backtesting engine,
I want to simulate order execution latency,
So that backtests reflect realistic timing.

**Acceptance Criteria:**

**Given** I submit an order
**When** order is processed
**Then** fill occurs after configurable delay (200-800ms)

**And** during the delay:
- Price may move (use next available tick)
- Order may be partially filled or rejected

**Technical Notes:**
- Implement in BacktestEngine execution model
- Configurable latency range
- Use tick data for price evolution during delay
- Track latency statistics

**Prerequisites:** Story 5.3

---

### Story 5.5: Walk-Forward Analysis

As a developer,
I want walk-forward analysis to validate strategy robustness,
So that I can detect overfitting.

**Acceptance Criteria:**

**Given** I run walk-forward analysis with:
- Total period: 2 years
- In-sample: 70%
- Out-of-sample: 30%
- Periods: 4 windows

**When** analysis completes
**Then** I see results for each window:
```
Window 1: IS Return: 15%, OOS Return: 8%
Window 2: IS Return: 12%, OOS Return: 10%
Window 3: IS Return: 18%, OOS Return: 6%
Window 4: IS Return: 14%, OOS Return: 11%

Average OOS Return: 8.75%
OOS/IS Ratio: 0.58 (acceptable if > 0.5)
```

**And** if OOS performance is < 50% of IS performance
**Then** a RED FLAG warning is generated

**Technical Notes:**
- Implement WalkForwardAnalyzer class
- Configurable window count and split ratio
- Generate summary report with statistics
- Detect and flag potential overfitting

**Prerequisites:** Story 5.4

---

### Story 5.6: Validation Report Generator

As a developer,
I want comprehensive backtest reports,
So that I can evaluate strategy quality.

**Acceptance Criteria:**

**Given** a backtest completes
**When** I request a report
**Then** I receive:

```
═══════════════════════════════════════════════
BACKTEST REPORT: MA Crossover Strategy
Period: 2023-01-01 to 2024-12-31
═══════════════════════════════════════════════

PERFORMANCE METRICS
───────────────────
Total Return:      23.5%
Annualized Return: 11.2%
Sharpe Ratio:      1.45
Sortino Ratio:     2.10
Max Drawdown:      8.3%
Win Rate:          58%
Profit Factor:     1.65

TRADE STATISTICS
───────────────────
Total Trades:      156
Average Trade:     $150.32
Largest Win:       $1,250.00
Largest Loss:      -$450.00
Average Duration:  4.2 hours

FTMO COMPLIANCE
───────────────────
Max Daily Loss:    3.8% (of 5% limit)
Max Drawdown:      8.3% (of 10% limit)
Daily Violations:  0
Total Violations:  0

RED FLAGS
───────────────────
⚠️ None detected

═══════════════════════════════════════════════
```

**And** report is saved to file (JSON + text)

**Technical Notes:**
- Calculate all metrics from trade history
- Include FTMO-specific metrics
- Detect red flags (low trade count, high drawdown, etc.)
- Export to JSON for programmatic access

**Prerequisites:** Story 5.5

---

## Epic 6: State Management & Recovery

**Goal:** System maintains state reliably and recovers gracefully from crashes.

**User Value:** Never lose track of positions or orders, even after unexpected shutdowns.

**FRs Covered:** FR36, FR37, FR38, FR39, FR40, FR41, FR42, FR43

**Technical Context:**
- Redis for real-time state snapshots
- TimescaleDB for persistent trade history
- Crash recovery with state validation

---

### Story 6.1: Real-Time State Cache

As a trading engine,
I want to maintain real-time state in Nautilus Cache,
So that I have fast access to positions, orders, and account balance.

**Acceptance Criteria:**

**Given** the engine is running
**When** I query current state
**Then** I get:
- Open positions (symbol, side, size, entry price, P&L)
- Pending orders (if any)
- Account balance and equity
- Peak balance (high water mark)

**And** state updates are reflected immediately after events

**Technical Notes:**
- Use Nautilus Portfolio and Cache objects
- Subscribe to position and order events
- Calculate equity in real-time (balance + unrealized P&L)
- Track peak balance for drawdown calculation

**Prerequisites:** Epic 2

---

### Story 6.2: Redis State Snapshots

As a trading engine,
I want to save state snapshots to Redis periodically,
So that I can recover from crashes.

**Acceptance Criteria:**

**Given** the engine is running
**When** 5 minutes pass
**Then** a snapshot is saved to Redis:
```json
{
  "timestamp": "2025-12-03T14:32:15.123456Z",
  "positions": [...],
  "orders": [...],
  "account_balance": 100000.00,
  "peak_balance": 102500.00,
  "daily_pnl": -350.00,
  "checksum": "sha256:abc123..."
}
```

**And Given** a trade is executed
**When** fill is confirmed
**Then** an additional snapshot is saved

**And** snapshots have 24-hour TTL in Redis

**Technical Notes:**
- Use Redis HSET for atomic snapshot writes
- Include checksum for corruption detection
- Save on: periodic interval, trade events, shutdown
- Key: `snapshot:latest` and `snapshot:{timestamp}`

**Prerequisites:** Story 6.1

---

### Story 6.3: Crash Recovery Manager

As a trading engine,
I want to recover state after an unexpected crash,
So that I don't lose track of positions or create duplicate orders.

**Acceptance Criteria:**

**Given** the engine crashed while positions were open
**When** the engine restarts
**Then** it:
1. Detects unclean shutdown (no clean exit flag)
2. Loads latest snapshot from Redis
3. Validates snapshot checksum
4. Restores state to Nautilus Cache
5. Logs recovery summary

**And Given** snapshot is corrupted (checksum mismatch)
**When** recovery runs
**Then** alert is sent and manual intervention required

**And Given** recovery completes
**When** positions are restored
**Then** no duplicate orders are created

**Technical Notes:**
- Set `clean_shutdown` flag on normal exit
- Check flag on startup
- Implement RecoveryManager class
- Log detailed recovery steps

**Prerequisites:** Story 6.2

---

### Story 6.4: Broker State Reconciliation

As a trading engine,
I want to reconcile internal state with broker state,
So that I detect and alert on discrepancies.

**Acceptance Criteria:**

**Given** engine has position: GOLD LONG 0.1 lots @ $1850
**When** broker reports: GOLD LONG 0.1 lots @ $1850
**Then** reconciliation PASSES

**And Given** engine has position but broker doesn't (or vice versa)
**When** reconciliation runs
**Then** ALERT is generated:
```
STATE DISCREPANCY DETECTED
─────────────────────────
Engine: GOLD LONG 0.1 lots
Broker: No position
Action Required: Manual review
Trading: PAUSED
```

**And** reconciliation runs every 15 minutes during trading

**Technical Notes:**
- Query broker positions via ZeroMQ
- Compare with internal state
- Generate discrepancy report
- Pause trading on mismatch until resolved

**Prerequisites:** Story 6.3, Story 2.3

---

### Story 6.5: Trade Persistence

As a trading engine,
I want all trades persisted to TimescaleDB,
So that I have complete history for analysis and tax reporting.

**Acceptance Criteria:**

**Given** a trade is closed
**When** exit is confirmed
**Then** trade record is saved:
```sql
INSERT INTO trades (
  trade_id, strategy_name, symbol, side,
  quantity, entry_price, entry_time,
  exit_price, exit_time, pnl_dollars, pnl_percent,
  slippage, signal_reason, metadata
) VALUES (...)
```

**And** I can query trades by:
- Date range
- Symbol
- Strategy
- P&L (winners/losers)

**Technical Notes:**
- Use TimescaleDB trades table from Architecture
- Include all fields for comprehensive analysis
- Store signal reasoning in metadata JSON
- Index on common query patterns

**Prerequisites:** Story 2.2

---

## Epic 7: Risk Management & Safety

**Goal:** Prevent financial errors and handle system failures gracefully.

**User Value:** Sleep well knowing the system won't blow up the account due to bugs or failures.

**FRs Covered:** FR44, FR45, FR46, FR47, FR48, FR49, FR50, FR51

**Technical Context:**
- Duplicate order prevention
- Connection monitoring
- Fail-safe defaults

---

### Story 7.1: Duplicate Order Prevention

As a trading engine,
I want to prevent duplicate order submissions,
So that I don't accidentally double my position.

**Acceptance Criteria:**

**Given** I submit order with ID "ORDER-123"
**When** order is pending confirmation
**And** I try to submit another order with same ID
**Then** second submission is rejected:
```
DuplicateOrderError: Order ORDER-123 already pending
```

**And Given** an order times out without confirmation
**When** I retry the order
**Then** the original order is first cancelled before retrying

**Technical Notes:**
- Track pending orders by ID
- Implement idempotency key
- Store order state in Redis
- TTL on order tracking: 1 hour

**Prerequisites:** Story 2.3

---

### Story 7.2: Connection Health Monitor

As a trading engine,
I want to monitor connection health to all external systems,
So that I can pause trading when connections are unhealthy.

**Acceptance Criteria:**

**Given** Redis connection is healthy
**When** health check runs (every 30 seconds)
**Then** health status is "connected"

**And Given** Redis connection fails
**When** 3 consecutive health checks fail
**Then** status changes to "disconnected"
**And** alert is published
**And** trading is paused

**And** monitoring covers:
- Redis (data feed)
- TimescaleDB (persistence)
- ZeroMQ (execution)

**Technical Notes:**
- Implement HealthMonitor class
- Store health status in Redis (for notification service)
- Configurable thresholds for unhealthy detection
- Auto-recovery when connection restored

**Prerequisites:** Epic 2

---

### Story 7.3: Automatic Reconnection

As a trading engine,
I want automatic reconnection to external systems,
So that transient failures don't require manual intervention.

**Acceptance Criteria:**

**Given** Redis connection is lost
**When** adapter detects disconnection
**Then** reconnection attempts start with exponential backoff:
- Attempt 1: Immediate
- Attempt 2: 1 second
- Attempt 3: 2 seconds
- Attempt 4: 4 seconds
- Max delay: 30 seconds

**And Given** reconnection succeeds
**When** connection is restored
**Then** subscriptions are re-established
**And** trading resumes if other connections healthy

**And Given** reconnection fails after 5 minutes
**When** max retries exceeded
**Then** alert is sent and trading remains paused

**Technical Notes:**
- Implement in each adapter
- Use exponential backoff with jitter
- Log each reconnection attempt
- Preserve message queue during disconnect if possible

**Prerequisites:** Story 7.2

---

### Story 7.4: Fail-Safe Defaults

As a trading engine,
I want fail-safe defaults in uncertain situations,
So that I don't trade when conditions are ambiguous.

**Acceptance Criteria:**

**Given** state is uncertain (e.g., recovery from crash)
**When** engine starts
**Then** trading is paused until state is validated

**And Given** data feed is stale (> 60 seconds old)
**When** signal is generated
**Then** signal is ignored with log:
```
Signal ignored: Data feed stale (last update: 90 seconds ago)
```

**And Given** any compliance check fails to execute (exception)
**When** order submission is attempted
**Then** order is rejected (assume worst case)

**Technical Notes:**
- Default to not trading when uncertain
- Log all fail-safe triggers
- Require explicit action to resume trading
- Implement as policy in RuleEngine

**Prerequisites:** Story 7.3

---

### Story 7.5: Aggregate Exposure Tracking

As a trading engine,
I want to track total exposure across all positions,
So that I don't over-leverage the account.

**Acceptance Criteria:**

**Given** I have:
- GOLD LONG 0.1 lots ($18,500 notional)
- BTC LONG 0.01 lots ($4,300 notional)
**When** I query aggregate exposure
**Then** I see: Total exposure = $22,800

**And Given** max total exposure is configured at $50,000
**When** I try to add $30,000 position
**Then** order is blocked (would exceed $50,000 limit)

**And** exposure is calculated in account currency (USD)

**Technical Notes:**
- Calculate notional value per position
- Sum across all open positions
- Apply configurable maximum
- Include in multi-layer validation

**Prerequisites:** Story 6.1

---

## Epic 8: Paper Trading & CLI

**Goal:** Validate strategy with real market data before risking capital.

**User Value:** Build confidence through extended paper trading that matches backtest expectations.

**FRs Covered:** FR66, FR67, FR68, FR69, FR70, FR82, FR83

**Technical Context:**
- Simulated execution with real data
- Mode switching via configuration
- Performance comparison

---

### Story 8.1: Paper Trading Mode

As a developer,
I want to run strategies in paper trading mode,
So that I can validate with real market data without risking money.

**Acceptance Criteria:**

**Given** config has `trading_mode: paper`
**When** engine starts
**Then** it:
- Connects to real market data (Redis, ZeroMQ)
- Uses simulated execution (no real orders)
- Applies realistic execution model (spreads, slippage)

**And Given** a signal generates an order
**When** order is "executed"
**Then** fill is simulated based on current market data
**And** position is tracked in paper trading state

**And** paper trades are stored separately from live trades

**Technical Notes:**
- Implement PaperExecutionClient
- Use same spread/slippage models as backtest
- Store in separate Redis keys and DB table
- Clear distinction in logs: `[PAPER]` prefix

**Prerequisites:** Epic 5, Epic 6

---

### Story 8.2: Mode Indication in Logs and Alerts

As a developer,
I want clear indication of trading mode in all outputs,
So that I never confuse paper trading with live trading.

**Acceptance Criteria:**

**Given** engine runs in paper mode
**When** log entry is written
**Then** it includes mode:
```json
{
  "trading_mode": "paper",
  "event": "order_filled",
  ...
}
```

**And Given** alert is published
**Then** alert includes mode indicator:
```
[PAPER] TRADE EXECUTED
Symbol: GOLD
...
```

**And Given** I query the engine status
**Then** mode is prominently displayed

**Technical Notes:**
- Add trading_mode to all log entries
- Include emoji/prefix in alerts
- CLI status command shows mode

**Prerequisites:** Story 8.1

---

### Story 8.3: Paper vs Backtest Comparison

As a developer,
I want to compare paper trading results to backtest results,
So that I can validate my execution model is realistic.

**Acceptance Criteria:**

**Given** I have completed:
- Backtest: 2024-01-01 to 2024-06-30
- Paper trading: 2024-07-01 to 2024-07-31

**When** I run comparison analysis
**Then** I see:
```
BACKTEST vs PAPER TRADING COMPARISON
════════════════════════════════════════

              Backtest    Paper    Diff
─────────────────────────────────────────
Return         12.5%      10.8%    -14%
Win Rate        58%        55%     -5%
Avg Slippage   0.3 pips   0.4 pips +33%
Sharpe          1.45       1.32    -9%

VERDICT: Paper trading within 20% of backtest ✓
```

**And** if paper results are < 80% of backtest
**Then** warning is generated

**Technical Notes:**
- Compare key metrics
- Flag significant divergences
- Suggest calibration if slippage differs significantly
- Store comparison reports

**Prerequisites:** Story 8.1, Epic 5

---

### Story 8.4: Live Trading Mode

As a developer,
I want to run in live trading mode after validation,
So that I can execute real trades on my FTMO account.

**Acceptance Criteria:**

**Given** config has `trading_mode: live`
**When** engine starts
**Then** it:
- Prompts for confirmation (safety check)
- Connects to real execution (mt5-bridge)
- Uses real order submission

**And Given** safety confirmation is not provided
**When** 30 seconds pass
**Then** engine exits (no silent live trading)

**And Given** paper trading hasn't been run
**When** I try to start live mode
**Then** warning is shown (not blocked, but warned)

**Technical Notes:**
- Require --confirm flag for live mode
- Log transition to live mode prominently
- No functional difference except execution client
- Same compliance, logging, and state management

**Prerequisites:** Story 8.1

---

### Story 8.5: Hot Reload Configuration

As a developer,
I want to reload strategy configuration without restart,
So that I can iterate quickly during development.

**Acceptance Criteria:**

**Given** engine is running
**When** I send SIGHUP signal (or CLI command)
**Then** configuration is reloaded:
- Strategy parameters updated
- Risk limits updated
- Logging level updated

**And** the following are NOT reloaded (require restart):
- Trading mode
- Database connections
- Core adapters

**And** if reload fails validation
**Then** old configuration is kept

**Technical Notes:**
- Watch config file for changes (development only)
- Implement reload via CLI command
- Validate new config before applying
- Log config changes

**Prerequisites:** Story 1.2

---

## Epic 9: Testing & Quality

**Goal:** Comprehensive test coverage to ensure system reliability.

**User Value:** Confidence that the system works correctly through automated testing.

**FRs Covered:** FR85, FR86, FR87, FR88, FR89

**Technical Context:**
- pytest for unit and integration tests
- Historical scenario replay
- CI/CD integration

---

### Story 9.1: Unit Test Framework

As a developer,
I want unit tests for core components,
So that I can catch bugs early.

**Acceptance Criteria:**

**Given** I run `pytest tests/unit`
**When** all tests pass
**Then** coverage is >= 70% for:
- Rule validators
- Position sizer
- State management
- Configuration loading

**And** tests are:
- Fast (< 10 seconds total)
- Isolated (no external dependencies)
- Deterministic (same result every run)

**Technical Notes:**
- Use pytest with pytest-asyncio
- Mock all external dependencies
- Use fixtures for common setup
- Include edge cases and error conditions

**Prerequisites:** All epics (concurrent with development)

---

### Story 9.2: Integration Test Suite

As a developer,
I want integration tests for adapter connections,
So that I can verify external system integration works.

**Acceptance Criteria:**

**Given** Docker infrastructure is running (Redis, TimescaleDB)
**When** I run `pytest tests/integration`
**Then** tests verify:
- Redis connection and pub/sub
- TimescaleDB queries and inserts
- ZeroMQ message passing (with mock bridge)

**And** integration tests can be skipped if infra unavailable

**Technical Notes:**
- Use Docker Compose for test infrastructure
- pytest markers for integration tests
- Skip if containers not running
- Clean up test data after each test

**Prerequisites:** Epic 2

---

### Story 9.3: Historical Scenario Replay

As a developer,
I want to replay historical scenarios,
So that I can regression test the compliance engine.

**Acceptance Criteria:**

**Given** a saved scenario (sequence of events that should trigger rule)
**When** I replay the scenario
**Then** the same compliance decisions are made

**Scenarios include:**
- Daily loss approaching 5%
- Drawdown approaching 10%
- Successful trade execution
- Order blocked by compliance

**And** scenarios are stored as JSON fixtures

**Technical Notes:**
- Record events during backtest
- Replay events through rule engine
- Assert on outcomes
- Use for regression testing after changes

**Prerequisites:** Epic 3

---

### Story 9.4: Backtest as Integration Test

As a developer,
I want to use backtest as an integration test,
So that I verify complete system behavior.

**Acceptance Criteria:**

**Given** test data (1 month of historical data)
**When** I run backtest in test mode
**Then** it verifies:
- Data loading works
- Strategy executes
- Compliance checks run
- Trades are recorded

**And** test backtest completes in < 60 seconds

**Technical Notes:**
- Use subset of data for speed
- Assert on expected outcomes
- Include in CI/CD pipeline
- Run after every significant change

**Prerequisites:** Epic 5

---

### Story 9.5: Zero False Negatives Validation

As a developer,
I want to verify zero false negatives in compliance,
So that I never allow a trade that should be blocked.

**Acceptance Criteria:**

**Given** historical violation scenarios (trades that should have been blocked)
**When** I replay through compliance engine
**Then** 100% of violations are detected (zero false negatives)

**Scenarios:**
- Order that would exceed daily loss limit
- Order that would exceed drawdown limit
- Order when emergency stop is active
- Order with corrupted data

**And** false positive rate is tracked (blocks that could have been allowed)

**Technical Notes:**
- Create comprehensive violation test cases
- Measure both false negative and false positive rates
- Target: 0% false negatives, < 5% false positives
- Document each test case

**Prerequisites:** Epic 3

---

## FR Coverage Matrix

| FR | Description | Epic | Story | Status |
|----|-------------|------|-------|--------|
| FR3 | Load historical data from TimescaleDB | 2 | 2.2 | Planned |
| FR4 | Validate data quality | 2 | 2.5 | Planned |
| FR6 | Cross-validate data sources | 2 | 2.5 | Planned |
| FR7 | Handle data unavailability | 2 | 2.5 | Planned |
| FR8 | Load rules from YAML | 3 | 3.1 | Planned |
| FR9 | Enforce max daily loss (5%) | 3 | 3.2 | Planned |
| FR10 | Enforce max drawdown (10%) | 3 | 3.3 | Planned |
| FR11 | Track trading days, profit target | 3 | 3.4 | Planned |
| FR12 | Validate after every bar | 3 | 3.5 | Planned |
| FR13 | Preventive order blocking | 3 | 3.2, 3.3 | Planned |
| FR14 | Multi-layer risk validation | 3 | 3.5 | Planned |
| FR15 | Immutable audit trail | 3 | 3.6 | Planned |
| FR16 | Support multiple prop firms | 3 | 3.1 | Planned |
| FR17 | Emergency stop mechanism | 3 | 3.7 | Planned |
| FR18 | Nautilus Strategy base class | 4 | 4.1 | Planned |
| FR19 | Signal on bar close | 4 | 4.3 | Planned |
| FR20 | Position sizing with FTMO | 4 | 4.2 | Planned |
| FR21 | Multi-symbol management | 4 | 4.4 | Planned |
| FR22 | Execute via ZeroMQ | 2 | 2.3 | Planned |
| FR23 | Baseline strategy | 4 | 4.3 | Planned |
| FR24 | Strategy lifecycle hooks | 4 | 4.1 | Planned |
| FR25 | Access positions, balance | 4 | 4.1 | Planned |
| FR26 | Log trade decisions | 4 | 4.5 | Planned |
| FR27 | Nautilus BacktestEngine | 5 | 5.1 | Planned |
| FR28 | Realistic execution model | 5 | 5.2, 5.3, 5.4 | Planned |
| FR29 | Dynamic spread modeling | 5 | 5.2 | Planned |
| FR30 | Slippage simulation | 5 | 5.3 | Planned |
| FR31 | Latency simulation | 5 | 5.4 | Planned |
| FR32 | Walk-forward analysis | 5 | 5.5 | Planned |
| FR33 | Validation reports | 5 | 5.6 | Planned |
| FR34 | Red flag detection | 5 | 5.6 | Planned |
| FR35 | Same code backtest/live | 5 | 5.1 | Planned |
| FR36 | Real-time state cache | 6 | 6.1 | Planned |
| FR37 | Redis snapshots | 6 | 6.2 | Planned |
| FR38 | Crash recovery | 6 | 6.3 | Planned |
| FR39 | State validation on startup | 6 | 6.3 | Planned |
| FR40 | Broker reconciliation | 6 | 6.4 | Planned |
| FR41 | Trade persistence | 6 | 6.5 | Planned |
| FR42 | Performance metrics | 6 | 6.5 | Planned |
| FR43 | Append-only audit | 3 | 3.6 | Planned |
| FR44 | Duplicate order prevention | 7 | 7.1 | Planned |
| FR45 | Position reconciliation alerts | 6 | 6.4 | Planned |
| FR46 | Balance verification | 6 | 6.4 | Planned |
| FR47 | Anomaly detection | 7 | 7.4 | Planned |
| FR48 | Connection loss detection | 7 | 7.2 | Planned |
| FR49 | Fail-safe defaults | 7 | 7.4 | Planned |
| FR50 | Auto-reconnection | 7 | 7.3 | Planned |
| FR51 | Aggregate exposure tracking | 7 | 7.5 | Planned |
| FR52 | Structured JSON logging | 1 | 1.3 | Planned |
| FR60 | Submit orders via ZeroMQ | 2 | 2.3 | Planned |
| FR62 | Measure slippage | 5 | 5.3 | Planned |
| FR63 | Track execution latency | 5 | 5.4 | Planned |
| FR66 | Paper trading mode | 8 | 8.1 | Planned |
| FR67 | Compare paper vs backtest | 8 | 8.3 | Planned |
| FR68 | Mode switching | 8 | 8.4 | Planned |
| FR69 | Mode indication in logs | 8 | 8.2 | Planned |
| FR70 | Separate state per mode | 8 | 8.1 | Planned |
| FR71 | YAML configuration | 1 | 1.2 | Planned |
| FR72 | Environment variables | 1 | 1.2 | Planned |
| FR73 | Startup validation | 1 | 1.2 | Planned |
| FR74 | Mock data mode | 2 | 2.4 | Planned |
| FR82 | CLI commands | 1 | 1.4 | Planned |
| FR83 | Hot reload | 8 | 8.5 | Planned |
| FR85 | Scenario replay | 9 | 9.3 | Planned |
| FR86 | Unit tests | 9 | 9.1 | Planned |
| FR87 | Integration tests | 9 | 9.2 | Planned |
| FR88 | Backtest as integration | 9 | 9.4 | Planned |
| FR89 | Zero false negatives | 9 | 9.5 | Planned |

**Total FRs Covered:** 67
**Total Stories:** 45

---

## Summary

### Epic Summary

| Epic | Stories | FRs Covered | Priority |
|------|---------|-------------|----------|
| 1. Foundation | 5 | 5 | P0 - Must Have |
| 2. Adapters | 5 | 6 | P0 - Must Have |
| 3. Compliance | 7 | 10 | P0 - Critical |
| 4. Strategy | 5 | 9 | P0 - Must Have |
| 5. Backtesting | 6 | 9 | P1 - Should Have |
| 6. State | 5 | 8 | P0 - Must Have |
| 7. Risk | 5 | 8 | P0 - Must Have |
| 8. Paper Trading | 5 | 7 | P1 - Should Have |
| 9. Testing | 5 | 5 | P1 - Concurrent |

### Implementation Order

```
Phase 1: Foundation (Epic 1, 2)
    ├── Project setup, adapters, mocks
    └── Can run basic tests

Phase 2: Core Trading (Epic 3, 4)
    ├── FTMO compliance engine
    ├── Strategy framework
    └── Can run backtests with compliance

Phase 3: Validation (Epic 5, 6, 7)
    ├── Backtesting with realistic model
    ├── State management
    ├── Risk safety
    └── Can validate strategy confidence

Phase 4: Go Live (Epic 8)
    ├── Paper trading
    ├── Live trading
    └── Ready for FTMO challenge

Phase 5: Quality (Epic 9)
    └── Concurrent with all phases
```

### Success Criteria Mapping

| Success Criterion | Epics Required |
|-------------------|----------------|
| Zero FTMO violations (30+ days paper) | 3, 6, 7, 8 |
| Paper within 20% of backtest | 5, 8 |
| 24-hour uptime | 6, 7 |
| Walk-forward consistency | 5 |
| Data pipeline quality | 2 |

---

_For implementation: Use the `dev-story` workflow to implement individual stories from this epic breakdown._

_This document covers trading-engine service only. Other services (tv-api, mt5-bridge, notification) require separate epic breakdowns._

_Generated via YOLO mode workflow execution._
