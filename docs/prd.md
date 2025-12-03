# FTMO Trading System - Product Requirements Document

**Author:** BMad
**Date:** 2025-11-25
**Version:** 2.0 - Monorepo Architecture Update
**Last Updated:** 2025-12-03

---

## Executive Summary

An event-driven automated trading system engineered specifically for FTMO prop firm challenges, targeting high-frequency intraday trading on 1m/5m timeframes across GOLD, BTC, and EUR symbols. The system is architected as a **monorepo with 4 independent microservices**, leveraging a polyglot tech stack (Go, Rust, Python) optimized for each service's requirements, with Docker-managed infrastructure.

**Core Services:**
| Service | Language | Purpose |
|---------|----------|---------|
| tv-api | Go | TradingView WebSocket data collector |
| mt5-bridge | Rust | MT5 ZeroMQ bridge (latency-critical) |
| trading-engine | Python | Nautilus Trader core, strategies, FTMO compliance |
| notification | Go | Telegram alerts and notifications |

**Core Problem Solved:** FTMO challenges require consistent profitability within strict risk constraints (5% max daily loss, 10% max total drawdown), but traders face three critical challenges: (1) compliance complexity where a single rule violation terminates the account, (2) backtest-reality gap where strategies fail in live trading despite backtest success, and (3) architectural limitations of traditional polling-based systems that can't handle the multiple independent subsystems needed (strategy logic, risk management, compliance monitoring, execution).

**Solution Approach:** A monorepo with independent microservices, each optimized for its specific task. The trading-engine leverages Nautilus Trader's production-grade event-driven framework with custom FTMO rule engine. Services communicate via ZeroMQ (low-latency) and Redis Pub/Sub (event distribution). All infrastructure is Docker-managed for reproducible deployment. Focus on reliability and consistency over speed (100-500ms latency sufficient for 1m/5m timeframes).

### What Makes This Special

**Real-time Automated FTMO Compliance** - Unlike generic trading bots that focus on strategy alpha, this system treats FTMO rule compliance as a first-class architectural concern. The declarative YAML-based rule engine validates constraints after every bar (not end-of-day), provides preventive order blocking when approaching limits, and maintains comprehensive audit logging. Zero violations through architecture, not hope.

**Backtest-Reality Alignment** - Bridges the dangerous gap between backtest performance and live trading through realistic execution modeling (dynamic spreads, slippage simulation, latency delays) and walk-forward validation. The same codebase runs backtests and live trading (via Nautilus), eliminating divergence. Paper trading validation gates confirm model accuracy before risking capital.

**Professional Event-Driven Architecture** - Leverages Nautilus Trader's production-grade event architecture rather than building from scratch. Natural fit for trading domain (markets ARE event-driven), enabling clean separation of concerns: strategies react to market events, risk management reacts to position events, compliance monitoring reacts to trade events. Extensible to multiple strategies, symbols, and future prop firms without core changes.

**Pragmatic Infrastructure Leverage** - Integrates existing operational infrastructure (tv-api for TradingView data, ZeroMQ for MT5 execution, Redis/PostgreSQL for state) rather than rebuilding. Focuses development effort on the differentiating 20% (FTMO rules, realistic modeling, validation) while Nautilus handles 80% of trading infrastructure. 6-8 weeks to MVP versus 6+ months fully custom.

**Polyglot Microservices Architecture** - Each service uses the optimal language for its requirements: Go for I/O-bound services (tv-api, notification), Rust for latency-critical messaging (mt5-bridge), and Python for trading logic (trading-engine). Services are completely independent with no shared code, enabling independent development, testing, and deployment.

---

## Project Classification

**Technical Type:** developer_tool
**Domain:** fintech
**Complexity:** high

This is classified as a **Developer Tool** in the **Fintech** domain with **High Complexity**.

**Project Type Rationale:**
While this is a trading system, it's fundamentally a framework/tool for automated trading - similar to how Nautilus Trader itself is a developer tool. The primary user is a technical developer building trading infrastructure, the deliverable is a reusable system with adapters/extensions, and success is measured by engineering quality and extensibility as much as trading performance.

**Domain Complexity Rationale:**
The fintech domain carries high complexity due to regulatory considerations, strict compliance requirements, risk management criticality, and financial consequences of errors. While this MVP targets prop firm trading (not retail brokerage), FTMO rules function as a compliance framework, and the system must handle: real-time risk monitoring, trade audit trails, multi-layer compliance validation, and integration with regulated brokers (MT5). Future expansion could involve KYC/AML for multi-user platforms, additional prop firm regulations, and potential regional trading requirements.

### Domain Context

**Fintech Domain - High Complexity Considerations:**

The fintech domain introduces critical requirements that shape every aspect of this system:

**Regulatory & Compliance Landscape:**
- FTMO operates as a proprietary trading firm with specific challenge rules that function as contractual compliance requirements
- While not directly regulated like retail brokerages, prop firms maintain strict operational standards
- Integration with MT5 broker infrastructure requires adherence to broker API terms and rate limits
- Future multi-user expansion would trigger additional requirements (data privacy, potentially financial services regulations)

**Risk Management Criticality:**
- Financial systems have zero tolerance for certain error classes (duplicate orders, incorrect position sizing, rule violations)
- Real-time risk monitoring is not optional - it's a core functional requirement
- Audit trails must be comprehensive and immutable for post-trade analysis
- System failures during trading hours have immediate financial consequences

**Data Integrity & Security:**
- Trading data must be accurate, timestamped, and tamper-proof
- API keys, broker credentials, and trading strategies constitute sensitive intellectual property
- State consistency is critical (positions, account balance, P&L must always reconcile)
- Data retention requirements for tax reporting and performance analysis

**Integration Complexity:**
- Multiple external systems with different reliability profiles (TradingView API, MT5 broker, ZeroMQ)
- Each integration point is a potential failure mode requiring monitoring and fallback strategies
- Broker-specific quirks and limitations must be handled gracefully
- Market data feed interruptions must be detected and recovered from automatically

These domain characteristics inform architectural decisions (event-driven for reliability, comprehensive logging for audit, multi-layer risk validation) and drive many functional and non-functional requirements throughout this PRD.

### Reference Documents

**Product Brief:** `docs/product-brief-FTMO-Trading-System-2025-12-03.md` - Updated vision with monorepo architecture, polyglot tech stack, and service definitions

**Architecture Document:** `docs/architecture.md` - Comprehensive technical architecture including service details, inter-service communication, Docker configuration, and deployment

**Research Documents:** None - Domain knowledge sufficient for MVP based on expert-level user familiarity with FTMO requirements and trading systems

