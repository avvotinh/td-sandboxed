# Product Brief: FTMO Trading System

**Date:** 2025-11-25
**Author:** BMad
**Context:** Expert Technical Project

---

## Executive Summary

An event-driven automated trading system engineered specifically for FTMO prop firm challenges, targeting high-frequency intraday trading on 1m/5m timeframes across GOLD, BTC, and EUR symbols. The system leverages Nautilus Trader's production-grade event architecture, integrates existing TradingView and MT5 infrastructure, and implements rigorous FTMO compliance monitoring to ensure reliable, rule-compliant trading that passes fund challenges through disciplined risk management rather than gambling.

---

## Core Vision

### Problem Statement

FTMO and similar prop firm challenges require traders to demonstrate consistent profitability within strict risk constraints - but the challenge isn't just about having a profitable strategy. The real problems are:

1. **Compliance Complexity**: FTMO rules are non-negotiable (5% max daily loss, 10% max total drawdown, minimum trading days, profit targets). A single violation terminates the account. Manual monitoring is error-prone and high-stress.

2. **Backtest-Reality Gap**: Most retail trading systems work beautifully in backtesting but fail in live trading due to unrealistic assumptions about execution quality, slippage, spreads, and latency. This "backtest divergence" destroys trader confidence and capital.

3. **Architecture Limitations**: Traditional polling-based or monolithic trading systems are difficult to extend, impossible to audit comprehensively, and don't naturally support the multiple independent subsystems needed (strategy logic, risk management, compliance monitoring, execution).

4. **Reliability Over Speed**: For 1m/5m intraday trading, 100-500ms latency is sufficient - but **reliability, consistency, and uptime are critical**. Missing signals, crashes during volatility, or connection drops are catastrophic when trading with prop firm capital.

### Problem Impact

**For Individual Traders:**
- FTMO challenge fees: $155-$1,080 per attempt
- Failed challenges due to rule violations despite profitable trades
- Emotional stress from manual risk monitoring during live trading
- Inability to scale trading (limited to what can be manually monitored)

**For the System Builder (You):**
- Existing infrastructure (tv-api, MT5 ZeroMQ, Redis/PostgreSQL) underutilized
- Need for professional architecture that supports future expansion (multiple prop firms, multiple strategies)
- Desire to prove capability through systematic, validated approach rather than "hope and trade"

### Proposed Solution

A **pragmatic hybrid trading system** that combines:

**Core Framework: Nautilus Trader**
- Production-grade event-driven architecture (Rust/Cython core)
- Unified backtesting/live codebase (eliminates divergence)
- Natural fit for trading domain (markets ARE event-driven)
- Professional patterns for risk management, portfolio tracking, and execution

**Custom Extensions:**
- **FTMO Rule Engine**: YAML-based declarative rules, real-time validation (not EOD), preventive order blocking when approaching limits
- **Data Integration Layer**: Adapters connecting existing TradingView (OHLCV candles) + MT5 (bid-ask spreads, execution) infrastructure to Nautilus
- **Realistic Backtesting**: Dynamic spread modeling, slippage simulation, latency delay, walk-forward validation

