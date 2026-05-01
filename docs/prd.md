---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
inputDocuments:
  - docs/product-brief-multi-account-trading-system-2025-12-07.md
  - docs/architecture.md
workflowType: 'prd'
lastStep: 11
project_name: 'Multi-Account Trading System'
user_name: 'BMad'
date: '2025-12-07'
---

# Product Requirements Document - Multi-Account Trading System

**Author:** BMad
**Date:** 2025-12-07

## Executive Summary

An event-driven automated trading system designed for **multi-account, multi-prop-firm trading** with a **pluggable rule engine**. The system supports running multiple MT5 accounts simultaneously (up to 5), each with its own strategy and compliance rules - whether using built-in prop firm presets (FTMO, The5ers, WeMasterTrade) or fully custom user-defined YAML rules.

### Problem Statement

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

### What Makes This Special

- **Multi-Account Support**: Run 2-5 accounts simultaneously with completely independent strategies and MT5 connections
- **Pluggable Rule Engine**: Built-in prop firm presets + fully customizable YAML rules for any risk management scenario
- **Risk Isolation**: Account-level risk management ensures failures don't cascade - Account A's breach doesn't affect Account B
- **Polyglot Microservices**: Right language for each service - Go (I/O-bound), Rust (latency-critical), Python (trading logic with Nautilus Trader)
- **Backtest-Reality Alignment**: Same codebase for backtesting and live trading ensures consistent behavior

## Project Classification

**Technical Type:** Developer Tool (CLI-driven trading engine)
**Domain:** Fintech (automated trading, prop firm compliance)
**Complexity:** High

This is a high-complexity fintech project requiring:
- **Prop Firm Rule Accuracy**: Zero tolerance for compliance violations that could fail trader challenges
- **Real-time Performance**: Sub-second signal processing and order execution
- **State Recovery**: Crash recovery must preserve positions and compliance state
- **Audit Trail**: Complete logging for compliance verification and debugging

## Success Criteria

### User Success

| Success Indicator | Measurement | Target |
|-------------------|-------------|--------|
| **Challenge Pass Rate** | Traders pass prop firm challenges without system-caused violations | 100% (zero false negatives) |
| **Multi-Account Confidence** | Traders run 2-5 accounts simultaneously without manual intervention | Accounts operate independently 24/7 |
| **Configuration Autonomy** | Traders customize rules via YAML without developer assistance | < 30 min to create custom ruleset |
| **Risk Awareness** | Traders receive warnings before hitting limits | Alerts at 70%, 80%, 90% thresholds |

**User "Aha!" Moments:**
- First time seeing 3 accounts running different strategies on different prop firms simultaneously
- Receiving a "daily loss at 4.2%" warning and adjusting before breaching the 5% limit
- Copying FTMO preset, modifying 2 rules, and deploying custom config in minutes

### Business Success

| Timeframe | Success Metric | Target |
|-----------|----------------|--------|
| **MVP (3 months)** | Core multi-account system operational | 5 accounts running simultaneously |
| **Growth (6 months)** | Rule engine fully operational | 3 prop firm presets + custom YAML support |
| **Mature (12 months)** | Production stability | 99.9% uptime, zero compliance false negatives |

**Key Business Indicators:**
- Accounts managed without compliance breaches caused by system
- Time from configuration to live trading < 1 hour
- Recovery from crash with zero position discrepancy

### Technical Success

| Metric | Target | Rationale |
|--------|--------|-----------|
| **Signal Latency** | 100-500ms per signal | Sufficient for swing/position trading on 1m+ timeframes |
| **Rule Validation** | < 50ms per check | Real-time compliance without blocking trades |
| **Memory Footprint** | < 400MB per account | Support 5 accounts on 2GB RAM allocation |
| **State Recovery** | < 30 seconds | Crash recovery from Redis snapshot |
| **Position Reconciliation** | 100% accuracy | MT5 as source of truth, zero orphan positions |

### Measurable Outcomes

1. **Zero False Negatives**: No trade executed that should have been blocked by rules
2. **Account Isolation**: 100% - one account's failure never affects another
3. **Rule Coverage**: 5+ rule types (drawdown, time, position, symbol, frequency)
4. **Preset Accuracy**: FTMO, The5ers, WMT presets match official prop firm rules exactly
5. **Audit Completeness**: Every rule check logged with timestamp, values, and decision

## Product Scope

### MVP - Minimum Viable Product

**Phase 1: Core Multi-Account (Target: Week 1-4)**
- Account Manager with add/remove/start/stop lifecycle
- Per-account MT5 connections via ZeroMQ bridge
- Basic signal routing by symbol
- Per-account state persistence in Redis
- Crash recovery from snapshots

