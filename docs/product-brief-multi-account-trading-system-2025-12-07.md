# Product Brief: Multi-Account Trading System

**Version:** 3.0
**Date:** 2025-12-07
**Author:** Business Analyst Mary (with BMad)

---

## Executive Summary

An event-driven automated trading system designed for **multi-account, multi-prop-firm trading** with a **pluggable rule engine**. The system supports running multiple MT5 accounts simultaneously, each with its own strategy and compliance rules - whether using built-in prop firm presets (FTMO, The5ers, WeMasterTrade) or fully custom user-defined rules.

---

## Problem Statement

### Current Challenges

1. **Single Account Limitation**: Existing trading systems typically support only one account, requiring multiple instances for multi-account trading
2. **Rigid Compliance Rules**: FTMO-specific rules are often hardcoded, making it difficult to adapt for other prop firms or personal accounts
3. **No Custom Rules**: Traders cannot define their own risk management rules beyond what the system provides
4. **Shared Risk**: When one account has issues, it can affect others in the same system

### Target Users

| User Type | Description | Needs |
|-----------|-------------|-------|
| **Prop Firm Traders** | Trade with FTMO, The5ers, WMT, etc. | Preset compliance rules, multi-account support |
| **Personal Traders** | Trade with own capital | Custom risk rules, flexible configuration |
| **Hybrid Traders** | Both prop firm and personal accounts | Mix of presets and custom rules |

---

## Solution Overview

### Core Capabilities

| Capability | Description |
|------------|-------------|
| **Multi-Account** | Run multiple MT5 accounts simultaneously |
| **Independent Strategies** | Each account runs its own strategy with custom parameters |
| **Pluggable Rule Engine** | Built-in presets + fully customizable YAML rules |
| **Risk Isolation** | Account-level risk management, failures don't cascade |
| **Signal Filtering** | Each account filters signals independently |

### Supported Account Types

| Type | Rule Source | Examples |
|------|-------------|----------|
| **Prop Firm** | Built-in presets | FTMO, The5ers, WeMasterTrade |
| **Personal** | Custom YAML file | User-defined rules |
| **Demo/Test** | Optional/None | Backtesting, paper trading |

---

## Key Features

### 1. Multi-Account Management

- **Simultaneous Execution**: Run 2, 5, 10+ accounts at the same time
- **Independent Connections**: Each account has its own MT5 connection
- **Status Management**: Active, Paused, Stopped states per account
- **Account Lifecycle**: Add, configure, start, stop, remove accounts dynamically

### 2. Pluggable Rule Engine

#### Built-in Presets

| Prop Firm | Key Rules |
|-----------|-----------|
| **FTMO** | 5% daily loss, 10% max drawdown, 10% profit target, min 4 trading days |
| **The5ers** | 4% daily loss, 6% max drawdown, scaling plan rules |
| **WeMasterTrade** | 5% daily loss, 10% max drawdown, specific trading hours |

#### Custom Rule Types

| Category | Rule Types |
|----------|------------|
| **Drawdown** | Daily loss limit, Max drawdown, Trailing drawdown |
| **Time-based** | Trading hours, Sessions, Days of week, News blackout |
| **Position** | Max lots, Max positions, Max per symbol, Total exposure |
| **Symbol** | Allowed symbols, Blocked symbols |
| **Frequency** | Max trades/day, Min interval between trades, Max trades/hour |

#### Rule Configuration Example

```yaml
# Custom rules for personal account
name: "My Trading Rules"
rules:
  - type: daily_loss_limit
    threshold_percent: 2.0
    action: "block_trading"

  - type: trading_hours
    start: "08:00"
    end: "20:00"
    timezone: "UTC"

  - type: max_open_positions
    limit: 3

  - type: allowed_symbols
    symbols: ["EURUSD", "XAUUSD"]
```

### 3. Per-Account Strategy Assignment

- Each account can run a different strategy
- Strategy parameters configurable per account
- Signal filtering based on account configuration
- Example: Account 1 runs MA Crossover on GOLD, Account 2 runs Breakout on BTC

### 4. Risk Isolation