**Key Architectural Principles:**
- Event-driven core (strategies, risk, compliance all react to market events)
- Extensible by design (add new rules, strategies, symbols without core changes)
- Leverage existing infrastructure (don't rebuild what works)
- Pragmatic over perfect (ship MVP in 6-8 weeks, iterate)

### Key Differentiators

**vs. Manual Trading:**
- Real-time automated FTMO compliance (zero violations)
- Removes emotional decision-making under pressure
- Scalable to multiple strategies and symbols simultaneously

**vs. Generic Trading Bots:**
- Purpose-built for FTMO compliance (not generic trading)
- Professional event-driven architecture (not polling loops)
- Realistic backtesting prevents false confidence
- Extensible to other prop firms and custom rules

**vs. Building Fully Custom:**
- Leverages Nautilus Trader for 80% of infrastructure (event bus, backtesting, execution framework)
- Focuses development effort on differentiating 20% (FTMO rules, data integration, validation)
- 6-8 weeks to MVP vs. 6+ months for fully custom

**vs. All-In Nautilus:**
- Integrates existing production infrastructure (tv-api, ZeroMQ)
- Custom FTMO validation layer (not generic risk management)
- Tailored for specific use case (intraday FTMO challenges)

---

## Target Users

### Primary Users

**Profile: The System Builder (Immediate)**
- **Who**: Technical trader/developer building automated trading infrastructure
- **Skill Level**: Expert programmer, intermediate-to-advanced trader
- **Current Workflow**: Operating TradingView data pipeline (tv-api), MT5 via ZeroMQ, manual strategy testing
- **Core Frustrations**:
  - Existing infrastructure underutilized
  - Manual FTMO compliance monitoring is stressful and error-prone
  - Backtest results don't match live trading
  - Difficulty testing strategies rigorously before risking capital
- **What They Value Most**:
  - Architectural elegance and extensibility
  - Confidence through validation (backtesting, paper trading, walk-forward analysis)
  - Professional patterns they can learn from
  - Leverage existing infrastructure investments
  - Clear path from MVP to production

**Success Scenario**: Successfully passes FTMO challenge Phase 1 (profit target met, zero rule violations) using validated strategies running on the automated system, with full confidence from 30+ days of paper trading that matched backtest performance within 20%.

### Secondary Users

**Profile: Future Expansion (6-12 months)**
- **Who**: Other traders interested in FTMO/prop firm automation
- **What Changes**: System evolves from single-user tool to multi-strategy platform
- **Additional Needs**: Strategy marketplace, performance tracking, multi-account management

*Note: For MVP, focus is exclusively on primary user (the builder). Secondary users represent future vision only.*

---

## MVP Scope

### Core Features

**1. Data Integration Layer** ⭐ FOUNDATION
- TradingView Adapter: Redis/PostgreSQL → Nautilus Bar events (1m/5m OHLCV candles)
- MT5 ZeroMQ Adapter: Real-time bid-ask spreads → Nautilus QuoteTick events
- Historical data loader for backtesting (2-3 years, GOLD/BTC/EUR)
- Data quality validation (gap detection, timestamp sync, anomaly checks)

**2. FTMO Rule Engine** ⭐ CRITICAL
- YAML-based declarative rule configuration
- Real-time validation after every bar (not end-of-day)
- Rules implemented:
  - Max Daily Loss (5% default, configurable)
  - Max Total Drawdown (10% default, configurable)
  - Minimum Trading Days tracking
  - Profit Target tracking
- Preventive order blocking when approaching limits
- Multi-layer risk (strategy-level, account-level, system-level)
- Comprehensive audit logging (every rule check recorded)

**3. Strategy Framework** ⭐ CORE
- Nautilus Strategy base class implementation
- Simple baseline strategy for initial testing (e.g., moving average crossover)
- Event-driven signal generation (responds to bar close events)
- Position sizing logic respecting FTMO constraints
- Support for 3 symbols: GOLD, BTC, EUR on 1m/5m timeframes

**4. Realistic Backtesting Engine** ⭐ VALIDATION
- Nautilus BacktestEngine integration
- Custom execution model:
  - Dynamic spread modeling (time/volatility dependent)
  - Slippage simulation (0.5-2.0 × spread on market orders)
  - Latency delay (200-800ms simulation)
- Walk-forward analysis framework
- Validation report generator (Sharpe, win rate, drawdown, trade frequency)
- Red flag detection (unrealistic metrics that indicate overfitting)

**5. State Management & Persistence**
- Nautilus Cache for real-time state (positions, orders, account)
- Redis backup snapshots (every 5 minutes + on significant events)
- Crash recovery mechanism (restore from last snapshot)
- PostgreSQL for historical trades, performance metrics

**6. Monitoring & Alerts** (Lightweight MVP)
- Nautilus built-in logging (structured JSON logs)
- Telegram bot integration:
  - Trade notifications (entry/exit with P&L)
  - FTMO limit warnings (approaching 70-80% of thresholds)
  - System health alerts (connection drops, errors)
  - Daily summary (trades, P&L, rule status)

**7. Execution Integration**
- MT5 execution via existing ZeroMQ bridge
- Order placement with confirmation tracking
- Slippage monitoring (actual vs. expected)
- Execution quality metrics

### Out of Scope for MVP

**Deferred to Future Phases:**
- ❌ Advanced monitoring dashboard (web UI) → Phase 2
- ❌ Multiple strategy portfolio management → Phase 2
- ❌ Machine learning integration → Phase 3
- ❌ Multi-broker support (only MT5 in MVP) → Phase 3
- ❌ Strategy marketplace/sharing → Phase 4
- ❌ Additional prop firms beyond FTMO → Phase 2
- ❌ Optimization/parameter tuning tools → Phase 2
- ❌ Monte Carlo simulation → Phase 2 (walk-forward sufficient for MVP)

**Explicitly Not Included:**
- ❌ Sub-millisecond latency optimization (not needed for 1m/5m timeframes)
- ❌ Complex infrastructure (Kubernetes, ELK stack, microservices)
- ❌ Tick data storage (use real-time only, spread estimates for backtest)
- ❌ Multiple timeframes (only 1m/5m atomic units in MVP)
- ❌ Options, futures beyond GOLD/BTC/EUR (forex/crypto/metals only)

### MVP Success Criteria

**Technical Validation:**
- ✅ Real-time data flowing from TradingView + MT5 to Nautilus without gaps
- ✅ FTMO rules enforced with zero false negatives (never miss violation)
- ✅ Backtesting completes on 2+ years data with realistic execution model
- ✅ Walk-forward analysis shows consistency (all periods profitable or near-breakeven)
- ✅ System runs 24 hours without crashes during paper trading

**Trading Validation:**
- ✅ Paper trading for 30 days minimum
- ✅ Paper trading results within 20% of backtest metrics
- ✅ Zero FTMO rule violations during paper trading
- ✅ Slippage tracking confirms model assumptions
- ✅ At least 20 trades executed to validate execution quality

**Confidence Gate:**
- ✅ Developer confidence sufficient to risk FTMO challenge fee ($155-$1,080)
- ✅ No critical unknowns or "hope this works" assumptions
- ✅ Clear understanding of failure modes and edge cases

### Future Vision Features

**Phase 2 (Weeks 9-16): Refinement & Expansion**
- Web-based monitoring dashboard (real-time P&L, positions, FTMO limits visualization)
- Multi-strategy framework (portfolio allocation, strategy correlation analysis)
- Advanced risk features (news event detector, volatility regime filter, dynamic position sizing)
- Support for additional prop firms (FTUK, Funded Trader, etc.)

**Phase 3 (Months 6-12): Advanced Capabilities**
- Machine learning integration (regime detection, adaptive parameters, RL position sizing)
- Multi-broker support (IBKR, Oanda, automatic failover)
- Advanced backtesting (Monte Carlo simulation, regime-specific analysis)
- Strategy optimization tools (genetic algorithms, Bayesian optimization)

**Phase 4 (12+ months): Platform Evolution**
- Multi-fund platform (manage multiple FTMO accounts simultaneously)
- Community strategy marketplace (share/sell strategies, backtesting-as-a-service)
- Social features (performance leaderboards, strategy discussions)
- Potential revenue stream (SaaS for other FTMO traders)

---

## Technical Preferences

### Platform & Architecture

**Core Framework:** Nautilus Trader (Python with Rust/Cython core)
- Event-driven message bus (high-performance, type-safe)
- Unified backtesting/live engine
- Professional portfolio and risk management framework

**Data Architecture:** Hybrid TradingView + MT5
- **TradingView (tv-api)**: Primary market data source (OHLCV candles, 2-3 years history)
- **MT5 via ZeroMQ**: Real broker spreads (bid-ask ticks), execution
- **Storage**: Redis (hot data, real-time), PostgreSQL (cold data, historical)
- **Flow**: TV → Redis → Nautilus (bars) + MT5 → ZeroMQ → Nautilus (ticks) → Strategies

**Execution:** MT5 via existing ZeroMQ bridge
- Low latency (~100-300ms)
- Proven infrastructure already operational
- Direct broker connection (FTMO compatible)

**State Management:** Nautilus Cache + Redis Backup
- In-memory performance (Nautilus Cache)
- Durability and recovery (Redis snapshots)
- Historical tracking (PostgreSQL)

**Deployment:** VPS + Docker (production), Local (development)
- Digital Ocean / AWS EC2 for 99.9% uptime
- Docker containers for portability and reproducibility
- Estimated cost: $50-100/month operational

### Performance Requirements

**Latency Target:** 100-500ms (sufficient for 1m/5m timeframes)
- NOT sub-millisecond (unnecessary for intraday retail prop trading)
- Retail prop firm sweet spot

**True Performance Priorities:**
1. **Reliability & Consistency** > Speed (no missed signals, no crashes)
2. **Fast Risk Response** (FTMO breach detection < 100ms)
3. **Slippage Minimization** (execution quality > execution speed)
4. **Parallel Processing** (3 symbols × strategies concurrently)
5. **Data Pipeline Efficiency** (non-blocking indicator calculations)

### Technology Stack

**Core:**
- Python 3.10+ (primary language)
- Nautilus Trader framework (event-driven core)
- Redis 7+ (real-time cache, pub/sub)
- PostgreSQL 14+ (historical data, optional TimescaleDB)

**Integrations:**
- tv-api (existing TradingView infrastructure)
- ZeroMQ (existing MT5 bridge)
- MT5 terminal (broker execution)

**Monitoring:**
- Python logging (structured JSON)
- Telegram Bot API (alerts)
- Future: Prometheus + Grafana (Phase 2)

**Development:**
- Poetry or pip-tools (dependency management)
- pytest (testing framework)
- Docker + docker-compose (containerization)
- Git (version control)

---

## Risks and Assumptions

### Critical Assumptions

**Assumption #1: Nautilus Trader Learning Curve Manageable**
- **Assumption**: Can become productive with Nautilus within 2-4 weeks
- **Risk**: Steeper learning curve than expected delays MVP
- **Mitigation**: Active community support (Discord), comprehensive docs, start with tutorials
- **Validation**: Complete Nautilus hello-world strategy in Week 1

**Assumption #2: TradingView Data Quality Sufficient**
- **Assumption**: TradingView candles via tv-api are reliable and complete enough for backtesting
- **Risk**: Data gaps, bad ticks, or quality issues invalidate backtest results
- **Mitigation**: Data quality validation layer, compare against MT5 data samples
- **Validation**: <1% missing bars, no impossible prices in 2-year historical dataset

**Assumption #3: FTMO Rules Can Be Modeled Accurately**
- **Assumption**: FTMO rules as documented are complete and can be implemented in code
- **Risk**: Undocumented edge cases or rule interpretation differences
- **Mitigation**: Study FTMO community experiences, conservative buffer zones (stop at 80% of limits)
- **Validation**: Paper trading zero violations over 30 days

**Assumption #4: Backtest Will Approximate Live Performance**
- **Assumption**: Realistic execution model (spread, slippage, latency) produces backtest within 20% of live
- **Risk**: Unforeseen execution quality issues or model assumptions incorrect
- **Mitigation**: Conservative assumptions (pessimistic spread/slippage), 30-day paper trading validation
- **Validation**: Paper trading metrics within 20% of backtest

**Assumption #5: Existing Infrastructure Integrates Cleanly**
- **Assumption**: tv-api and MT5 ZeroMQ can be adapted to Nautilus without major rework
- **Risk**: Architectural incompatibilities require infrastructure changes
- **Mitigation**: Adapter pattern isolates integration complexity, fallback to Nautilus-native adapters
- **Validation**: Data flowing end-to-end in Week 2-3 integration tests

### Key Risks

**Risk #1: FTMO Rule Violations During Live Trading** 🔴 CRITICAL
- **Impact**: Account termination, lost challenge fee, wasted development effort
- **Likelihood**: Medium (if rule engine has bugs or edge cases)
- **Mitigation**:
  - Conservative thresholds (stop at 70-80% of limits, not 100%)
  - Comprehensive testing with historical violation scenarios
  - Real-time monitoring with immediate alerts
  - Manual emergency stop capability
- **Contingency**: Paper trade longer (60-90 days) if any validation concerns

**Risk #2: Backtest-Live Divergence** 🔴 HIGH
- **Impact**: Strategy appears profitable in backtest but loses in live trading
- **Likelihood**: Medium-High (common problem in algo trading)
- **Mitigation**:
  - Realistic execution model (dynamic spreads, slippage, latency)
  - Walk-forward validation (out-of-sample testing)
  - 30-day minimum paper trading
  - Conservative assumptions throughout
- **Contingency**: Iterate on execution model based on paper trading, increase paper trading duration

**Risk #3: System Reliability Issues** ⚠️ MEDIUM
- **Impact**: Missed signals, crashes during trading, data connection drops
- **Likelihood**: Medium (complexity inherent in distributed systems)
- **Mitigation**:
  - State persistence (Redis snapshots, crash recovery)
  - Connection monitoring and auto-reconnect
  - Health checks and alerting
  - VPS deployment (99.9% uptime)
- **Contingency**: Start with smaller position sizes, manual monitoring during early live trading

**Risk #4: Learning Curve Delays** ⚠️ MEDIUM
- **Impact**: MVP timeline extends beyond 8 weeks
- **Likelihood**: Medium (Nautilus is complex)
- **Mitigation**:
  - Community support (Discord, GitHub issues)
  - Start simple, iterate complexity
  - Allocate buffer time in schedule
- **Contingency**: Simplify MVP scope, defer non-critical features

**Risk #5: Strategy Performance Insufficient** ⚠️ MEDIUM
- **Impact**: Even with perfect execution, strategy doesn't meet FTMO profit targets
- **Likelihood**: Medium (strategy development is hard)
- **Mitigation**:
  - Focus MVP on infrastructure, not strategy alpha
  - Baseline simple strategy for validation
  - Iterate strategies once platform proven
- **Contingency**: This is a research problem, not an engineering problem - accept longer timeline for strategy development

---

## Timeline Constraints

### Development Phases

**Phase 1: Foundation (Weeks 1-4)**
- Week 1-2: Nautilus learning, environment setup, tutorials
- Week 2-3: TradingView adapter (Redis → Nautilus)
- Week 3-4: MT5 ZeroMQ adapter (spreads → Nautilus)
- Week 4: Integration testing with simple strategy

**Phase 2: Core Systems (Weeks 5-6)**
- Week 5: FTMO rule engine (YAML rules, real-time validation)
- Week 6: Testing with historical violation scenarios

**Phase 3: Validation (Weeks 7-8)**
- Week 7: Realistic execution model (spread, slippage, latency)
- Week 8: Walk-forward analysis framework, validation reports

**Phase 4: Paper Trading (Weeks 9-12+)**
- Week 9-12: Minimum 30 days paper trading
- Daily monitoring, slippage tracking, metrics validation
- Iterate based on results

**Phase 5: Live FTMO (Week 13+)**
- Start with minimum position sizes
- Conservative risk parameters
- Daily reconciliation and monitoring

### Critical Milestones

**Milestone 1: Data Integration Complete (End Week 4)**
- ✅ Real-time candles flowing without gaps
- ✅ Spreads updating from MT5
- ✅ Historical data loadable for backtests

**Milestone 2: FTMO Compliance Proven (End Week 6)**
- ✅ All rules implemented and tested
- ✅ Zero false negatives in historical tests
- ✅ Audit logs comprehensive

**Milestone 3: Backtest Validation (End Week 8)**
- ✅ Realistic execution model built
- ✅ Walk-forward analysis shows consistency
- ✅ No red flag metrics

**Milestone 4: Paper Trading Success (End Week 12+)**
- ✅ 30+ days paper trading complete
- ✅ Metrics within 20% of backtest
- ✅ Zero rule violations
- ✅ Confidence gate passed

**Milestone 5: FTMO Challenge Phase 1 Complete (Variable)**
- ✅ Profit target achieved
- ✅ Zero rule violations
- ✅ Minimum trading days met
- ✅ Ready for Phase 2 challenge

### Dependencies

**Technical Dependencies:**
- Nautilus Trader installation and learning (critical path)
- Existing tv-api and MT5 ZeroMQ operational (prerequisite)
- VPS setup and Docker deployment (can be parallelized)

**Knowledge Dependencies:**
- FTMO rules fully documented (research in Week 1)
- Nautilus architecture understood (learning in Week 1-2)
- Spread/slippage modeling research (Week 7)

**External Dependencies:**
- FTMO challenge availability and fees (external, low risk)
- Broker MT5 access and API stability (existing, low risk)
- TradingView data API reliability (existing, monitored)

---

## Supporting Materials

### Reference Documents

**Brainstorming Session Results (2025-11-25)**
- Comprehensive system design exploration covering architecture, frameworks, validation
- First Principles Thinking: 7 core truths about performance, architecture, data, validation
- Morphological Analysis: 8-parameter systematic evaluation (optimal: "Pragmatic Hybrid Stack")
- Key decisions documented:
  - Framework: Nautilus Trader (confirmed)
  - Data: TradingView + MT5 Hybrid
  - Architecture: Event-driven with custom FTMO rule engine
  - Timeline: 8-week MVP to paper trading
  - Budget: $50-100/month operational cost

### Key Insights from Brainstorming

**Theme 1: Leverage Existing Infrastructure**
- Don't rebuild what works (tv-api, ZeroMQ, Redis/PostgreSQL already operational)
- Integration adapters > full replacement

**Theme 2: Nautilus as Core Framework**
- Event-driven architecture matches trading domain naturally
- 80/20 rule: Nautilus handles 80% infrastructure → focus on 20% differentiation

**Theme 3: FTMO Compliance is Critical**
- Real-time validation, not end-of-day
- Realistic modeling prevents false confidence
- Under-engineering compliance = account failure

**Theme 4: Pragmatic Over Perfect**
- Ship MVP, iterate based on reality
- Avoid over-engineering (no Kubernetes, ELK, etc.)
- Start with Telegram alerts, upgrade to dashboard later

**Theme 5: Validation Before Capital**
- Paper trade 30 days minimum
- Walk-forward backtesting shows robustness
- Forward testing proves real-world validity

---

_This Product Brief captures the vision and requirements for FTMO Trading System._

_It was created through collaborative discovery and reflects the unique needs of this expert technical project._

_Next: The PRD workflow will transform this brief into detailed product requirements from this brief._