**Phase 2: Rule Engine (Target: Week 5-8)**
- Rule engine framework with pluggable architecture
- FTMO preset (5% daily, 10% max drawdown, 10% profit target, min 4 days)
- The5ers preset (4% daily, 6% max drawdown, scaling rules)
- WeMasterTrade preset (5% daily, 10% max drawdown, trading hours)
- Custom YAML rule loader
- Core rule types: drawdown, time-based, position limits

### Growth Features (Post-MVP)

**Phase 3: Advanced Features (Target: Week 9-12)**
- Advanced rule types (frequency limits, symbol restrictions)
- Per-account Telegram alerts with account identification
- Account dashboard/status overview via Telegram bot
- Rule violation history and compliance reporting
- Warning thresholds (70%, 80%, 90% of limits)

### Operational Hardening (Epic 10 — in progress, 2026-05-01)

Closes 10 architecture-review findings (D1–D10) gating live trading with capital.
Phase 1–4 shipped 2026-05-01; Phase 5 (legacy cleanup) gated by ops sign-off.

**Shipped capabilities (Phase 1–4):**
- `TradingEngine` god-object split → `RecoveryOrchestrator` + `LiveOrchestrator` + `EngineLifecycle` + `EngineConfig` DI container
- `AuditWriter` bounded queue — sync DB write before every `account.*` mutation (double-entry)
- Atomic expose-gate: Redis Lua `atomic_reserve/release` on every `validate_and_send` (race-condition fix)
- `LiveOrchestrator` partial: `LiveAccountSession` state machine, `RedisDataClient`, `ZmqExecutionClient`, orchestrator health surface (TradingNode wiring still backlog)
- Kill-switch `EmergencyStopHandler` — `emergency:stop` Redis → close all open positions → pause accounts
- News blackout rule + `EconomicCalendarService` (ForexFactory XML; Redis 26h TTL cache; fail-open fallback)
- `SpreadAwareFeeModel` — backtest spread parity per-firm (swap deferred)
- Alembic bootstrap — 6 raw migrations (005–010) ported to versioned revisions

**Remaining backlog (Phase 3 partial + Phase 5):**
- `TradingNode` per-account wiring + strategy registration + reload subscriber (10.5d/e2/f)
- Legacy `prop_firm` field + `prop_firms` table removal (10.12–10.14; gated by 10.11 ops audit)
- `.gitignore` compliance report files (10.15)

### Vision (Future)

- Web dashboard for multi-account monitoring
- Hot reload for non-critical configuration changes
- Additional prop firm presets (MFF, True Forex Funds, etc.)
- Strategy marketplace/sharing
- Backtesting with multi-account simulation
- Machine learning for optimal rule suggestions

## User Journeys

### Journey 1: Marcus Chen - The Multi-Prop-Firm Trader

Marcus is a 32-year-old professional trader who passed his first FTMO challenge six months ago. He's been profitable and recently qualified for challenges with The5ers and WeMasterTrade as well. His problem? He's running three separate MT5 instances on his Windows machine, each with different manual processes to track compliance. Last week, he almost breached FTMO's daily loss limit because he lost track of his aggregate positions across accounts.

One evening, after a close call where he hit 4.8% daily loss on FTMO, Marcus discovers the Multi-Account Trading System. He spends an hour configuring his three accounts in a single `accounts.yaml` file, selecting the appropriate prop firm presets for each. The next morning, instead of logging into three separate MT5 terminals and manually checking each dashboard, he starts the trading engine with a single command.

The breakthrough comes during a volatile gold session. His MA Crossover strategy on the FTMO account triggers a buy signal, but the rule engine blocks it - he's already at 4.2% daily loss and the position size would push him over the limit. Marcus receives a Telegram alert: "🟡 FTMO-Gold: Trade blocked - would exceed 5% daily limit (current: 4.2%)". Meanwhile, his The5ers BTC account continues trading normally, completely isolated from the FTMO restriction.

Three months later, Marcus has passed two more prop firm challenges and manages five accounts simultaneously. He hasn't had a single compliance breach caused by system oversight. His trading has become more confident because he trusts the system to protect him from himself.

### Journey 2: Sarah Williams - The Custom Rules Trader

Sarah is a 28-year-old personal trader who's been developing her own scalping strategy for EURUSD and GBPUSD. She doesn't trade with prop firms - she uses her own capital with ICMarkets. But she's disciplined and wants strict risk management: never more than 2% daily loss, maximum 2 open positions, and only trade during London/New York sessions.

She hears about the Multi-Account Trading System from Marcus (her trading mentor) and realizes she can use the custom YAML rules feature. Sarah runs `copy-preset ftmo my_rules.yaml` to get a starting template, then modifies it in her text editor:

```yaml
name: "Sarah's Conservative Rules"
rules:
  - type: daily_loss_limit
    threshold_percent: 2.0  # More conservative than FTMO's 5%
  - type: max_open_positions
    limit: 2
  - type: trading_sessions
    allowed: ["london", "new_york"]
```

The setup takes 20 minutes. The "aha!" moment comes when she realizes she can iterate on her rules - adding a `max_spread` filter to skip signals when spread exceeds 1.5 pips, then a `max_trades_per_day` limit of 5 to prevent overtrading during emotional sessions.

Six months later, Sarah's equity curve is the smoothest it's ever been. She attributes it to the rule engine preventing her from making impulsive trades during Asian session (when she used to lose money from boredom trading).

### Journey 3: Alex Rivera - The Crisis Recovery

Alex is running four accounts - two FTMO, one The5ers, one personal. It's Thursday afternoon when his VPS crashes unexpectedly during a high-volatility news event. He has open positions on three accounts.

When the VPS comes back online 3 minutes later, Alex's heart is racing. He starts the trading engine and watches the logs. The crash recovery sequence begins: Redis snapshots are loaded for each account, MT5 connections are re-established, and position reconciliation runs. The system detects his open positions match what's recorded in the snapshots.

The Telegram bot sends: "🔵 System recovered. 4 accounts online. 3 open positions reconciled. 0 discrepancies."

Alex breathes. The rule engine resumes monitoring, and his daily P&L tracking continues from where it left off. No duplicate orders were placed during the crash. No positions were orphaned. The audit log shows exactly what happened during the 3-minute outage.

This experience convinces Alex to recommend the system to his trading community Discord. The crash recovery feature alone is worth the setup effort.

### Journey 4: DevOps Dave - The System Administrator

Dave is a DevOps engineer who manages trading infrastructure for a small prop trading team. He's responsible for deploying, monitoring, and maintaining the Multi-Account Trading System for 3 traders, each running 2-3 accounts.

His morning starts with checking the Telegram bot status overview: all 8 accounts show "active", no overnight rule violations, system health shows all services green. He reviews the audit logs in TimescaleDB for any anomalies - nothing unusual.

When a new trader joins the team, Dave creates their account configurations, adds them to the Docker Compose environment, and deploys. The separation of concerns is clean: traders manage their strategy parameters and rule customizations, Dave manages infrastructure and monitoring.

The critical moment comes when FTMO updates their rules (reducing daily loss limit from 5% to 4% for a new challenge phase). Dave updates the `ftmo.yaml` preset, runs the validation tests, and deploys during market close. All FTMO accounts automatically pick up the new rules on restart. No trader intervention required.

### Journey 5: Emergency Stop - The Market Flash Crash

It's a Monday morning and gold gaps down 3% on unexpected news. Multiple accounts are in drawdown territory. The lead trader, Marcus, sees the chaos unfolding and types `/stop_all` in Telegram.

Within 500ms:
- All signal processing stops
- All pending orders are cancelled
- All accounts are set to "paused" state
- Existing positions remain open (manual close if needed)

Telegram responds: "🔴 EMERGENCY STOP: 5 accounts paused, 3 pending orders cancelled, 7 open positions preserved."

Marcus and the team assess the situation. Thirty minutes later, volatility subsides. Marcus types `/resume_all` and confirms. The system resumes normal operation, and the rule engine continues protecting each account's compliance limits.

This scenario validates that the system prioritizes trader safety over automation convenience.

### Journey Requirements Summary

| Journey | Capabilities Revealed |
|---------|----------------------|
| **Marcus (Multi-Prop)** | Multi-account management, preset rules, signal routing, per-account alerts, risk isolation |
| **Sarah (Custom Rules)** | YAML rule configuration, copy-preset workflow, custom rule types, iterative refinement |
| **Alex (Crisis Recovery)** | Crash recovery, Redis snapshots, position reconciliation, audit logging, state persistence |
| **Dave (DevOps)** | Docker deployment, centralized monitoring, preset updates, multi-user management |
| **Emergency Stop** | Telegram commands, emergency stop, account pausing, position preservation |

## Domain-Specific Requirements

### Fintech Compliance & Regulatory Overview

The Multi-Account Trading System operates in the automated trading / prop firm compliance domain. While not directly handling client funds or requiring broker licensing (traders use their own MT5 broker accounts), the system has critical compliance implications:

1. **Prop Firm Rule Accuracy**: Incorrect rule implementation could cause traders to fail challenges, resulting in financial loss
2. **Trade Execution Reliability**: System failures during live trading could result in unintended positions or missed exits
3. **Data Integrity**: Audit trails must be complete and tamper-evident for compliance verification
4. **Risk Management**: The system is a risk management tool - failures have direct financial consequences

### Key Domain Concerns

| Concern | Applicability | Approach |
|---------|---------------|----------|
| **Regional Compliance** | Low - traders responsible for their broker compliance | System agnostic to broker regulations |
| **Security Standards** | Medium - credential management, API security | Env-based secrets, no plaintext passwords |
| **Audit Requirements** | High - complete trade and rule check history | TimescaleDB audit logs, immutable records |
| **Fraud Prevention** | Low - single-user system, no external access | Internal use only, no fraud vector |
| **Data Protection** | Medium - trading credentials and performance data | Local storage, user-controlled deployment |

### Compliance Requirements

#### Prop Firm Rule Compliance

| Requirement | Implementation | Verification |
|-------------|----------------|--------------|
| **FTMO Rules** | Built-in preset matching official FTMO documentation | Manual verification against FTMO dashboard |
| **The5ers Rules** | Built-in preset matching official The5ers documentation | Manual verification against The5ers dashboard |
| **WeMasterTrade Rules** | Built-in preset matching official WMT documentation | Manual verification against WMT dashboard |
| **Rule Update Process** | Version-controlled presets, documented changes | Changelog per preset update |

#### Audit Trail Requirements

| Audit Item | Storage | Retention |
|------------|---------|-----------|
| **Rule Checks** | TimescaleDB `audit_logs` table | 90 days minimum |
| **Trade Executions** | TimescaleDB `trades` table | Indefinite |
| **Rule Violations** | TimescaleDB `rule_violations` table | Indefinite |
| **Account Snapshots** | Redis (hot) + TimescaleDB (cold) | 7 days (cold) |
| **System Events** | Structured JSON logs | 30 days |

### Industry Standards & Best Practices

| Standard | Relevance | Implementation |
|----------|-----------|----------------|
| **Position Reconciliation** | Critical - MT5 as source of truth | Compare snapshot vs MT5 on recovery |
| **Fail-Safe Design** | Critical - system should fail closed | Block trades when uncertain, not allow |
| **Idempotent Operations** | Critical - no duplicate orders | Order ID tracking, confirmation required |
| **Graceful Degradation** | Important - partial operation vs total failure | Account isolation, per-service health |

### Required Expertise & Validation

| Expertise Area | Need | Source |
|----------------|------|--------|
| **Prop Firm Rules** | Exact rule documentation for each supported firm | Official prop firm websites, challenge documentation |
| **MT5 Integration** | ZeroMQ bridge implementation, order execution | MT5 documentation, existing tv-api patterns |
| **Risk Calculation** | Drawdown calculation methods, P&L tracking | Industry-standard formulas, prop firm definitions |
| **Trading Sessions** | Session time definitions (London, NY, Tokyo, Sydney) | Standard forex market hours |

### Implementation Considerations

1. **Rule Accuracy is Non-Negotiable**: A single false negative (allowing a trade that should be blocked) could fail a trader's challenge. The rule engine must be conservative - when in doubt, block.

2. **Prop Firm Rule Updates**: Prop firms occasionally update their rules. The system needs:
   - Version-controlled presets
   - Clear update process
   - Notification mechanism for preset changes

3. **Testing Strategy**:
   - Unit tests for each rule type with edge cases
   - Integration tests with realistic market scenarios
   - Manual verification against prop firm dashboards before release

4. **Liability Disclaimer**: System should clearly document:
   - User responsibility for verifying rule accuracy
   - No guarantee of challenge pass
   - User must validate preset rules against current prop firm documentation

## Innovation & Novel Patterns

### Detected Innovation Areas

| Innovation | Description | Novelty Level |
|------------|-------------|---------------|
| **Pluggable Rule Engine** | Combining built-in prop firm presets with fully customizable YAML rules in a single framework | High - most trading systems have hardcoded or no compliance rules |
| **Multi-Account Risk Isolation** | Complete isolation of risk between accounts - one breach doesn't affect others | Medium-High - existing multi-account tools typically share risk state |
| **Polyglot Trading Architecture** | Go (I/O), Rust (latency-critical), Python (trading logic) - right language per service | Medium - novel for trading systems, proven pattern in web services |
| **Copy-and-Modify Presets** | `copy-preset ftmo my_rules.yaml` workflow for rule customization | Medium - makes compliance rules accessible to non-developers |

### Market Context & Competitive Landscape

**Current Market Solutions:**