**Brownfield Documentation:** Existing tv-api service (Go) operational and will be moved to `/services/tv-api`

---

## System Architecture Overview

This section provides a high-level view of the system architecture. For detailed technical specifications, see `docs/architecture.md`.

### Monorepo Structure

```
Sandboxed/
├── services/                    # Independent microservices
│   ├── tv-api/                  # Go - TradingView data collector
│   ├── mt5-bridge/              # Rust - MT5 ZeroMQ bridge
│   ├── trading-engine/          # Python - Nautilus trading core
│   └── notification/            # Go - Telegram alerts
├── infra/                       # Infrastructure configs
│   ├── docker/                  # Docker Compose files
│   ├── redis/                   # Redis configuration
│   └── timescaledb/             # Database init scripts
├── configs/                     # Environment configs
│   ├── dev/                     # Development environment
│   └── prod/                    # Production environment
└── scripts/                     # Build/test utilities
```

### Service Communication

| From | To | Protocol | Purpose |
|------|-----|----------|---------|
| tv-api | Redis | Redis Protocol | Publish OHLCV candles |
| mt5-bridge | trading-engine | ZeroMQ PUB/SUB | Market data, orders |
| trading-engine | notification | Redis Pub/Sub | Alerts |
| notification | Telegram | HTTPS | User notifications |

### Technology Stack

| Component | Technology | Justification |
|-----------|------------|---------------|
| tv-api | Go 1.21+ | Existing service, excellent concurrency |
| mt5-bridge | Rust 1.75+ | Zero-latency ZeroMQ, no GC pauses |
| trading-engine | Python 3.11+ | Nautilus Trader requirement |
| notification | Go 1.21+ | Lightweight, efficient I/O |
| Infrastructure | Redis 7.2+, TimescaleDB PG16+, Docker | Proven, reliable stack |

---

## Success Criteria

Success for the FTMO Trading System is defined by **confidence through validation** rather than arbitrary metrics. This is a trading infrastructure project where success means eliminating unknowns and proving reliability before risking capital.

**Technical Validation Success:**
- Zero FTMO rule violations during 30+ days of paper trading (demonstrates compliance engine works flawlessly)
- Paper trading results within 20% of backtest metrics (proves execution model is realistic)
- System maintains 24-hour uptime without crashes during paper trading period (demonstrates reliability)
- Walk-forward analysis shows consistency across multiple time periods (proves strategy robustness)
- Data pipeline operates without gaps or quality issues (validates integration architecture)

**Trading Validation Success:**
- Confidence gate passed: Developer willing to risk FTMO challenge fee ($155-$1,080) based on validation results
- No critical unknowns or "hope this works" assumptions remaining
- Clear understanding of failure modes, edge cases, and limitations
- Slippage tracking confirms realistic execution model assumptions within 10%
- Minimum 20 trades executed in paper trading to validate execution quality across different market conditions

**Engineering Success:**
- Professional architecture that can be extended to multiple strategies, symbols, and prop firms
- Clean separation of concerns (strategy logic, risk management, compliance, execution)
- Comprehensive audit logging enables post-trade analysis and debugging
- Integration adapters successfully bridge existing infrastructure (tv-api, MT5 ZeroMQ) to Nautilus framework
- Codebase maintainable by single developer with clear extension points

**Learning Success (Secondary but Important):**
- Deep understanding of Nautilus Trader framework and event-driven trading architecture
- Validated approach to realistic backtesting that can be applied to future strategies
- Reusable FTMO compliance engine that works for Phase 1, Phase 2, and live funded accounts
- Architecture patterns learned applicable to broader trading system development

**NOT Success Criteria for MVP:**
- ❌ Specific profit targets or win rates (strategy alpha is iterative, not MVP gate)
- ❌ Sub-millisecond latency achievements (not needed for 1m/5m timeframes)
- ❌ Multiple strategy portfolio (MVP validates single strategy, portfolio is Phase 2)
- ❌ Visual dashboard or elaborate monitoring UI (Telegram alerts sufficient for MVP)

**Business Context:**
This is a personal infrastructure project, not a commercial product in MVP phase. Success means passing FTMO Phase 1 challenge and progressing to Phase 2, then funded account. Future business metrics (if evolving to multi-user platform) would include: number of traders using system, aggregate capital under management, and subscription revenue - but these are Phase 4 considerations, not MVP success criteria.

---

## Product Scope

### MVP - Minimum Viable Product

The MVP scope is laser-focused on **proving the infrastructure works reliably** before risking capital. Every feature serves validation, compliance, or essential trading functionality.

**1. Data Integration Layer** ⭐ FOUNDATION
- TradingView adapter: Redis/PostgreSQL → Nautilus Bar events (1m/5m OHLCV candles)
- MT5 ZeroMQ adapter: Real-time bid-ask spreads → Nautilus QuoteTick events
- Historical data loader for backtesting (2-3 years, GOLD/BTC/EUR)
- Data quality validation (gap detection, timestamp synchronization, anomaly detection)

**2. FTMO Rule Engine** ⭐ CRITICAL DIFFERENTIATOR
- YAML-based declarative rule configuration (rules as data, not code)
- Real-time validation after every bar (not end-of-day calculations)
- Core rules: Max Daily Loss (5%), Max Total Drawdown (10%), Minimum Trading Days, Profit Target
- Preventive order blocking when approaching limits (fail-safe design)
- Multi-layer risk architecture (strategy-level, account-level, system-level validation)
- Comprehensive audit logging (every rule check, every order decision recorded)

**3. Strategy Framework** ⭐ VALIDATION VEHICLE
- Nautilus Strategy base class implementation
- Simple baseline strategy for infrastructure testing (e.g., moving average crossover with volatility filter)
- Event-driven signal generation responding to bar close events
- Position sizing logic respecting FTMO constraints
- Support for 3 symbols: GOLD, BTC, EUR on 1m/5m timeframes

**4. Realistic Backtesting Engine** ⭐ CONFIDENCE BUILDER
- Nautilus BacktestEngine integration with custom execution model
- Dynamic spread modeling (time-of-day and volatility dependent)
- Slippage simulation (0.5-2.0× spread on market orders based on liquidity)
- Latency delay simulation (200-800ms order-to-fill delay)
- Walk-forward analysis framework (out-of-sample validation)
- Validation report generator (Sharpe ratio, win rate, drawdown, trade frequency, red flags)

**5. State Management & Persistence**
- Nautilus Cache for real-time state (positions, orders, account balance)
- Redis backup snapshots (every 5 minutes + on significant events like trade execution)
- Crash recovery mechanism (restore from last valid snapshot)
- PostgreSQL for historical trades, performance metrics, audit logs

