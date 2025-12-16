# Schema Design - Multi-Account Trading System

**Version:** 1.0 Draft
**Date:** 2025-12-07
**Author:** Business Analyst Mary

---

## Overview

This document defines all data schemas for the Multi-Account Trading System, including:
- Database schemas (TimescaleDB/PostgreSQL)
- Redis data structures
- YAML configuration schemas
- Message/Event schemas (ZeroMQ, Redis Pub/Sub)

---

## Table of Contents

1. [Database Schema (TimescaleDB)](#1-database-schema-timescaledb)
2. [Redis Data Structures](#2-redis-data-structures)
3. [YAML Configuration Schemas](#3-yaml-configuration-schemas)
4. [Message Schemas (ZeroMQ)](#4-message-schemas-zeromq)
5. [Event Schemas (Internal)](#5-event-schemas-internal)

---

## 1. Database Schema (TimescaleDB)

### 1.1 Entity Relationship Diagram

```
┌─────────────────┐       ┌─────────────────┐
│   prop_firms    │       │    accounts     │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │◄──────│ prop_firm_id(FK)│
│ name            │       │ id (PK)         │
│ rules_preset    │       │ name            │
│ description     │       │ account_type    │
└─────────────────┘       │ mt5_server      │
                          │ mt5_login       │
                          │ strategy_name   │
                          │ status          │
                          └────────┬────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     trades      │    │  audit_logs     │    │account_snapshots│
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ trade_id (PK)   │    │ log_id (PK)     │    │ id (PK)         │
│ account_id (FK) │    │ account_id (FK) │    │ account_id (FK) │
│ symbol          │    │ event_type      │    │ snapshot_date   │
│ side            │    │ rule_name       │    │ daily_pnl       │
│ entry_price     │    │ rule_result     │    │ drawdown_percent│
└─────────────────┘    └─────────────────┘    └─────────────────┘
          │
          │
          ▼
┌─────────────────┐    ┌─────────────────┐
│rule_violations  │    │    candles      │
├─────────────────┤    ├─────────────────┤
│ id (PK)         │    │ time (PK)       │
│ account_id (FK) │    │ symbol          │
│ rule_type       │    │ timeframe       │
│ action_taken    │    │ open/high/low   │
└─────────────────┘    └─────────────────┘
```

### 1.2 Table Definitions

#### 1.2.1 `prop_firms` - Prop Firm Reference

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | VARCHAR(50) | PRIMARY KEY | Unique identifier (e.g., 'ftmo', 'the5ers') |
| `name` | VARCHAR(100) | NOT NULL | Display name |
| `rules_preset` | VARCHAR(50) | NOT NULL | Reference to YAML preset file |
| `website` | VARCHAR(255) | | Official website URL |
| `description` | TEXT | | Additional notes |
| `is_active` | BOOLEAN | DEFAULT TRUE | Whether this prop firm is currently supported |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

**Default Data:**
```sql
INSERT INTO prop_firms (id, name, rules_preset, website) VALUES
  ('ftmo', 'FTMO', 'ftmo', 'https://ftmo.com'),
  ('the5ers', 'The5ers', 'the5ers', 'https://the5ers.com'),
  ('wmt', 'WeMasterTrade', 'wmt', 'https://wemastertrade.com');
```

---

#### 1.2.2 `accounts` - Trading Accounts

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | VARCHAR(50) | PRIMARY KEY | Unique identifier (e.g., 'ftmo-gold-001') |
| `name` | VARCHAR(100) | NOT NULL | Human-readable name |
| `account_type` | VARCHAR(20) | NOT NULL | 'prop_firm', 'personal', 'demo' |
| `prop_firm_id` | VARCHAR(50) | FK → prop_firms | NULL for personal/demo accounts |
| `custom_rules_file` | VARCHAR(255) | | Path to custom rules YAML (for personal) |
| `mt5_server` | VARCHAR(100) | NOT NULL | MT5 server name |
| `mt5_login` | BIGINT | NOT NULL | MT5 account number |
| `mt5_password_env` | VARCHAR(100) | NOT NULL | Environment variable name for password |
| `strategy_name` | VARCHAR(100) | NOT NULL | Strategy class name |
| `strategy_params` | JSONB | | Strategy configuration |
| `signal_filter` | JSONB | | Signal filtering rules |
| `status` | VARCHAR(20) | DEFAULT 'inactive' | 'active', 'paused', 'stopped', 'inactive' |
| `initial_balance` | DECIMAL(18,2) | | Starting balance |
| `current_balance` | DECIMAL(18,2) | | Current balance (synced from MT5) |
| `peak_balance` | DECIMAL(18,2) | | Highest balance achieved |
| `currency` | VARCHAR(3) | DEFAULT 'USD' | Account currency |
| `leverage` | INTEGER | | Account leverage (e.g., 100) |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `last_sync_at` | TIMESTAMPTZ | | Last MT5 sync timestamp |

**Indexes:**
```sql
CREATE INDEX idx_accounts_status ON accounts (status);
CREATE INDEX idx_accounts_type ON accounts (account_type);
CREATE INDEX idx_accounts_prop_firm ON accounts (prop_firm_id);
```

**Example Data:**
```json
// strategy_params example
{
  "fast_period": 20,
  "slow_period": 50,
  "atr_period": 14,
  "risk_per_trade": 0.01
}

// signal_filter example
{
  "symbols": ["XAUUSD", "EURUSD"],
  "sessions": ["london", "new_york"],
  "max_spread_pips": 2.0,
  "min_volume": 1000
}
```

---

#### 1.2.3 `account_snapshots` - Daily Account State

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Auto-generated |
| `account_id` | VARCHAR(50) | FK → accounts, NOT NULL | |
| `snapshot_date` | DATE | NOT NULL | Date of snapshot |
| `snapshot_time` | TIME | DEFAULT '00:00:00' | Time of snapshot (for intraday) |
| `opening_balance` | DECIMAL(18,2) | | Balance at start of day |
| `closing_balance` | DECIMAL(18,2) | | Balance at end of day |
| `high_balance` | DECIMAL(18,2) | | Highest balance during day |
| `low_balance` | DECIMAL(18,2) | | Lowest balance during day |
| `daily_pnl` | DECIMAL(18,2) | | P&L for the day |
| `daily_pnl_percent` | DECIMAL(8,4) | | P&L as percentage |
| `peak_balance` | DECIMAL(18,2) | | All-time high balance |
| `drawdown_from_peak` | DECIMAL(18,2) | | Drawdown amount from peak |
| `drawdown_percent` | DECIMAL(8,4) | | Drawdown as percentage |
| `trades_count` | INTEGER | DEFAULT 0 | Number of trades |
| `winning_trades` | INTEGER | DEFAULT 0 | |
| `losing_trades` | INTEGER | DEFAULT 0 | |
| `total_volume` | DECIMAL(18,2) | DEFAULT 0 | Total lots traded |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |

**Constraints:**
```sql
UNIQUE (account_id, snapshot_date);
```

---

#### 1.2.4 `trades` - Trade History

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Internal trade ID |
| `account_id` | VARCHAR(50) | FK → accounts, NOT NULL | |
| `mt5_ticket` | BIGINT | | MT5 order ticket number |
| `mt5_position_id` | BIGINT | | MT5 position ID |
| `strategy_name` | VARCHAR(100) | NOT NULL | Strategy that generated signal |
| `symbol` | VARCHAR(20) | NOT NULL | Trading symbol |
| `side` | VARCHAR(4) | NOT NULL | 'BUY' or 'SELL' |
| `order_type` | VARCHAR(20) | NOT NULL | 'MARKET', 'LIMIT', 'STOP' |
| `quantity` | DECIMAL(18,8) | NOT NULL | Lot size |
| `entry_price` | DECIMAL(18,5) | NOT NULL | Entry price |
| `entry_time` | TIMESTAMPTZ | NOT NULL | Entry timestamp |
| `stop_loss` | DECIMAL(18,5) | | Stop loss price |
| `take_profit` | DECIMAL(18,5) | | Take profit price |
| `exit_price` | DECIMAL(18,5) | | Exit price (NULL if open) |
| `exit_time` | TIMESTAMPTZ | | Exit timestamp |
| `exit_reason` | VARCHAR(50) | | 'tp_hit', 'sl_hit', 'manual', 'signal', 'rule_violation' |
| `pnl_dollars` | DECIMAL(18,2) | | Realized P&L in dollars |
| `pnl_pips` | DECIMAL(18,2) | | P&L in pips |
| `pnl_percent` | DECIMAL(8,4) | | P&L as percentage of balance |
| `commission` | DECIMAL(18,2) | DEFAULT 0 | Commission paid |
| `swap` | DECIMAL(18,2) | DEFAULT 0 | Swap/rollover |
| `slippage_pips` | DECIMAL(18,2) | | Slippage from requested price |
| `execution_time_ms` | INTEGER | | Time to execute in milliseconds |
| `signal_reason` | TEXT | | Why the signal was generated |
| `metadata` | JSONB | | Additional trade data |
| `status` | VARCHAR(20) | DEFAULT 'open' | 'open', 'closed', 'cancelled' |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

**Indexes:**
```sql
CREATE INDEX idx_trades_account_time ON trades (account_id, entry_time DESC);
CREATE INDEX idx_trades_symbol ON trades (symbol, entry_time DESC);
CREATE INDEX idx_trades_status ON trades (status) WHERE status = 'open';
CREATE INDEX idx_trades_mt5_ticket ON trades (mt5_ticket);
```

---

#### 1.2.5 `rule_violations` - Compliance Violations

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | |
| `account_id` | VARCHAR(50) | FK → accounts, NOT NULL | |
| `timestamp` | TIMESTAMPTZ | NOT NULL | When violation occurred |
| `rule_type` | VARCHAR(50) | NOT NULL | 'daily_loss_limit', 'max_drawdown', etc. |
| `rule_name` | VARCHAR(100) | NOT NULL | Human-readable rule name |
| `severity` | VARCHAR(20) | NOT NULL | 'warning', 'violation', 'critical' |
| `current_value` | DECIMAL(18,4) | | Value that triggered violation |
| `threshold_value` | DECIMAL(18,4) | | Rule threshold |
| `threshold_percent` | DECIMAL(8,4) | | How close to limit (e.g., 85% of limit) |
| `action_taken` | VARCHAR(50) | NOT NULL | 'warned', 'blocked', 'stopped' |
| `trade_id` | UUID | FK → trades | Related trade (if applicable) |
| `order_blocked` | BOOLEAN | DEFAULT FALSE | Whether an order was blocked |
| `message` | TEXT | | Detailed description |
| `context` | JSONB | | Additional context data |
| `acknowledged` | BOOLEAN | DEFAULT FALSE | User acknowledged |
| `acknowledged_at` | TIMESTAMPTZ | | |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |

**Hypertable:**
```sql
SELECT create_hypertable('rule_violations', 'timestamp');
```

---

#### 1.2.6 `audit_logs` - System Audit Trail

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | |
| `timestamp` | TIMESTAMPTZ | NOT NULL | |
| `account_id` | VARCHAR(50) | FK → accounts | NULL for system events |
| `event_type` | VARCHAR(50) | NOT NULL | Event category |
| `event_subtype` | VARCHAR(50) | | Event subcategory |
| `source` | VARCHAR(50) | NOT NULL | 'trading_engine', 'rule_engine', 'mt5_bridge' |
| `level` | VARCHAR(20) | DEFAULT 'INFO' | 'DEBUG', 'INFO', 'WARNING', 'ERROR' |
| `message` | TEXT | | Human-readable description |
| `rule_name` | VARCHAR(100) | | For rule-related events |
| `rule_result` | VARCHAR(20) | | 'passed', 'warned', 'blocked' |
| `current_value` | DECIMAL(18,4) | | |
| `threshold_value` | DECIMAL(18,4) | | |
| `trade_id` | UUID | | Related trade |
| `order_id` | VARCHAR(50) | | MT5 order ID |
| `context` | JSONB | | Additional data |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |

**Event Types:**
```
- account.started, account.stopped, account.paused
- trade.signal, trade.submitted, trade.filled, trade.closed
- rule.checked, rule.warning, rule.violation
- system.startup, system.shutdown, system.error
- mt5.connected, mt5.disconnected, mt5.error
```

---

#### 1.2.7 `candles` - OHLCV Market Data

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `time` | TIMESTAMPTZ | NOT NULL | Candle open time |
| `symbol` | VARCHAR(20) | NOT NULL | Trading symbol |
| `timeframe` | VARCHAR(5) | NOT NULL | '1m', '5m', '15m', '1h', '4h', '1d' |
| `open` | DECIMAL(18,5) | NOT NULL | |
| `high` | DECIMAL(18,5) | NOT NULL | |
| `low` | DECIMAL(18,5) | NOT NULL | |
| `close` | DECIMAL(18,5) | NOT NULL | |
| `volume` | DECIMAL(18,2) | | |
| `tick_volume` | INTEGER | | MT5 tick volume |
| `spread` | DECIMAL(18,5) | | Average spread during candle |
| `source` | VARCHAR(20) | DEFAULT 'tradingview' | 'tradingview', 'mt5' |

**Hypertable & Indexes:**
```sql
SELECT create_hypertable('candles', 'time');
CREATE UNIQUE INDEX idx_candles_unique ON candles (symbol, timeframe, time);
CREATE INDEX idx_candles_symbol_time ON candles (symbol, time DESC);
```

---

#### 1.2.8 `performance_metrics` - Daily Performance

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `date` | DATE | NOT NULL | |
| `account_id` | VARCHAR(50) | FK → accounts, NOT NULL | |
| `strategy_name` | VARCHAR(100) | NOT NULL | |
| `total_trades` | INTEGER | DEFAULT 0 | |
| `winning_trades` | INTEGER | DEFAULT 0 | |
| `losing_trades` | INTEGER | DEFAULT 0 | |
| `gross_profit` | DECIMAL(18,2) | DEFAULT 0 | |
| `gross_loss` | DECIMAL(18,2) | DEFAULT 0 | |
| `net_profit` | DECIMAL(18,2) | DEFAULT 0 | |
| `win_rate` | DECIMAL(8,4) | | |
| `profit_factor` | DECIMAL(8,4) | | gross_profit / gross_loss |
| `average_win` | DECIMAL(18,2) | | |
| `average_loss` | DECIMAL(18,2) | | |
| `largest_win` | DECIMAL(18,2) | | |
| `largest_loss` | DECIMAL(18,2) | | |
| `max_drawdown_percent` | DECIMAL(8,4) | | |
| `sharpe_ratio` | DECIMAL(8,4) | | |
| `sortino_ratio` | DECIMAL(8,4) | | |
| `total_volume` | DECIMAL(18,2) | | |
| `average_hold_time_minutes` | INTEGER | | |
| `created_at` | TIMESTAMPTZ | DEFAULT NOW() | |

**Primary Key:**
```sql
PRIMARY KEY (date, account_id, strategy_name)
```

---

#### 1.2.9 `symbols` - Trading Symbols Metadata

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `symbol` | VARCHAR(20) | PRIMARY KEY | Symbol name |
| `display_name` | VARCHAR(50) | | Human-readable name |
| `category` | VARCHAR(20) | | 'forex', 'metals', 'crypto', 'indices' |
| `base_currency` | VARCHAR(10) | | Base currency |
| `quote_currency` | VARCHAR(10) | | Quote currency |
| `pip_size` | DECIMAL(18,10) | | Size of 1 pip |
| `pip_value` | DECIMAL(18,4) | | Value per pip per lot |
| `contract_size` | DECIMAL(18,2) | | Contract size |
| `min_lot` | DECIMAL(18,4) | | Minimum lot size |
| `max_lot` | DECIMAL(18,4) | | Maximum lot size |
| `lot_step` | DECIMAL(18,4) | | Lot size step |
| `typical_spread` | DECIMAL(18,2) | | Typical spread in pips |
| `volatile_spread` | DECIMAL(18,2) | | Spread during volatility |
| `trading_hours` | JSONB | | Trading session hours |
| `is_active` | BOOLEAN | DEFAULT TRUE | |
| `updated_at` | TIMESTAMPTZ | DEFAULT NOW() | |

**Example trading_hours:**
```json
{
  "sunday": {"open": "22:00", "close": "24:00"},
  "monday": {"open": "00:00", "close": "24:00"},
  "friday": {"open": "00:00", "close": "22:00"}
}
```

---

## 2. Redis Data Structures

### 2.1 Account State (Hash)

**Key Pattern:** `account:{account_id}:state`

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | 'active', 'paused', 'stopped' |
| `balance` | float | Current balance |
| `equity` | float | Current equity |
| `margin` | float | Used margin |
| `free_margin` | float | Available margin |
| `margin_level` | float | Margin level % |
| `open_positions` | int | Number of open positions |
| `daily_pnl` | float | Today's P&L |
| `daily_pnl_percent` | float | Today's P&L % |
| `peak_balance` | float | All-time high |
| `drawdown_percent` | float | Current drawdown % |
| `last_trade_time` | timestamp | Last trade timestamp |
| `trades_today` | int | Number of trades today |
| `updated_at` | timestamp | Last update time |

**TTL:** None (persistent)

**Example:**
```redis
HSET account:ftmo-gold-001:state status "active" balance 100500.00 equity 100650.00 daily_pnl 500.00 daily_pnl_percent 0.50
```

---

### 2.2 Open Positions (Hash)

**Key Pattern:** `account:{account_id}:positions`

| Field | Type | Description |
|-------|------|-------------|
| `{position_id}` | JSON | Position details |

**Position JSON:**
```json
{
  "ticket": 12345678,
  "symbol": "XAUUSD",
  "side": "BUY",
  "volume": 0.1,
  "open_price": 1850.25,
  "open_time": "2025-12-07T10:30:00Z",
  "sl": 1845.00,
  "tp": 1860.00,
  "current_price": 1852.50,
  "pnl": 225.00,
  "swap": -1.25
}
```

---

### 2.3 Rule State (Hash)

**Key Pattern:** `account:{account_id}:rules`

| Field | Type | Description |
|-------|------|-------------|
| `daily_loss_used` | float | Daily loss consumed |
| `daily_loss_limit` | float | Daily loss limit |
| `daily_loss_percent` | float | % of limit used |
| `max_drawdown_current` | float | Current drawdown |
| `max_drawdown_limit` | float | Max drawdown limit |
| `trades_today` | int | Trades count today |
| `trades_limit` | int | Max trades per day |
| `last_trade_time` | timestamp | For cooldown rules |
| `trading_blocked` | boolean | Whether trading is blocked |
| `block_reason` | string | Why blocked |

---

### 2.4 Candle Cache (Sorted Set)

**Key Pattern:** `candles:{symbol}:{timeframe}`

**Score:** Unix timestamp (milliseconds)
**Value:** JSON candle data

```json
{
  "o": 1850.25,
  "h": 1852.50,
  "l": 1849.00,
  "c": 1851.75,
  "v": 12500,
  "t": 1701950400000
}
```

**TTL:** 24 hours

---

### 2.5 Latest Tick (String)

**Key Pattern:** `tick:{symbol}`

**Value:** JSON
```json
{
  "bid": 1851.50,
  "ask": 1851.75,
  "spread": 0.25,
  "time": "2025-12-07T14:32:15.123Z"
}
```

**TTL:** 60 seconds

---

### 2.6 Health Check (String)

**Key Pattern:** `health:{service_name}`

**Value:** JSON
```json
{
  "status": "healthy",
  "last_heartbeat": "2025-12-07T14:32:15.123Z",
  "uptime_seconds": 86400,
  "version": "1.0.0"
}
```

**TTL:** 30 seconds (must be refreshed by service)

---

### 2.7 Alert Queue (List)

**Key Pattern:** `alerts:queue`

**Value:** JSON alert messages (LPUSH, RPOP)
```json
{
  "type": "rule_warning",
  "account_id": "ftmo-gold-001",
  "severity": "warning",
  "message": "Daily loss at 80% of limit",
  "timestamp": "2025-12-07T14:32:15.123Z",
  "data": {
    "current": 4.0,
    "limit": 5.0
  }
}
```

---

### 2.8 Pub/Sub Channels

| Channel | Publisher | Subscriber | Data |
|---------|-----------|------------|------|
| `bars:{symbol}:{timeframe}` | tv-api | trading-engine | New candle |
| `ticks:{symbol}` | mt5-bridge | trading-engine | Bid/ask tick |
| `trades:{account_id}` | trading-engine | notification | Trade events |
| `alerts:{account_id}` | trading-engine | notification | Rule alerts |
| `alerts:system` | any service | notification | System alerts |
| `commands:{account_id}` | notification | trading-engine | Control commands |

---

## 3. YAML Configuration Schemas

### 3.1 Account Configuration (`accounts.yaml`)

```yaml
# Schema: accounts.yaml
# Max 5 accounts supported

accounts:
  - id: string              # Required, unique identifier
    name: string            # Required, display name
    type: enum              # Required: 'prop_firm' | 'personal' | 'demo'

    # For prop_firm type
    prop_firm: string       # 'ftmo' | 'the5ers' | 'wmt'

    # For personal/demo type
    rules_file: string      # Path to custom rules YAML

    # MT5 Connection (required)
    mt5:
      server: string        # MT5 server name
      login: integer        # Account number
      password_env: string  # Environment variable name

    # Strategy (required)
    strategy: string        # Strategy class name
    strategy_params:        # Optional, strategy-specific
      key: value

    # Signal Filter (optional)
    signal_filter:
      symbols: [string]     # Allowed symbols
      sessions: [string]    # 'asian' | 'london' | 'new_york'
      max_spread_pips: float
      min_volume: integer

    # Status
    status: enum            # 'active' | 'paused' | 'inactive'
```

**Example:**
```yaml
accounts:
  - id: "ftmo-gold-001"
    name: "FTMO Gold Challenge"
    type: "prop_firm"
    prop_firm: "ftmo"
    mt5:
      server: "FTMO-Demo"
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
```

---

### 3.2 Rule Preset Schema (`presets/*.yaml`)

```yaml
# Schema: Rule Preset
name: string                # Required, preset name
version: string             # Required, version number
description: string         # Optional
prop_firm: string           # Optional, prop firm reference

rules:
  # Drawdown Rules
  - type: "daily_loss_limit"
    threshold_percent: float      # e.g., 5.0
    reset_time: string            # e.g., "00:00"
    timezone: string              # e.g., "UTC"
    action: enum                  # 'block_trading' | 'warn' | 'notify'
    warning_at: [float]           # e.g., [70, 80, 90] - percentages

  - type: "max_drawdown"
    threshold_percent: float      # e.g., 10.0
    reference: enum               # 'initial_balance' | 'peak_balance'
    action: enum
    warning_at: [float]

  - type: "trailing_drawdown"
    threshold_percent: float
    lock_at_profit: float         # Lock when profit reaches X%
    action: enum

  # Time-based Rules
  - type: "trading_hours"
    start: string                 # "HH:MM"
    end: string                   # "HH:MM"
    timezone: string
    action: enum

  - type: "trading_sessions"
    allowed: [string]             # ['asian', 'london', 'new_york']
    action: enum

  - type: "trading_days"
    allowed: [string]             # ['monday', 'tuesday', ...]
    action: enum

  - type: "news_blackout"
    before_minutes: integer       # Minutes before news
    after_minutes: integer        # Minutes after news
    impact_levels: [string]       # ['high', 'medium']
    action: enum

  # Position Rules
  - type: "max_position_size"
    max_lots: float
    scaling: enum                 # 'fixed' | 'per_10k_balance'
    action: enum

  - type: "max_open_positions"
    limit: integer
    action: enum

  - type: "max_per_symbol"
    limit: integer
    action: enum

  - type: "max_total_exposure"
    max_percent: float            # % of balance
    action: enum

  # Symbol Rules
  - type: "allowed_symbols"
    symbols: [string]
    action: enum

  - type: "blocked_symbols"
    symbols: [string]
    action: enum

  # Frequency Rules
  - type: "max_trades_per_day"
    limit: integer
    action: enum

  - type: "min_trade_interval"
    minutes: integer
    action: enum

  - type: "max_trades_per_hour"
    limit: integer
    action: enum

  # Custom Rules
  - type: "max_spread"
    max_pips: float
    action: enum                  # 'skip_signal' | 'warn'

  - type: "min_risk_reward"
    min_ratio: float              # e.g., 1.5
    action: enum

  # Monitoring (no blocking)
  - type: "profit_target"
    target_percent: float
    action: "notify"

  - type: "min_trading_days"
    min_days: integer
    action: "notify"
```

---

### 3.3 FTMO Preset Example

```yaml
# presets/ftmo.yaml
name: "FTMO Challenge Rules"
version: "2024.1"
description: "Official FTMO challenge and funded account rules"
prop_firm: "ftmo"

rules:
  # === MANDATORY RULES ===

  # Daily Loss Limit: 5%
  - type: "daily_loss_limit"
    threshold_percent: 5.0
    reset_time: "00:00"
    timezone: "CET"
    action: "block_trading"
    warning_at: [70, 80, 90]

  # Maximum Drawdown: 10%
  - type: "max_drawdown"
    threshold_percent: 10.0
    reference: "initial_balance"
    action: "block_trading"
    warning_at: [50, 70, 85]

  # === MONITORING RULES ===

  # Profit Target: 10% (Challenge phase)
  - type: "profit_target"
    target_percent: 10.0
    action: "notify"

  # Minimum Trading Days: 4
  - type: "min_trading_days"
    min_days: 4
    action: "notify"

  # === RECOMMENDED RULES ===

  # Conservative position sizing
  - type: "max_position_size"
    max_lots: 10.0
    scaling: "per_10k_balance"
    action: "block_trading"

  # Avoid over-trading
  - type: "max_open_positions"
    limit: 5
    action: "warn"
```

---

### 3.4 Custom Rules Example

```yaml
# custom/my_rules.yaml
name: "BMad Personal Rules"
version: "1.0"
description: "Conservative personal trading rules"
copied_from: "ftmo"  # Reference only

rules:
  # Stricter drawdown
  - type: "daily_loss_limit"
    threshold_percent: 2.0
    reset_time: "00:00"
    timezone: "UTC"
    action: "block_trading"
    warning_at: [50, 75]

  - type: "max_drawdown"
    threshold_percent: 5.0
    reference: "peak_balance"
    action: "block_trading"
    warning_at: [40, 60, 80]

  # Time restrictions
  - type: "trading_hours"
    start: "08:00"
    end: "20:00"
    timezone: "UTC"
    action: "block_trading"

  - type: "trading_sessions"
    allowed: ["london", "new_york"]
    action: "block_trading"

  - type: "trading_days"
    allowed: ["monday", "tuesday", "wednesday", "thursday", "friday"]
    action: "block_trading"

  # Position limits
  - type: "max_open_positions"
    limit: 2
    action: "block_trading"

  - type: "max_per_symbol"
    limit: 1
    action: "block_trading"

  # Frequency limits
  - type: "max_trades_per_day"
    limit: 5
    action: "block_trading"

  - type: "min_trade_interval"
    minutes: 30
    action: "block_trading"

  # Symbol restrictions
  - type: "allowed_symbols"
    symbols: ["EURUSD", "GBPUSD", "XAUUSD"]
    action: "block_trading"

  # Quality filters
  - type: "max_spread"
    max_pips: 2.0
    action: "skip_signal"

  - type: "min_risk_reward"
    min_ratio: 1.5
    action: "skip_signal"
```

---

## 4. Message Schemas (ZeroMQ)

### 4.1 MT5 → Bridge: Tick Data

```json
{
  "type": "tick",
  "symbol": "XAUUSD",
  "bid": 1850.25,
  "ask": 1850.45,
  "spread": 0.20,
  "timestamp": "2025-12-07T14:32:15.123Z",
  "volume": 125
}
```

### 4.2 MT5 → Bridge: Account Update

```json
{
  "type": "account_update",
  "login": 12345678,
  "balance": 100500.00,
  "equity": 100650.00,
  "margin": 1500.00,
  "free_margin": 99150.00,
  "margin_level": 6710.00,
  "timestamp": "2025-12-07T14:32:15.123Z"
}
```

### 4.3 Bridge → MT5: Order Request

```json
{
  "type": "order_request",
  "request_id": "req-123-456",
  "account_login": 12345678,
  "action": "BUY",
  "symbol": "XAUUSD",
  "volume": 0.1,
  "order_type": "MARKET",
  "price": 1850.45,
  "sl": 1845.00,
  "tp": 1860.00,
  "magic": 123456,
  "comment": "MA_Crossover_Signal",
  "timestamp": "2025-12-07T14:32:15.123Z"
}
```

### 4.4 MT5 → Bridge: Order Result

```json
{
  "type": "order_result",
  "request_id": "req-123-456",
  "status": "filled",
  "ticket": 87654321,
  "position_id": 87654321,
  "symbol": "XAUUSD",
  "volume": 0.1,
  "price": 1850.47,
  "sl": 1845.00,
  "tp": 1860.00,
  "slippage": 0.02,
  "commission": 0.70,
  "timestamp": "2025-12-07T14:32:15.456Z",
  "error_code": 0,
  "error_message": null
}
```

### 4.5 Bridge → MT5: Close Position

```json
{
  "type": "close_position",
  "request_id": "req-789-012",
  "account_login": 12345678,
  "ticket": 87654321,
  "volume": 0.1,
  "price": 1855.00,
  "comment": "TP_Hit",
  "timestamp": "2025-12-07T15:45:30.123Z"
}
```

---

## 5. Event Schemas (Internal)

### 5.1 Signal Event

```python
@dataclass
class SignalEvent:
    id: str                    # Unique signal ID
    timestamp: datetime
    source: str                # Strategy name
    symbol: str
    direction: Literal["BUY", "SELL"]
    strength: float            # 0.0 - 1.0
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    risk_reward: float
    reason: str                # Signal explanation
    metadata: dict             # Additional data
```

### 5.2 Rule Check Event

```python
@dataclass
class RuleCheckEvent:
    id: str
    timestamp: datetime
    account_id: str
    rule_type: str
    rule_name: str
    current_value: Decimal
    threshold_value: Decimal
    result: Literal["passed", "warned", "blocked"]
    action_taken: str
    message: str
    context: dict
```

### 5.3 Trade Event

```python
@dataclass
class TradeEvent:
    id: str
    timestamp: datetime
    account_id: str
    event_type: Literal["opened", "modified", "closed", "cancelled"]
    trade_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    volume: Decimal
    price: Decimal
    pnl: Optional[Decimal]
    reason: str
    metadata: dict
```

### 5.4 Alert Event

```python
@dataclass
class AlertEvent:
    id: str
    timestamp: datetime
    account_id: Optional[str]  # None for system alerts
    alert_type: Literal["trade", "rule_warning", "rule_violation", "system", "error"]
    severity: Literal["info", "warning", "error", "critical"]
    title: str
    message: str
    data: dict
    requires_action: bool
```

---

## Appendix: SQL Migration Script

```sql
-- migrations/001_initial_schema.sql

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create all tables
-- (See individual table definitions above)

-- Create hypertables
SELECT create_hypertable('candles', 'time');
SELECT create_hypertable('rule_violations', 'timestamp');
SELECT create_hypertable('audit_logs', 'timestamp');

-- Insert default data
INSERT INTO prop_firms (id, name, rules_preset, website) VALUES
  ('ftmo', 'FTMO', 'ftmo', 'https://ftmo.com'),
  ('the5ers', 'The5ers', 'the5ers', 'https://the5ers.com'),
  ('wmt', 'WeMasterTrade', 'wmt', 'https://wemastertrade.com');

INSERT INTO symbols (symbol, display_name, category, pip_size, contract_size) VALUES
  ('XAUUSD', 'Gold', 'metals', 0.01, 100),
  ('EURUSD', 'Euro/USD', 'forex', 0.0001, 100000),
  ('GBPUSD', 'GBP/USD', 'forex', 0.0001, 100000),
  ('BTCUSD', 'Bitcoin/USD', 'crypto', 0.01, 1);
```

---

**Document Status:** Draft
**Next Steps:** Review with BMad, finalize schema design, create SQL migrations