| Solution Type | Limitation | Our Approach |
|---------------|------------|--------------|
| **MT5 Native** | Single account, manual compliance tracking | Multi-account with automated rule engine |
| **Prop Firm Dashboards** | View-only, no automation, no custom rules | Proactive blocking, custom rules, alerts |
| **Trading Bots** | Strategy-focused, no compliance, single account | Compliance-first, multi-account, strategy-agnostic |
| **Risk Management Tools** | Generic, not prop-firm-aware | Prop firm presets, specific rule types |

**Gap Being Addressed:**
No existing solution combines:
1. Multi-account management (2-5 accounts simultaneously)
2. Prop firm-specific compliance presets
3. Fully customizable rule engine (YAML)
4. Per-account risk isolation
5. Unified monitoring via Telegram

### Validation Approach

| Innovation | Validation Method | Success Criteria |
|------------|-------------------|------------------|
| **Pluggable Rule Engine** | Unit tests per rule type, integration tests with market scenarios | 100% of FTMO/5ers/WMT rules pass verification against official docs |
| **Risk Isolation** | Chaos testing - force breach on Account A, verify Account B unaffected | Zero cross-account impact in all test scenarios |
| **Polyglot Architecture** | Latency benchmarks per service, memory profiling | Bridge < 1ms, engine < 50ms rule check, < 400MB per account |
| **Preset Workflow** | User testing - can trader create custom rules in < 30 min? | 90% of test users succeed without developer help |

### Risk Mitigation

| Innovation Risk | Mitigation Strategy | Fallback |
|-----------------|---------------------|----------|
| **Rule Engine Complexity** | Start with core 5 rule types, add incrementally | Manual rule checking if engine fails |
| **Multi-Account Performance** | Benchmark at 5 accounts, optimize bottlenecks | Reduce to 3 accounts if memory constrained |
| **Polyglot Maintenance** | Clear service boundaries, independent deployment | Consolidate to Python-only if team expertise limited |
| **Preset Accuracy** | Version control, changelog, manual verification | User override, custom rules always available |

## Developer Tool Specific Requirements

### Project-Type Overview

The Multi-Account Trading System is a **CLI-driven developer tool** for traders who are comfortable with:
- YAML configuration files
- Command-line interfaces
- Docker deployment
- Environment variable management

This is not a consumer product with GUI wizards - it's a power-user tool that prioritizes flexibility and control over ease of use.

### Technical Architecture Considerations

#### Language & Runtime Matrix

| Service | Language | Runtime | Package Manager |
|---------|----------|---------|-----------------|
| **tv-api** | Go 1.21+ | Native binary | go mod |
| **mt5-bridge** | Rust 1.75+ | Native binary | cargo |
| **trading-engine** | Python 3.11+ | Python interpreter | uv |
| **notification** | Go 1.21+ | Native binary | go mod |

#### Installation Methods

| Method | Target User | Prerequisites |
|--------|-------------|---------------|
| **Docker Compose** (Primary) | All users | Docker 24+, Docker Compose 2.x |
| **Local Development** | Contributors | Go, Rust, Python, uv installed |
| **VPS Deployment** | Production | Ubuntu 22.04+, Docker, SSH access |

#### CLI Command Surface

**Trading Engine CLI:**
```bash
# Account management
trading-engine accounts list
trading-engine accounts add --config account.yaml
trading-engine accounts remove <account_id>
trading-engine accounts start <account_id>
trading-engine accounts stop <account_id>
trading-engine accounts status [account_id]

# Rule management
trading-engine rules list-presets
trading-engine rules copy-preset <preset> <output.yaml>
trading-engine rules validate <rules.yaml>

# Engine control
trading-engine start
trading-engine stop
trading-engine status
trading-engine logs [--follow] [--account <id>]
```

**Docker Compose Commands:**
```bash
# Infrastructure
make infra-up          # Start Redis + TimescaleDB
make infra-down        # Stop infrastructure

# Services
make build             # Build all service images
make up                # Start all services
make down              # Stop all services
make logs              # View logs
make restart           # Restart all services

# Development
make test              # Run all tests
make lint              # Run linters
make build-<service>   # Build specific service
```

### Configuration File Specifications

#### accounts.yaml Structure

```yaml
accounts:
  - id: string           # Unique account identifier (required)
    name: string         # Human-readable name (required)
    type: enum           # "prop_firm" | "custom" | "demo" (required)
    prop_firm: string    # "ftmo" | "the5ers" | "wmt" (if type=prop_firm)
    rules_file: string   # Path to custom YAML (if type=custom)
    mt5:
      server: string     # MT5 server name (required)
      login: integer     # MT5 login number (required)
      password_env: string  # Env var name for password (required)
    strategy: string     # Strategy name (required)
    strategy_params: object  # Strategy-specific parameters
    signal_filter:
      symbols: string[]  # Allowed symbols
      sessions: string[] # Allowed sessions
      max_spread_pips: number  # Max spread filter
    status: enum         # "active" | "paused" | "stopped"
```