- **Independent Risk Tracking**: Each account tracks its own drawdown, P&L
- **Isolated Failures**: If one account breaches rules, only that account stops
- **No Cross-Contamination**: Account A's losses don't affect Account B's limits
- **Per-Account Alerts**: Telegram notifications specify which account

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Trading Engine (Python)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Account Manager                          │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │ │
│  │  │ FTMO Acc │  │ 5ers Acc │  │ WMT Acc  │  │Custom Acc│   │ │
│  │  │Strategy A│  │Strategy B│  │Strategy C│  │Strategy D│   │ │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │ │
│  └───────┼─────────────┼─────────────┼─────────────┼─────────┘ │
│          │             │             │             │            │
│          ▼             ▼             ▼             ▼            │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Rule Engine                              │ │
│  │  ┌─────────────────────┐  ┌─────────────────────┐          │ │
│  │  │   Preset Loader     │  │   Custom Loader     │          │ │
│  │  │ (FTMO, 5ers, WMT)   │  │   (YAML files)      │          │ │
│  │  └─────────────────────┘  └─────────────────────┘          │ │
│  │                     │                                       │ │
│  │  ┌──────────────────┴──────────────────────────────────┐   │ │
│  │  │ Rule Types: Drawdown | Time | Position | Symbol | Freq│   │ │
│  │  └─────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Signal Router                            │ │
│  │         (Filter & distribute signals per account)          │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MT5 Execution Layer                           │
│        (Multiple MT5 connections, one per account)               │
└─────────────────────────────────────────────────────────────────┘
```

---

## User Stories

### Epic 1: Multi-Account Management

| ID | Story | Priority |
|----|-------|----------|
| MA-1 | As a trader, I want to add multiple MT5 accounts so I can trade with different prop firms simultaneously | Must Have |
| MA-2 | As a trader, I want each account to have its own strategy so I can optimize for different market conditions | Must Have |
| MA-3 | As a trader, I want to pause/resume individual accounts without affecting others | Must Have |
| MA-4 | As a trader, I want to see the status of all accounts in one dashboard | Should Have |

### Epic 2: Pluggable Rule Engine

| ID | Story | Priority |
|----|-------|----------|
| RE-1 | As a trader, I want to select a prop firm preset (FTMO/5ers/WMT) so I don't have to configure rules manually | Must Have |
| RE-2 | As a trader, I want to create custom rules via YAML so I can implement my own risk management | Must Have |
| RE-3 | As a trader, I want rules to be validated in real-time (every bar) so I never breach compliance | Must Have |
| RE-4 | As a trader, I want to receive warnings before hitting limits so I can adjust my trading | Should Have |

### Epic 3: Risk Isolation

| ID | Story | Priority |
|----|-------|----------|
| RI-1 | As a trader, I want account failures to be isolated so one account's issues don't affect others | Must Have |
| RI-2 | As a trader, I want per-account P&L tracking so I can monitor each account independently | Must Have |
| RI-3 | As a trader, I want per-account alerts so I know which account triggered a warning | Must Have |

### Epic 4: Signal Routing

| ID | Story | Priority |
|----|-------|----------|
| SR-1 | As a trader, I want each account to filter signals by symbol so Account A trades GOLD and Account B trades BTC | Must Have |
| SR-2 | As a trader, I want to filter signals by session so I only trade during specific hours | Should Have |
| SR-3 | As a trader, I want to filter by spread so I skip signals during high spread periods | Should Have |

---

## Technical Requirements

### Platform & Broker Support

| Requirement | Details |
|-------------|---------|
| Trading Platform | MetaTrader 5 (MT5) |
| Connection | ZeroMQ bridge (existing infrastructure) |
| Prop Firms | FTMO, The5ers, WeMasterTrade (all use MT5) |
| Personal Brokers | Any MT5 broker (ICMarkets, Pepperstone, etc.) |

### Data Storage

| Component | Technology | Purpose |
|-----------|------------|---------|
| Hot Cache | Redis 7.2+ | Real-time state, per-account snapshots |
| Historical | TimescaleDB (PostgreSQL 16+) | Trades, audit logs, compliance history |
| Configuration | YAML files + Database | Account configs, rule definitions |

### Performance

| Metric | Target |
|--------|--------|
| Accounts | **5 simultaneous** (max) |
| Latency | 100-500ms per signal |
| Rule Validation | < 50ms per check |
| Memory | < 400MB per account (~2GB total) |

### User Interface

| Interface | Purpose | Features |
|-----------|---------|----------|
| **CLI** | Configuration & Setup | Add/remove accounts, edit configs, start/stop engine |
| **Telegram Bot** | Monitoring & Control | Status overview, pause/resume accounts, alerts, emergency stop |

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Multi-Account Reliability** | 99.9% uptime per account | Account availability monitoring |
| **Rule Accuracy** | 0 false negatives | No missed violations |
| **Isolation Effectiveness** | 100% isolation | Failures contained to single account |
| **Configuration Flexibility** | 5+ rule types | Customizable via YAML |

---

## MVP Scope

### Phase 1: Core Multi-Account (Week 1-4)

- [ ] Account Manager with add/remove/start/stop
- [ ] Per-account MT5 connections
- [ ] Basic signal routing (by symbol)
- [ ] Per-account state persistence

### Phase 2: Rule Engine (Week 5-8)

- [ ] Rule engine framework
- [ ] FTMO preset
- [ ] The5ers preset
- [ ] WeMasterTrade preset
- [ ] Custom YAML rule loader
- [ ] Core rule types (drawdown, time, position)

### Phase 3: Advanced Features (Week 9-12)

- [ ] Advanced rule types (frequency, symbol)
- [ ] Per-account alerts via Telegram
- [ ] Account dashboard/status overview
- [ ] Rule violation history and reporting

---

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| MT5 connection limits | High | Medium | Test with target account count, implement connection pooling |
| Rule engine performance | Medium | Low | Benchmark rule validation, optimize hot path |
| Configuration complexity | Medium | Medium | Provide clear examples, validation on load |
| Prop firm rule changes | Medium | Medium | Version presets, easy to update |

---

## Design Decisions

### 1. Account Limits: **5 Accounts Maximum**

- **Decision**: Support up to 5 simultaneous accounts
- **Rationale**: Sufficient for 2-3 prop firms + 1-2 personal accounts
- **Resource**: ~2GB RAM estimated
- **Future**: Can increase if needed via config change

### 2. UI Requirements: **CLI + Telegram**

- **Decision**: Command line tools + Telegram bot for status/control
- **Rationale**:
  - CLI for configuration and setup
  - Telegram for real-time monitoring and quick actions
  - No web dashboard in MVP (can add later)
- **Telegram Features**:
  - View all accounts status
  - Pause/resume individual accounts
  - Receive per-account alerts
  - Emergency stop all

### 3. Rule Inheritance: **Copy from Preset**

- **Decision**: Custom accounts copy preset rules, then modify (no live inheritance)
- **Rationale**: Simpler implementation, no hidden dependencies
- **Workflow**:
  1. User runs: `copy-preset ftmo my_rules.yaml`
  2. System creates `my_rules.yaml` with all FTMO rules
  3. User edits the file to add/remove/modify rules
  4. Changes are independent from original preset
- **Example**:
  ```yaml
  # my_rules.yaml (copied from FTMO, then modified)
  name: "My Rules (based on FTMO)"
  copied_from: "ftmo"  # For reference only
  rules:
    - type: daily_loss_limit
      threshold_percent: 3.0  # Changed from 5%
    # ... rest of rules
  ```

### 4. Hot Reload: **Require Restart**

- **Decision**: Configuration changes require engine restart
- **Rationale**:
  - Simpler implementation
  - Prevents mid-trade rule changes
  - Safer for compliance
- **Workflow**:
  1. Edit YAML config files
  2. Stop engine: `trading-engine stop`
  3. Start engine: `trading-engine start`
  4. New config applied
- **Future**: Can add hot reload for non-critical settings if needed

---

## Appendix: Configuration Examples

### Example: 3-Account Setup

```yaml
# accounts.yaml
accounts:
  # Prop Firm Account 1: FTMO Gold
  - id: "ftmo-gold-001"
    name: "FTMO Gold Challenge"
    type: "prop_firm"
    prop_firm: "ftmo"
    mt5:
      server: "FTMO-Demo"
      login: 12345678
      password_env: "FTMO_PASS"
    strategy: "ma_crossover"
    strategy_params:
      fast_period: 20
      slow_period: 50
    signal_filter:
      symbols: ["XAUUSD"]
    status: "active"

  # Prop Firm Account 2: The5ers BTC
  - id: "5ers-btc-001"
    name: "The5ers BTC"
    type: "prop_firm"
    prop_firm: "the5ers"
    mt5:
      server: "The5ers-Live"
      login: 87654321
      password_env: "5ERS_PASS"
    strategy: "breakout"
    strategy_params:
      lookback: 20
    signal_filter:
      symbols: ["BTCUSD"]
    status: "active"

  # Personal Account: Custom Rules
  - id: "personal-001"
    name: "My Personal Account"
    type: "custom"
    rules_file: "my_rules.yaml"
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

**Document Status:** Finalized
**Last Updated:** 2025-12-07
**Next Steps:** Create detailed Epics and Stories, begin implementation