**6. Monitoring & Alerts** (Lightweight MVP)
- Nautilus structured JSON logging (all events, decisions, errors)
- Telegram bot integration for real-time alerts:
  - Trade notifications (entry/exit with P&L and reason)
  - FTMO limit warnings (approaching 70-80% of thresholds)
  - System health alerts (connection drops, API errors, data gaps)
  - Daily summary (trades executed, P&L, rule compliance status)

**7. Execution Integration**
- MT5 execution via existing ZeroMQ bridge
- Order placement with confirmation tracking (acknowledgment within 2 seconds)
- Slippage monitoring (actual vs. expected, tracked per symbol)
- Execution quality metrics (fill rate, average slippage, latency distribution)

**MVP Validation Milestones:**
- ✅ Week 4: Data flowing end-to-end without gaps
- ✅ Week 6: FTMO rules tested against historical violation scenarios (zero false negatives)
- ✅ Week 8: Backtest completes with realistic execution model, walk-forward validation shows consistency
- ✅ Week 12+: 30 days paper trading with results within 20% of backtest, zero rule violations

### Growth Features (Post-MVP)

**Phase 2: Refinement & Expansion (Weeks 9-16)**
- Web-based monitoring dashboard (real-time P&L visualization, position tracking, FTMO limit gauges)
- Multi-strategy framework (portfolio allocation, strategy correlation analysis, aggregate risk management)
- Advanced risk features (news event detector for pause trading, volatility regime filter, dynamic position sizing based on market conditions)
- Support for additional prop firms (FTUK, Funded Trader, etc.) - extend rule engine with new YAML configurations
- Enhanced backtesting (Monte Carlo simulation for robustness testing, regime-specific performance analysis)

**Phase 3: Advanced Capabilities (Months 6-12)**
- Machine learning integration (regime detection, adaptive parameter tuning, reinforcement learning for position sizing)
- Multi-broker support (IBKR, Oanda) with automatic failover
- Advanced strategy features (multi-timeframe analysis, correlation-based filters, adaptive indicators)
- Optimization tooling (genetic algorithms, Bayesian optimization, parameter sensitivity analysis)
- Enhanced observability (Prometheus metrics, Grafana dashboards, distributed tracing)

**Phase 4: Platform Evolution (12+ months)**
- Multi-fund platform (manage multiple FTMO accounts simultaneously, aggregate reporting)
- Community features (strategy marketplace, backtesting-as-a-service, performance leaderboards)
- SaaS evolution (subscription model for other FTMO traders, managed hosting)
- Advanced compliance (support for retail brokerage regulations, expanded audit features)

### Vision (Future)

**Long-term Vision: Professional Trading Infrastructure Platform**

The ultimate vision extends beyond personal FTMO automation to a comprehensive trading infrastructure platform that empowers technical traders to build, validate, and deploy automated trading systems with professional-grade tools.

**Platform Capabilities:**
- Multi-prop-firm support (FTMO, FTUK, Funded Trader, MyForexFunds, etc.) with unified rule engine
- Strategy ecosystem (marketplace for buying/selling validated strategies, community backtesting)
- Advanced validation tools (Monte Carlo simulation, stress testing, regime analysis, correlation analysis)
- Institutional-grade observability (distributed tracing, anomaly detection, predictive alerting)
- Collaborative features (team-based strategy development, shared research, performance benchmarking)

**Business Model Evolution:**
- Phase 1-3: Personal infrastructure (no revenue, focus on capability)
- Phase 4: SaaS for individual traders ($50-200/month subscription)
- Phase 5+: Team/institutional tier ($500-2000/month for multiple accounts and strategies)
- Potential: Strategy marketplace revenue sharing, backtesting API for third-party integrations

**Technical Vision:**
- Microservices architecture (independent scaling of data, execution, risk, compliance services)
- Cloud-native deployment (Kubernetes, auto-scaling, multi-region)
- ML/AI integration (reinforcement learning for strategy optimization, NLP for news sentiment)
- Real-time collaborative features (shared workspaces, live strategy collaboration)

This vision guides architectural decisions even in MVP (event-driven design, clean separation of concerns, extensible rule engine) while maintaining pragmatic focus on immediate goals.

---

## Domain-Specific Requirements

**Fintech High-Complexity Domain Considerations:**

As a fintech trading system, this product must address domain-specific requirements that go beyond typical software development:

### Compliance & Regulatory Requirements

**FTMO Rule Compliance (Core):**
- System must enforce FTMO challenge rules with zero tolerance: 5% max daily loss, 10% max total drawdown, minimum trading days, profit targets
- Real-time rule validation (not end-of-day) to prevent violations before they occur
- Conservative buffer zones (warn at 70-80% of limits, block orders before 100%)
- Immutable audit trail of all rule checks, violations approached, and preventive actions taken
- Rule configuration as data (YAML) to support future prop firms without code changes

**Broker Integration Compliance:**
- Adherence to MT5 API rate limits and usage terms
- Proper handling of broker-specific order types and constraints
- Graceful degradation when broker API is unavailable
- Compliance with broker data feed terms of service

**Future Expansion Considerations:**
- If evolving to multi-user platform: data privacy requirements, credential isolation, PII protection
- If expanding to additional markets/brokers: regional trading regulations, market-specific rules
- Tax reporting considerations: comprehensive trade logs, P&L calculations, historical data retention

### Risk Management Requirements

**Multi-Layer Risk Validation:**
- Strategy-level risk: Position sizing respects FTMO constraints per trade
- Account-level risk: Aggregate exposure across all strategies monitored in real-time
- System-level risk: Emergency stop mechanisms, connection loss detection, failsafe defaults

**Financial Error Prevention:**
- Duplicate order prevention (idempotency checks)
- Position reconciliation (system state matches broker state)
- Balance verification (P&L calculations match broker reported balance)
- Anomaly detection (orders outside expected size/price ranges flagged)