#### Custom Rules YAML Structure

```yaml
name: string            # Rule set name (required)
version: string         # Version identifier
description: string     # Human-readable description
copied_from: string     # Reference preset (if copied)

rules:
  - type: enum          # Rule type (required)
    # Type-specific parameters vary per rule type
    action: enum        # "block_trading" | "skip_signal" | "warn" | "notify"
    warning_at: number[] # Percentage thresholds for warnings
```

### Documentation Requirements

| Document | Purpose | Location |
|----------|---------|----------|
| **README.md** | Quick start, overview | Project root |
| **INSTALL.md** | Detailed installation | docs/ |
| **CONFIGURATION.md** | All config options | docs/ |
| **RULES.md** | Rule types reference | docs/ |
| **PRESETS.md** | Prop firm preset docs | docs/ |
| **API.md** | Internal API reference | docs/ |
| **TROUBLESHOOTING.md** | Common issues | docs/ |

### Code Examples to Include

1. **Basic 3-Account Setup** - FTMO + The5ers + Personal
2. **Custom Rules Creation** - Copy preset and modify
3. **Docker Deployment** - Full production setup
4. **Telegram Bot Setup** - Notification configuration
5. **Strategy Integration** - Adding custom strategy
6. **Backup & Recovery** - State persistence

### Implementation Considerations

#### Developer Experience Priorities

1. **Clear Error Messages**: Every failure should explain what went wrong and how to fix it
2. **Validation on Load**: Config files validated before engine starts, not at runtime
3. **Dry Run Mode**: `trading-engine start --dry-run` to validate without executing
4. **Verbose Logging**: `--verbose` flag for debugging
5. **Configuration Dump**: `trading-engine config dump` to show resolved configuration

#### Backward Compatibility

- Config file format versioned in frontmatter
- Migration scripts for breaking changes
- Deprecation warnings before removal

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach:** Problem-Solving MVP - Solve the core multi-account compliance problem with minimal but reliable features.

**Rationale:**
- Traders need the compliance protection immediately - a partial solution is better than manual tracking
- Rule engine accuracy is non-negotiable; better to have fewer rule types that work perfectly
- Multi-account isolation is the unique value proposition - must work from Day 1

**Resource Requirements:**
- 1 senior developer with Go/Rust/Python experience
- Existing tv-api service as foundation
- 2-3 month development timeline for Phase 1

### MVP Feature Set (Phase 1)

**Core User Journeys Supported:**
1. ✅ Marcus (Multi-Prop) - Run 3+ accounts simultaneously with preset rules
2. ✅ Alex (Crisis Recovery) - Crash recovery with position reconciliation
3. ⚠️ Sarah (Custom Rules) - Basic custom rules (limited rule types)
4. ❌ Dave (DevOps) - Deferred to Phase 2 (single-user first)
5. ✅ Emergency Stop - Critical safety feature

**Must-Have Capabilities (Phase 1):**

| Capability | Rationale | Complexity |
|------------|-----------|------------|
| Account Manager | Core feature - add/remove/start/stop accounts | Medium |
| Per-Account MT5 Connections | Required for multi-account | High |
| FTMO Preset | Most common prop firm | Medium |
| Daily Loss Limit Rule | Most critical compliance rule | Low |
| Max Drawdown Rule | Second most critical rule | Low |
| Basic Signal Routing | Route by symbol filter | Medium |
| Redis State Snapshots | Required for crash recovery | Medium |
| Position Reconciliation | Safety-critical | High |
| Emergency Stop (Telegram) | Safety-critical | Low |

**Explicitly Deferred from MVP:**
- The5ers and WMT presets (Phase 2)
- Custom YAML rule loader (Phase 2)
- Advanced rule types (frequency, sessions) (Phase 2)
- Account dashboard overview (Phase 2)
- Multi-user support (Phase 3)

### Post-MVP Features

**Phase 2: Rule Engine Completion (Month 3-4)**

| Feature | User Journey | Priority |
|---------|--------------|----------|
| The5ers Preset | Marcus, hybrid traders | High |
| WeMasterTrade Preset | Marcus, hybrid traders | High |
| Custom YAML Loader | Sarah (Custom Rules) | High |
| Trading Hours Rule | Sarah, all users | Medium |
| Max Positions Rule | Sarah, all users | Medium |
| Trading Sessions Rule | Sarah, all users | Medium |
| Per-Account Telegram Alerts | All users | Medium |
| Rule Violation History | All users | Low |

**Phase 3: Advanced Features (Month 5-6)**

| Feature | User Journey | Priority |
|---------|--------------|----------|
| Account Status Dashboard | Dave (DevOps) | Medium |
| Warning Thresholds (70/80/90%) | All users | Medium |
| Symbol Restriction Rules | Sarah | Low |
| Frequency Limit Rules | Sarah | Low |
| Hot Reload (non-critical config) | Dave | Low |
| Compliance Reporting | Dave | Low |

### Risk Mitigation Strategy

**Technical Risks:**

| Risk | Impact | Mitigation |
|------|--------|------------|
| MT5 connection limits | High | Test with 5 accounts early; implement connection pooling if needed |
| Rule engine performance | Medium | Benchmark rule validation; optimize only if >50ms |
| Polyglot complexity | Medium | Clear service boundaries; comprehensive documentation |
| Crash recovery accuracy | High | Extensive testing; MT5 as source of truth |

**Market Risks:**

| Risk | Mitigation |
|------|------------|
| Prop firms change rules | Version-controlled presets; easy update process |
| Users don't adopt CLI tool | Clear documentation; example configurations |
| Competition emerges | Focus on rule accuracy and multi-account isolation |

**Resource Risks:**

| Risk | Contingency |
|------|-------------|
| Solo developer unavailable | Document everything; modular architecture |
| Development takes longer | Reduce Phase 1 to FTMO-only; defer other presets |
| Budget constraints | Docker-only deployment; skip VPS-specific features |

## Functional Requirements

### Account Management

- **FR1**: Trader can add a new trading account by providing MT5 credentials and account configuration
- **FR2**: Trader can remove an existing trading account from the system
- **FR3**: Trader can start an individual account to begin trading operations
- **FR4**: Trader can stop an individual account to pause trading operations
- **FR5**: Trader can view the status of all configured accounts (active, paused, stopped, error)
- **FR6**: Trader can configure each account with a specific trading strategy and parameters
- **FR7**: Trader can assign a prop firm preset or custom rule set to each account
- **FR8**: System can manage up to 5 simultaneous trading accounts

### Rule Engine

- **FR9**: System can load and apply built-in prop firm rule presets (FTMO, The5ers, WeMasterTrade)
- **FR10**: Trader can create custom rules by copying a preset and modifying it
- **FR11**: System can validate rule configurations before applying them
- **FR12**: System can evaluate rules in real-time (every bar) for each account independently
- **FR13**: System can block trade execution when a rule would be violated
- **FR14**: System can track daily P&L for each account against daily loss limits
- **FR15**: System can track total drawdown for each account against max drawdown limits
- **FR16**: System can enforce trading hours restrictions per account
- **FR17**: System can enforce position size limits per account
- **FR18**: System can log every rule check with timestamp, values, and decision

### Signal Routing

- **FR19**: System can receive trading signals from strategies
- **FR20**: System can route signals to appropriate accounts based on symbol filter
- **FR21**: System can filter signals based on account-specific criteria (spread, session)
- **FR22**: Trader can configure which symbols each account is allowed to trade

### Trade Execution

- **FR23**: System can send order commands to MT5 via ZeroMQ bridge
- **FR24**: System can receive order execution confirmations from MT5
- **FR25**: System can track order status (pending, filled, rejected, cancelled)
- **FR26**: System can record trade execution details (entry price, slippage, fill time)
- **FR27**: System can maintain independent MT5 connections per account

### Risk Isolation

- **FR28**: System can isolate risk state between accounts (one account's breach doesn't affect others)
- **FR29**: System can continue operating unaffected accounts when one account is paused or stopped
- **FR30**: System can track per-account equity, balance, and drawdown independently

### State Management & Recovery

- **FR31**: System can persist account state to Redis every 5 seconds
- **FR32**: System can recover account state from Redis snapshot after crash
- **FR33**: System can reconcile positions with MT5 after recovery
- **FR34**: System can detect and log discrepancies between snapshot and MT5 positions
- **FR35**: System can resume trading operations after successful recovery

### Notifications & Alerts

- **FR36**: Trader can receive Telegram notifications for trade executions
- **FR37**: Trader can receive Telegram warnings when approaching rule limits
- **FR38**: Trader can receive Telegram alerts when rules are violated
- **FR39**: Trader can view account status overview via Telegram bot
- **FR40**: Trader can trigger emergency stop for all accounts via Telegram command
- **FR41**: Trader can pause/resume individual accounts via Telegram commands

### Audit & Compliance