**Operational Risk Management:**
- Crash recovery without state loss or duplicate orders
- Connection monitoring with automatic reconnection
- Data feed health checks (gap detection, stale data detection)
- Fail-safe defaults (if uncertain, don't trade)

### Data Integrity & Audit Requirements

**Tamper-Proof Audit Trail:**
- Every trade decision logged with timestamp, reasoning, market conditions
- All FTMO rule checks recorded (pass/fail, current values, thresholds)
- System events tracked (startups, shutdowns, errors, reconnections)
- Audit log immutable and append-only (no deletion or modification)

**Data Quality Assurance:**
- Historical data validation before backtest (completeness, accuracy, anomaly detection)
- Real-time data quality checks (timestamp consistency, price sanity checks, gap detection)
- Cross-validation between data sources (TradingView vs. MT5 spread comparison)
- Data provenance tracking (source, timestamp, transformations applied)

**State Consistency:**
- Positions, orders, and account balance always reconcilable
- Periodic state snapshots for disaster recovery
- State validation on startup (detect inconsistencies from crashes)
- Synchronization verification between Nautilus cache and broker state

### Security Requirements

**Credential & Secret Management:**
- Secure storage of API keys (TradingView, MT5, Telegram, broker credentials)
- No secrets in code or version control
- Environment variable or secure vault-based configuration
- Credential rotation support without system downtime

**Intellectual Property Protection:**
- Trading strategies and parameters not exposed in logs or public APIs
- Access control if future multi-user platform
- Secure communication channels for all external integrations

### Integration Reliability Requirements

**External System Dependencies:**
- **TradingView API**: Historical data source, must handle rate limits, retry transient failures
- **MT5 ZeroMQ**: Real-time spreads and execution, must detect connection loss and reconnect
- **Broker MT5 Terminal**: Execution endpoint, must handle broker downtime gracefully
- **Redis**: State persistence, must have backup/recovery strategy
- **PostgreSQL**: Historical data, must handle connection loss without data loss

**Graceful Degradation:**
- If TradingView data unavailable: Use cached historical data or pause backtesting
- If MT5 spreads unavailable: Use static spread estimates or pause live trading
- If broker execution unavailable: Queue orders or pause trading with immediate alert
- If Telegram unavailable: Log locally and retry alerts

**Health Monitoring:**
- Connection status for each external system monitored continuously
- Latency tracking for critical paths (data ingestion, order execution)
- Data freshness checks (alert if data older than threshold)
- Heartbeat mechanisms for long-running processes

---

## Innovation & Novel Patterns

This system introduces several innovative approaches that differentiate it from traditional trading bots and generic automation tools:

### Innovation #1: Compliance-First Architecture

**Novel Approach:** Treating FTMO rule compliance as a first-class architectural concern rather than an afterthought validation layer.

**What Makes It Unique:**
- Traditional trading systems focus on strategy alpha with risk management bolted on
- This system inverts the priority: compliance engine sits at the architectural core, strategies operate within compliance boundaries
- Declarative rule engine (YAML-based) makes compliance logic explicit, auditable, and extensible
- Real-time validation after every bar (not EOD) with preventive order blocking

**Validation Approach:**
- Historical violation scenario testing: Replay trades that should have triggered rules, verify zero false negatives
- Conservative buffer testing: Verify system stops trading at 70-80% thresholds, not at 100%
- Multi-day paper trading: Confirm zero violations over 30+ days across varying market conditions
- Edge case testing: Rapid drawdown scenarios, gap fills, rollover events

**Fallback Strategy:**
If real-time validation proves too complex or has performance issues:
- Implement dual validation: Real-time (fast, approximate) + periodic (detailed, accurate)
- Add manual confirmation step before live trading if automated validation can't reach 100% confidence
- Start with more conservative thresholds (60-70% instead of 70-80%) until proven reliable

### Innovation #2: Backtest-Live Convergence Through Realistic Execution Modeling

**Novel Approach:** Eliminating the dangerous "backtest-reality gap" through comprehensive execution realism baked into backtesting framework.

**What Makes It Unique:**
- Most retail systems use naive execution models (fill at close price, static spread)
- This system models dynamic spreads (time-of-day, volatility-dependent), realistic slippage (0.5-2.0× spread based on order size), and latency delays (200-800ms)
- Same codebase runs backtests and live trading (Nautilus feature), eliminating divergence from code differences
- Walk-forward validation proves out-of-sample performance, not just in-sample overfitting

**Validation Approach:**
- Paper trading is the ultimate validation: Results within 20% of backtest proves model accuracy
- Slippage tracking: Compare actual vs. modeled slippage, iterate spread model if divergence > 10%
- Latency measurement: Measure real order-to-fill latency, validate simulation assumptions
- Continuous calibration: Update spread/slippage models monthly based on live execution data

**Fallback Strategy:**
If backtest-live convergence doesn't achieve within 20%:
- Increase paper trading duration (60-90 days) to get more representative sample
- Conservative bias: If backtest is better than live, assume live performance and work backward to improve strategy
- Incremental strategy deployment: Start with smallest position sizes, scale up only after proven live performance
- Focus on robustness over optimization: Prefer strategies that perform consistently in both backtest and live rather than chasing backtest performance

### Innovation #3: Event-Driven Trading Infrastructure for Retail

**Novel Approach:** Bringing institutional-grade event-driven architecture patterns to retail/prop trading through Nautilus Trader framework.

**What Makes It Unique:**
- Retail trading systems typically use polling loops, monolithic designs, or fragile state management
- This system leverages production-grade event bus, type-safe messaging, and clean separation of concerns
- Natural fit for trading domain: Markets ARE event-driven (bar close, quote update, fill confirmation)
- Extensibility by design: Add new strategies, symbols, or compliance rules without core changes

**Why This Matters:**
- Scalability: Can handle multiple strategies on multiple symbols concurrently without threading complexity
- Reliability: Event-driven systems are easier to test, debug, and reason about (deterministic event replay)
- Maintainability: Clear contracts between components (strategy reacts to bars, risk reacts to orders, compliance reacts to trades)
- Professional learning: Architecture patterns applicable to broader trading infrastructure development

**No Fallback Needed:**
This is an architectural decision made upfront by choosing Nautilus Trader. The learning curve is the risk, not the approach validity.

### Innovation #4: Pragmatic Hybrid Infrastructure Strategy

**Novel Approach:** Leveraging existing operational infrastructure (tv-api, MT5 ZeroMQ, Redis/PostgreSQL) through adapters rather than rebuilding everything.

**What Makes It Unique:**
- "Not invented here" syndrome plagues many developer projects - tendency to rebuild everything
- This system pragmatically integrates proven components, focusing development effort on differentiating 20% (FTMO rules, realistic modeling, validation)
- Adapter pattern isolates integration complexity, making it swappable if needed
- Achieves 6-8 week MVP vs. 6+ months fully custom by standing on existing infrastructure

**Why This Matters:**
- Faster validation: Working system in weeks, not months
- Lower risk: Existing components already proven in production use
- Focus on differentiation: Development time spent on FTMO compliance engine, not rebuilding data pipelines
- Extensibility: If TradingView adapter has issues, swap for Nautilus-native adapter without changing core system

**Validation Approach:**
- Integration tests in Week 2-3: Data flows end-to-end, no gaps, no quality issues
- Fallback plan: If adapters prove problematic, Nautilus has native data providers (IQFeed, Interactive Brokers)
- Clear abstraction boundaries: Integration code isolated from strategy/risk/compliance logic

---

## developer_tool Specific Requirements

As a **Developer Tool** project type, this system has unique requirements focused on extensibility, developer experience, and framework quality:

### System Architecture & Design

**Framework-Quality Code:**
- Clear separation of concerns (data layer, strategy layer, risk layer, execution layer, compliance layer)
- Well-defined interfaces and contracts between components
- Type hints and documentation for all public APIs
- Consistent error handling and logging patterns
- Unit testable components with dependency injection where appropriate

**Extensibility Points:**
- **New Strategies**: Inherit from base Strategy class, implement signal generation, plug in without core changes
- **New Symbols**: Add symbol configuration to YAML, data adapters automatically support
- **New Prop Firms**: Add new rule YAML file, rule engine automatically enforces
- **New Data Sources**: Implement adapter interface, swap providers without changing downstream code
- **New Execution Venues**: Implement execution adapter interface, support multiple brokers

**Configuration as Code:**
- YAML-based configuration for rules, strategies, symbols, risk parameters
- Environment variables for secrets and deployment-specific settings
- Code controls behavior, configuration controls specifics
- Version control for configuration changes with clear migration paths

### Developer Experience

**Project Setup & Onboarding:**
- Clear README with setup instructions, prerequisites, and architecture overview
- Automated environment setup (Poetry/pip-tools for dependencies, Docker Compose for services)
- Example configurations for common use cases (different strategies, different prop firms)
- Troubleshooting guide for common integration issues

**Development Workflow:**
- Local development mode with mock data sources for fast iteration
- Hot reload for strategy changes without full system restart
- Comprehensive logging for debugging (structured JSON, multiple log levels)
- CLI commands for common operations (backtest, paper trade, analyze logs)

**Testing & Validation:**
- Unit tests for core logic (rule engine, position sizing, risk calculations)
- Integration tests for data adapters (verify data flows end-to-end)
- Backtesting framework serves as integration test (strategy + data + execution + risk)
- Historical scenario replay for regression testing (verify rule engine behavior)

### Documentation & Learning

**Code Documentation:**
- Docstrings for all classes and public methods (Google style or numpy style)
- Inline comments for complex logic or non-obvious decisions
- Type hints for IDE support and self-documenting interfaces
- Architecture Decision Records (ADR) for key design choices

**System Documentation:**
- Architecture overview: Component diagram, data flow, event flow
- Integration guide: How to add new data sources, execution venues, strategies
- FTMO rule engine: How declarative rules work, how to add new prop firms
- Troubleshooting guide: Common issues, debugging techniques, FAQ

**Learning Resources:**
- Example strategies with detailed comments explaining event-driven patterns
- Backtesting tutorial showing how to evaluate and iterate on strategies
- Walk-forward analysis guide explaining out-of-sample validation
- Realistic execution modeling explanation with spread/slippage research

### Package & Distribution

**MVP: Single-User Installation**
- Git repository with clear installation instructions
- Environment setup scripts (Python venv, dependency installation, service startup)
- Docker Compose for infrastructure services (Redis, PostgreSQL)
- Configuration templates with sensible defaults

**Future: Multi-User Distribution (Phase 4+)**
- PyPI package for easy installation (`pip install ftmo-trading-system`)
- Pre-built Docker images for one-command deployment
- Web-based installer/configurator for non-technical users
- Managed hosting option (SaaS deployment)

### Integration & API Requirements

**Data Adapter Interface:**
- Standardized adapter contract: `get_bars()`, `get_quotes()`, `subscribe_live()`
- Support for both historical (backtest) and live (streaming) data modes
- Error handling contract: Transient errors (retry), permanent errors (fail-fast)
- Data quality validation built into adapter layer

**Execution Adapter Interface:**
- Standardized execution contract: `submit_order()`, `cancel_order()`, `get_positions()`
- Order confirmation tracking and timeout handling
- Slippage monitoring and execution quality metrics
- Graceful degradation when execution venue unavailable

**Strategy Interface:**
- Event-driven contract: `on_bar()`, `on_quote()`, `on_order_filled()`
- Strategy lifecycle: `on_start()`, `on_stop()`, `on_resume()`
- Position management helpers: `open_position()`, `close_position()`, `size_position()`
- Market data access: Access to historical bars, current positions, account state

**Compliance Rule Interface:**
- Declarative YAML schema for rule definition
- Rule evaluation contract: `check_compliance(event)` returns pass/fail + metadata
- Multi-layer rules: Strategy-level, account-level, system-level
- Rule action contract: Warn, block, emergency stop

---

## Functional Requirements

These functional requirements define the complete capability contract for the FTMO Trading System. Every capability listed here must be implemented for MVP success. FRs are organized by capability area and numbered sequentially.

### Data Integration & Management

**FR1:** tv-api service (Go) can ingest historical OHLCV candle data from TradingView WebSocket for GOLD, BTC, and EUR symbols on 1m and 5m timeframes, publishing to Redis and storing in TimescaleDB

**FR2:** mt5-bridge service (Rust) can receive real-time bid-ask spread updates from MT5 EA via ZeroMQ REQ/REP and publish to trading-engine via ZeroMQ PUB/SUB

**FR3:** trading-engine service (Python) can load 2-3 years of historical data from TimescaleDB for backtesting purposes with automatic handling of date ranges and symbol mapping

**FR4:** trading-engine can validate data quality automatically, detecting gaps, timestamp inconsistencies, impossible prices, and other anomalies

**FR5:** notification service (Go) can alert when data feed freshness exceeds threshold (stale data detection) or when connection to data sources is lost

**FR6:** trading-engine can cross-validate data from multiple sources (compare TradingView candles with MT5 quotes for sanity checks)

**FR7:** All services can handle data source unavailability gracefully (use cached data for backtest, pause live trading with alert via notification service)

### FTMO Compliance & Rule Engine

**FR8:** System can load FTMO compliance rules from declarative YAML configuration files without code changes

**FR9:** System can enforce maximum daily loss rule (default 5%, configurable) by tracking intraday P&L in real-time

**FR10:** System can enforce maximum total drawdown rule (default 10%, configurable) by tracking peak-to-trough account balance

**FR11:** System can track minimum trading days requirement and progress toward profit targets

**FR12:** System can validate compliance rules after every bar close (not end-of-day) for immediate violation detection

**FR13:** System can implement preventive order blocking when approaching risk limits (warn at 70-80%, block orders before 100%)

**FR14:** System can apply multi-layer risk validation: strategy-level, account-level, and system-level checks before order submission

**FR15:** System can maintain immutable audit trail of all compliance checks including timestamps, rule evaluations, threshold values, and pass/fail results

**FR16:** System can support multiple prop firm rule configurations (extensible to FTUK, Funded Trader, etc. through new YAML files)

**FR17:** System can provide emergency stop mechanism that immediately halts all trading when triggered manually or by critical violation

### Strategy Execution & Trading Logic

**FR18:** System can execute trading strategies that inherit from Nautilus Strategy base class with event-driven architecture

**FR19:** System can generate trading signals in response to bar close events (end of 1m or 5m period)

**FR20:** System can calculate position sizes that respect FTMO constraints (daily loss limit, total drawdown limit, maximum position size)

**FR21:** System can manage positions for multiple symbols concurrently (GOLD, BTC, EUR) without interference

**FR22:** System can execute market orders through MT5 broker via ZeroMQ with order confirmation tracking

**FR23:** System can support baseline strategy for infrastructure validation (e.g., moving average crossover with volatility filter)

**FR24:** System can provide strategy lifecycle hooks (on_start, on_stop, on_resume, on_bar, on_quote, on_order_filled)

**FR25:** System can allow strategies to access current positions, account balance, and historical bar data

**FR26:** System can log every trade decision with reasoning, market conditions, and signal parameters for post-trade analysis

### Backtesting & Validation

**FR27:** System can run backtests using Nautilus BacktestEngine with 2-3 years of historical data

**FR28:** System can apply realistic execution model during backtesting including dynamic spreads, slippage, and latency delays

**FR29:** System can model dynamic spreads based on time-of-day and volatility (not static spread assumptions)

**FR30:** System can simulate realistic slippage (0.5-2.0× spread on market orders) based on order size and liquidity

**FR31:** System can simulate order execution latency (200-800ms delay between order submission and fill)

**FR32:** System can perform walk-forward analysis with multiple out-of-sample periods to validate strategy robustness

**FR33:** System can generate validation reports including Sharpe ratio, win rate, maximum drawdown, trade frequency, and red flag indicators

**FR34:** System can detect and alert on red flag metrics indicating overfitting or unrealistic backtest assumptions

**FR35:** System can use identical codebase for backtesting and live trading (no divergence between backtest logic and live execution)

### State Management & Persistence

**FR36:** System can maintain real-time state (positions, orders, account balance) in Nautilus Cache for fast access

**FR37:** System can create periodic state snapshots to Redis (every 5 minutes + on significant events like trades)

**FR38:** System can recover from crashes by restoring state from most recent valid snapshot without duplicate orders or state loss

**FR39:** System can verify state consistency on startup, detecting and alerting on inconsistencies from previous crashes

**FR40:** System can reconcile internal state with broker-reported state (positions, balance) and alert on discrepancies

**FR41:** System can persist historical trade data to PostgreSQL including entry/exit prices, P&L, timestamps, and strategy metadata

**FR42:** System can persist performance metrics and audit logs to PostgreSQL for long-term analysis and tax reporting

**FR43:** System can maintain append-only audit logs that cannot be modified or deleted (tamper-proof)

### Risk Management & Safety

**FR44:** System can prevent duplicate order submission through idempotency checks

**FR45:** System can detect and alert on position reconciliation failures (system position != broker position)

**FR46:** System can validate account balance calculations match broker-reported balance

**FR47:** System can detect anomalies in order parameters (size/price outside expected ranges) and block suspicious orders

**FR48:** System can detect connection loss to critical services (broker, data feeds) and pause trading with immediate alert

**FR49:** System can implement fail-safe defaults (when uncertain about state or connectivity, do not trade)

**FR50:** System can automatically reconnect to data feeds and execution venues after transient connection failures

**FR51:** System can track aggregate exposure across all active strategies to prevent over-leveraging

### Monitoring, Alerts & Observability

**FR52:** All services can generate structured JSON logs for all events, decisions, errors, and state changes

**FR53:** notification service (Go) can send Telegram alerts for trade executions including entry/exit, P&L, and trade reasoning (received via Redis Pub/Sub from trading-engine)

**FR54:** notification service can send Telegram alerts when approaching FTMO risk limits (70-80% thresholds)

**FR55:** notification service can send Telegram alerts for system health issues (connection drops, API errors, data gaps, crashes) from all services

**FR56:** notification service can send daily summary reports via Telegram including trades executed, P&L, rule compliance status

**FR57:** All services can publish health status to Redis, notification service can track and alert on data feed health (connection status, latency, freshness)

**FR58:** trading-engine can monitor execution quality metrics (fill rate, average slippage, latency distribution) and publish alerts via notification service on degradation

**FR59:** All services can log all external API calls and responses for debugging and audit purposes

### Execution & Broker Integration

**FR60:** trading-engine can submit market orders to MT5 broker via mt5-bridge service (Rust) using ZeroMQ REQ/REP pattern

**FR61:** mt5-bridge can track order confirmation and forward to trading-engine, alerting via notification service on order timeouts (acknowledgment within 2 seconds expected)

**FR62:** trading-engine can measure actual slippage on filled orders and compare against expected slippage model

**FR63:** trading-engine can track execution latency (order submission to fill confirmation) per symbol, with metrics stored in TimescaleDB

**FR64:** mt5-bridge can handle broker API errors gracefully (rate limits, temporary unavailability) with retry logic and fallback

**FR65:** mt5-bridge can queue orders during temporary broker unavailability or pause trading with alert via notification service if unavailability persists

### Paper Trading & Live Trading Modes

**FR66:** System can operate in paper trading mode using real market data but simulated execution

**FR67:** System can track paper trading performance metrics and compare against backtest results

**FR68:** System can switch between paper trading and live trading modes through configuration without code changes

**FR69:** System can clearly indicate current trading mode in logs and alerts to prevent confusion

**FR70:** System can maintain separate state and performance tracking for paper vs. live trading

### Configuration & Deployment

**FR71:** System can load all configuration from YAML files (strategies, symbols, rules, risk parameters)

**FR72:** System can load secrets and credentials from environment variables (not hardcoded or in version control)

**FR73:** System can validate configuration on startup and fail fast with clear error messages if misconfigured

**FR74:** System can run in local development mode with mock data sources for fast iteration

**FR75:** System can be deployed via Docker Compose including all 4 services and infrastructure (Redis, TimescaleDB)

**FR76:** System can support VPS deployment with automated startup and health checks

**FR76a:** Each service (tv-api, mt5-bridge, trading-engine, notification) can be built and deployed independently

**FR76b:** System provides unified Makefile commands for building, testing, and deploying all services

**FR76c:** System supports environment-specific configuration via `/configs/dev/` and `/configs/prod/` directories

**FR76d:** Docker Compose configuration includes health checks for all services and infrastructure components

### Extensibility & Developer Experience

**FR77:** System can support adding new trading strategies without modifying core system code (plugin architecture)

**FR78:** System can support adding new symbols by updating configuration without code changes

**FR79:** System can support adding new prop firm rule sets through new YAML files without code changes

**FR80:** System can support swapping data sources by implementing adapter interface without changing downstream code

**FR81:** System can support adding new execution venues through adapter interface

**FR82:** System can provide CLI commands for common operations (run backtest, start paper trading, analyze performance)

**FR83:** System can hot reload strategy configurations without full system restart during development

**FR84:** System can generate configuration templates with sensible defaults for quick setup

**FR84a:** System can support adding new services by creating new folder in `/services` directory following established patterns

**FR84b:** Each service has its own README.md documenting build, run, and test procedures

**FR84c:** Services communicate through well-defined protocols (ZeroMQ, Redis Pub/Sub) with documented message formats

### Testing & Validation Framework

**FR85:** System can replay historical scenarios for regression testing of compliance rule engine

**FR86:** System can execute unit tests for core logic (rule validation, position sizing, risk calculations)

**FR87:** System can execute integration tests validating data flow end-to-end (source → Nautilus → strategy)

**FR88:** System can use backtesting framework as integration test to validate complete system behavior

**FR89:** System can validate zero false negatives in compliance rule enforcement through historical violation replay

### Documentation & Learning

**FR90:** System can provide example strategies with detailed documentation explaining event-driven patterns

**FR91:** System can generate architecture documentation showing component relationships and data flows

**FR92:** System can include troubleshooting guides for common integration issues and debugging techniques

**FR93:** System can maintain architecture decision records (ADR) documenting key design choices

---

## Non-Functional Requirements

### Performance

**Latency & Response Time:**
- Order submission to broker acknowledgment: Target 100-500ms (sufficient for 1m/5m timeframes)
- FTMO compliance rule validation: Complete within 100ms per rule check to enable real-time validation
- Data ingestion pipeline: Process incoming bars/quotes with < 50ms delay to maintain data freshness
- Strategy signal generation: Complete within single bar period (60s for 1m, 300s for 5m) with margin for processing
- State snapshot creation: Complete Redis snapshot in < 1 second to minimize impact on trading operations

**Throughput:**
- Data pipeline: Handle concurrent data streams for 3 symbols × 2 timeframes = 6 simultaneous feeds
- Parallel processing: Support multiple strategies operating independently on different symbols without performance degradation
- Event processing: Handle burst events during high volatility (100+ events/second) without queue backlog
- Logging: Write structured logs at 1000+ events/second without blocking main trading logic

**Resource Efficiency:**
- Memory: Operate within 2GB RAM for MVP single-strategy deployment (scales with strategy count)
- CPU: Maintain < 50% CPU utilization during normal trading to leave headroom for volatility spikes
- Storage: PostgreSQL historical data < 10GB for 3 years × 3 symbols (compressed, indexed)
- Network: Minimize data transfer with local caching, acceptable on typical VPS bandwidth (100 Mbps)

**Performance Priorities (Ranked):**
1. Reliability & consistency (zero missed signals, zero crashes) > raw speed
2. Fast risk response (compliance validation < 100ms)
3. Execution quality (minimize slippage) > execution speed
4. Data pipeline efficiency (non-blocking indicator calculations)
5. Parallel strategy processing

### Security

**Authentication & Authorization:**
- All API credentials (TradingView, MT5, Telegram, broker) stored securely, never in code or version control
- Environment variables or secure vault (e.g., AWS Secrets Manager, HashiCorp Vault) for production deployment
- No credentials logged or exposed in error messages or debug output

**Data Protection:**
- Trading strategies and parameters treated as intellectual property, not exposed in logs or external APIs
- Audit logs contain trading decisions but not proprietary strategy logic
- Database connections use encrypted channels (SSL/TLS)
- Telegram bot communication over HTTPS

**Secrets Management:**
- Support credential rotation without system downtime (reload configuration without restart)
- Separate credentials for paper trading vs. live trading environments
- API keys have minimum required permissions (principle of least privilege)

**Future Multi-User Considerations (Phase 4+):**
- User credential isolation (each user's API keys stored separately)
- Role-based access control (admin, trader, viewer roles)
- Data privacy compliance (GDPR if European users, appropriate data retention policies)

### Reliability & Availability

**Uptime:**
- Target 99.5% uptime during market hours (allows ~3.6 hours downtime per month for maintenance)
- Planned maintenance during market close windows when possible
- VPS deployment for production (99.9% infrastructure uptime)

**Crash Recovery:**
- System recovers from crashes automatically with state restoration from Redis snapshots
- No duplicate orders on restart (idempotency enforced)
- State validation on startup detects inconsistencies and alerts for manual verification if needed
- Maximum state loss: 5 minutes (time since last snapshot)

**Connection Resilience:**
- Automatic reconnection to data feeds after transient failures (retry with exponential backoff)
- Automatic reconnection to broker after connection drops
- Graceful degradation: Pause trading if critical connections unavailable > 60 seconds with immediate alert
- Heartbeat monitoring for all external connections (detect silent failures within 30 seconds)

**Data Integrity:**
- Audit logs append-only, immutable (no deletion or modification)
- State snapshots atomic (complete or not at all, no partial states)
- Database transactions for trade records (ACID compliance)
- Periodic reconciliation between system state and broker state (every 15 minutes during trading)

**Error Handling:**
- Fail-safe defaults: When uncertain, do not trade (prefer safety over opportunity)
- All errors logged with full context (stack trace, system state, market conditions)
- Critical errors trigger immediate Telegram alerts with actionable information
- Non-critical errors logged for post-analysis without blocking operations

### Scalability

**MVP Scope (Limited Scalability Requirements):**
- 3 symbols (GOLD, BTC, EUR) on 2 timeframes (1m, 5m) = manageable with single instance
- 1 strategy in MVP, designed to support 3-5 strategies in Phase 2
- Single trading account (one FTMO challenge at a time)

**Design for Future Scaling (Phase 2+):**
- Event-driven architecture naturally supports horizontal scaling (add more strategies without interference)
- Stateless strategy design enables running multiple strategy instances in parallel
- Database schema designed for multiple accounts/strategies (indexed by account_id, strategy_id)
- Redis can cluster for higher throughput if needed (MVP uses single instance)

**Scalability Priorities:**
- MVP: Prove single-strategy reliability, not scale
- Phase 2: Support 5-10 concurrent strategies on single VPS
- Phase 3: Multi-account support (manage multiple FTMO challenges simultaneously)
- Phase 4: Multi-user platform (requires microservices architecture, beyond MVP scope)

### Maintainability & Supportability

**Code Quality:**
- Type hints throughout codebase (Python 3.10+ type annotations)
- Docstrings for all public classes and methods (Google or numpy style)
- Inline comments for complex logic or non-obvious implementation decisions
- Consistent code style (enforced by linters: black, pylint, mypy)

**Testability:**
- Unit test coverage > 70% for core logic (rule engine, position sizing, risk validation)
- Integration tests for all adapters (data, execution)
- Backtesting framework serves as end-to-end integration test
- Historical scenario replay for regression testing

**Observability:**
- Structured JSON logging with consistent field names and formats
- Log levels appropriately used (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- All significant events logged: trades, rule checks, errors, state changes, external API calls
- Logs include context: timestamp, module, function, market conditions, system state

**Debugging Support:**
- Comprehensive logs enable post-incident analysis without reproducing issues
- Event replay capability for debugging strategy logic
- Performance profiling hooks (can enable detailed timing in development mode)
- Health check endpoints for monitoring system status

**Configuration Management:**
- All configuration in version control (YAML files)
- Configuration changes documented (git commit messages explain why)
- Backward compatibility for configuration schema (migrations documented)
- Validation on startup catches configuration errors early

### Deployment & Operations

**Deployment Targets:**
- **Development**: Local machine with Docker Compose for services (Redis, PostgreSQL)
- **Production MVP**: Single VPS (Digital Ocean, AWS EC2, Linode) with Docker Compose
- **Future**: Kubernetes for multi-instance deployment (Phase 4)

**Deployment Automation:**
- Docker Compose configuration includes all required services with correct network configuration
- Environment setup script automates dependency installation (Python packages, Docker, etc.)
- Configuration templates with sensible defaults (minimal manual configuration required)
- Health checks verify successful deployment (all services running, connections established)

**Operational Requirements:**
- Monitoring dashboard not required for MVP (Telegram alerts sufficient)
- Log aggregation not required for MVP (local logs sufficient, consider Grafana/Loki in Phase 2)
- Backup strategy: Redis snapshots every 5 minutes, PostgreSQL nightly backups
- Disaster recovery: Restore from latest Redis snapshot + PostgreSQL backup, manual state reconciliation if needed

**Operational Cost:**
- VPS: $50-100/month for production deployment (8GB RAM, 4 CPU cores, 100GB SSD)
- Data feeds: Existing TradingView subscription, MT5 broker data included
- Infrastructure services: Self-hosted Redis/PostgreSQL (no external service costs)
- Total operational cost: $50-100/month

### Usability & Developer Experience

**Developer Onboarding:**
- New developer can setup development environment in < 30 minutes following README
- Example strategy provided demonstrates all key patterns (event handling, position management, risk integration)
- Troubleshooting guide addresses common setup issues (connection problems, configuration errors)

**Configuration & Setup:**
- Configuration YAML files human-readable and well-commented
- Validation provides clear error messages (e.g., "Invalid symbol 'BTCUSD': Expected format 'BTC', available symbols: ['GOLD', 'BTC', 'EUR']")
- Environment variables documented with examples (.env.example template provided)

**Debugging & Iteration:**
- Local development mode with mock data enables fast iteration without external dependencies
- Hot reload for strategy changes (no full restart needed during development)
- Backtest iterations complete in minutes (not hours), enabling rapid strategy experimentation
- Logs human-readable with appropriate verbosity (INFO level for high-level flow, DEBUG for detailed trace)

**CLI Usability:**
- CLI commands intuitive and consistent (e.g., `ftmo-system backtest --strategy=ma_cross --period=2023`)
- Help text available for all commands (`--help` flag)
- Progress indicators for long-running operations (backtest progress bar)
- Output formatted for readability (tables, colors, clear sections)

### Compliance & Audit

**Audit Trail Requirements:**
- Every trade logged with: strategy name, symbol, direction, size, entry/exit price, P&L, timestamp, reasoning
- Every compliance check logged with: rule name, current value, threshold, pass/fail, timestamp
- System events logged: startups, shutdowns, errors, reconnections, configuration changes
- Audit log format: Structured JSON for easy parsing and analysis

**Retention Requirements:**
- Trade history: Retain indefinitely (required for tax reporting and performance analysis)
- Audit logs: Retain for 2 years minimum (sufficient for FTMO challenge duration + analysis)
- Performance metrics: Retain indefinitely (long-term strategy evaluation)
- System logs: Retain for 90 days (debugging recent issues), archive older logs

**Tamper-Proofing:**
- Audit logs append-only (no modification or deletion operations)
- File permissions restrict write access to system process only
- Consider cryptographic hashing for critical audit entries if regulatory requirements increase (Phase 4)

**Reporting:**
- Daily summary reports: Trades, P&L, rule compliance status, system health
- Monthly performance reports: Strategy metrics, execution quality, compliance track record
- On-demand reports: Backtest results, walk-forward analysis, trade-by-trade breakdown
- Export formats: CSV for spreadsheet analysis, JSON for programmatic access

---

_This PRD v2.0 captures the comprehensive requirements for the FTMO Trading System - a professional monorepo with 4 independent microservices (tv-api, mt5-bridge, trading-engine, notification) built for reliability, validation, and FTMO compliance. With 100+ functional requirements organized into 13 capability areas and comprehensive non-functional requirements covering performance, security, reliability, and maintainability, this document serves as the complete contract for architecture and epic breakdown._

_Architecture: See `docs/architecture.md` for detailed technical specifications._

_**Project Classification:** Developer Tool in the Fintech domain with High Complexity_

_**What Makes It Special:** Real-time automated FTMO compliance through first-class architectural design, backtest-reality alignment through realistic execution modeling, professional event-driven architecture for retail/prop trading, and pragmatic infrastructure leverage through adapter-based integration._

_**Key Success Metrics:** Zero FTMO violations over 30+ days paper trading, paper results within 20% of backtest, 24-hour uptime without crashes, confidence gate passed to risk FTMO challenge fee._

_Created through YOLO-mode workflow execution analyzing Product Brief for FTMO Trading System._