- **FR42**: System can maintain complete audit trail of all rule checks in TimescaleDB
- **FR43**: System can record all trade executions with full context per account
- **FR44**: System can track rule violations with violation details and context
- **FR45**: System can store daily account snapshots for compliance verification

### Configuration Management

- **FR46**: Trader can configure accounts via YAML configuration file
- **FR47**: Trader can configure custom rules via YAML rule files
- **FR48**: System can validate configuration files before engine start
- **FR49**: Trader can view resolved configuration via CLI command

### System Operations

- **FR50**: Trader can start the trading engine via CLI command
- **FR51**: Trader can stop the trading engine gracefully via CLI command
- **FR52**: Trader can view engine status and health via CLI command
- **FR53**: Trader can view logs filtered by account via CLI command
- **FR54**: System can perform graceful shutdown preserving all state

## Non-Functional Requirements

### Performance

| Requirement | Target | Rationale |
|-------------|--------|-----------|
| **NFR1**: Signal processing latency | < 500ms end-to-end | Sufficient for swing/position trading on 1m+ timeframes |
| **NFR2**: Rule validation time | < 50ms per rule check | Must not block trade execution flow |
| **NFR3**: State snapshot frequency | Every 5 seconds | Balance between data safety and I/O overhead |
| **NFR4**: Crash recovery time | < 30 seconds | Minimize exposure during market hours |
| **NFR5**: Telegram notification delivery | < 2 seconds | Near real-time awareness for trader |
| **NFR6**: MT5 order execution round-trip | < 1 second | Broker-dependent but system shouldn't add delay |

### Reliability

| Requirement | Target | Rationale |
|-------------|--------|-----------|
| **NFR7**: System uptime per account | 99.9% during market hours | Trading cannot happen if system is down |
| **NFR8**: Zero false negatives | 100% rule accuracy | A missed violation could fail a prop firm challenge |
| **NFR9**: Position reconciliation accuracy | 100% match with MT5 | MT5 is source of truth for positions |
| **NFR10**: Graceful degradation | Per-account isolation | One account failure must not cascade |
| **NFR11**: Data persistence | Zero trade data loss | Complete audit trail required |

### Security

| Requirement | Implementation |
|-------------|----------------|
| **NFR12**: Credential storage | MT5 passwords stored in environment variables, never in config files |
| **NFR13**: Telegram bot token | Environment variable, not committed to repository |
| **NFR14**: Database credentials | Environment variables with restricted access |
| **NFR15**: Network isolation | All services on internal Docker network, minimal port exposure |
| **NFR16**: Audit log integrity | Append-only logs in TimescaleDB, no delete permissions |

### Scalability

| Requirement | Target | Rationale |
|-------------|--------|-----------|
| **NFR17**: Account capacity | 5 simultaneous accounts | Design limit per original brief |
| **NFR18**: Memory per account | < 400MB | Total system footprint ~2GB for 5 accounts |
| **NFR19**: Redis connection pooling | Shared pool across accounts | Efficient resource utilization |
| **NFR20**: Horizontal scaling | Not required | Single-node deployment sufficient for MVP |

### Maintainability

| Requirement | Implementation |
|-------------|----------------|
| **NFR21**: Service independence | No shared code between services | Independent deployment and versioning |
| **NFR22**: Configuration validation | All configs validated before engine start | Fail fast on misconfiguration |
| **NFR23**: Structured logging | JSON-formatted logs with correlation IDs | Easy debugging and log aggregation |
| **NFR24**: Error messages | Actionable error messages with suggested fixes | Developer-friendly troubleshooting |
| **NFR25**: Documentation | README, installation guide, configuration reference | Self-service onboarding |

### Integration

| Requirement | Target | Rationale |
|-------------|--------|-----------|
| **NFR26**: MT5 ZeroMQ protocol | Compatible with standard MT5 EA ZeroMQ | Leverage existing MT5 ecosystem |
| **NFR27**: Redis protocol | Redis 7.2+ compatible | Standard Redis commands and pub/sub |
| **NFR28**: PostgreSQL protocol | PostgreSQL 16+ / TimescaleDB | Standard SQL with time-series extensions |
| **NFR29**: Telegram Bot API | Official Telegram Bot API | Standard bot commands and messaging |

### Observability

| Requirement | Implementation |
|-------------|----------------|
| **NFR30**: Health endpoints | Each service exposes health check | Container orchestration integration |
| **NFR31**: Service heartbeats | 30-second heartbeat to Redis | Detect service failures quickly |
| **NFR32**: Account health tracking | Per-account connection status in Redis | Quick identification of account issues |
| **NFR33**: Audit trail queryability | TimescaleDB indexes on account, timestamp, rule | Efficient compliance queries |

