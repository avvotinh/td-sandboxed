# Tech-Spec: Epic 4 - Strategy Framework

**Created:** 2025-12-04
**Status:** Ready for Development
**Epic:** 4 - Strategy Framework
**Service:** trading-engine (Python/Nautilus Trader)

---

## Overview

### Problem Statement

The trading-engine needs a clean, extensible framework for implementing trading strategies that:
1. Integrates seamlessly with Nautilus Trader's event-driven architecture
2. Automatically enforces FTMO compliance rules before every order
3. Calculates position sizes that respect risk limits and drawdown constraints
4. Supports multiple symbols (GOLD, BTC, EUR) concurrently
5. Logs every trade decision with full context for debugging and analysis

Without this framework, developers would need to manually wire up compliance checks, risk calculations, and logging for every strategy - leading to inconsistency, bugs, and potential FTMO rule violations.

### Solution

Build an **FTMO-aware Strategy Framework** consisting of:

1. **FTMOBaseStrategy** - Base class extending Nautilus `Strategy` with built-in compliance validation
2. **FTMOPositionSizer** - Risk-based position sizing that respects FTMO limits
3. **MACrossoverStrategy** - Reference implementation demonstrating framework patterns
4. **Multi-Symbol Manager** - Concurrent tracking of positions across GOLD, BTC, EUR
5. **Trade Decision Logger** - Structured JSON logging of every signal, order, and decision

### Scope

**In Scope:**
- Story 4.1: FTMO Base Strategy Class
- Story 4.2: FTMO Position Sizer
- Story 4.3: MA Crossover Example Strategy
- Story 4.4: Multi-Symbol Management
- Story 4.5: Trade Decision Logging
- FRs: FR18, FR19, FR20, FR21, FR22, FR23, FR24, FR25, FR26

**Out of Scope:**
- Epic 3 (FTMO Compliance Engine) - assumed complete as dependency
- Epic 2 (Adapters) - assumed complete as dependency
- Additional strategy implementations beyond MA Crossover
- Backtesting integration (Epic 5)
- Live/Paper trading modes (Epic 8)

**Dependencies:**
- Epic 2 complete: Redis adapter, ZeroMQ adapter, TimescaleDB adapter
- Epic 3 complete: FTMORuleEngine, validators, audit logger

---

## Context for Development

### Codebase Patterns

**Nautilus Trader Strategy Pattern (from latest docs):**

```python
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from decimal import Decimal

class MyStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for strategy - immutable after creation"""
    instrument_id: InstrumentId
    bar_type: BarType
    fast_ema_period: int = 10
    slow_ema_period: int = 20
    trade_size: Decimal

class MyStrategy(Strategy):
    def __init__(self, config: MyStrategyConfig) -> None:
        super().__init__(config)  # Config available via self.config

    def on_start(self) -> None:
        # Register indicators BEFORE requesting data
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
        self.request_bars(self.config.bar_type)  # Historical -> on_historical_data
        self.subscribe_bars(self.config.bar_type)  # Live -> on_bar

    def on_bar(self, bar: Bar) -> None:
        # Indicators auto-updated before this is called
        pass

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        self.close_all_positions(self.config.instrument_id)
```

**EMA Indicator Usage:**

```python
from nautilus_trader.indicators.average.ema import ExponentialMovingAverage

# Initialize
self.fast_ema = ExponentialMovingAverage(period=20)
self.slow_ema = ExponentialMovingAverage(period=50)

# Access values (after indicator initialized)
current_fast = self.fast_ema.value  # Latest value
previous_fast = self.fast_ema.value  # Use deque for history if needed
```

**Position Sizing Pattern:**

```python
def calculate_position_size(
    self,
    entry_price: Decimal,
    stop_price: Decimal,
    account_balance: Decimal,
    risk_percent: Decimal = Decimal("0.01")  # 1% risk
) -> Decimal:
    risk_amount = account_balance * risk_percent
    price_diff = abs(entry_price - stop_price)
    position_size = risk_amount / price_diff
    return min(position_size, self.MAX_POSITION_SIZE)
```

**Portfolio Access:**

```python
# Account and position information
account = self.portfolio.account(venue)
balance = account.balance_total().as_decimal()
unrealized_pnl = self.portfolio.unrealized_pnl(instrument_id)
realized_pnl = self.portfolio.realized_pnl(instrument_id)
is_flat = self.portfolio.is_flat(instrument_id)
net_position = self.portfolio.net_position(instrument_id)
```

### Files to Reference

**Existing Architecture (from docs/architecture.md):**
```
services/trading-engine/
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── strategies/           # <-- Epic 4 focus
│   │   ├── __init__.py
│   │   ├── base_strategy.py  # Story 4.1
│   │   ├── position_sizer.py # Story 4.2
│   │   └── ma_crossover.py   # Story 4.3
│   ├── adapters/             # Epic 2 (dependency)
│   ├── risk/                 # Epic 3 (dependency)
│   │   ├── ftmo_rules.py
│   │   └── validators.py
│   └── config/
├── tests/
│   ├── unit/
│   │   └── strategies/
│   └── integration/
└── pyproject.toml
```

**Epic 3 Interface (assumed from docs/epics-trading-engine.md):**

```python
# Expected interface from FTMORuleEngine (Epic 3)
class FTMORuleEngine:
    def validate_order(self, order: Order, context: dict) -> ValidationResult
    def get_daily_loss_percent(self) -> Decimal
    def get_drawdown_percent(self) -> Decimal
    def is_trading_allowed(self) -> bool

@dataclass
class ValidationResult:
    passed: bool
    layer: str  # "strategy", "account", "system"
    rule: str
    reason: str
    current_value: Decimal
    threshold: Decimal
```

### Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Base class | Extend `nautilus_trader.trading.Strategy` | Required for Nautilus integration |
| Config pattern | Pydantic `StrategyConfig` subclass | Type safety, validation, immutability |
| Position sizing | Risk-based with FTMO cap | Prevents single trade from violating limits |
| Indicator library | Nautilus built-in indicators | Auto-registration, historical warmup |
| Logging format | Structured JSON | Machine-parseable, queryable |
| Multi-symbol | Single strategy instance, multiple subscriptions | Simpler state management |

---

## Implementation Plan

### Tasks

#### Story 4.1: FTMO Base Strategy Class

- [ ] **Task 4.1.1**: Create `src/strategies/__init__.py` with exports
- [ ] **Task 4.1.2**: Create `FTMOBaseStrategyConfig` extending `StrategyConfig`
  - Fields: `instrument_ids`, `bar_type`, `risk_per_trade_percent`, `max_position_size`
- [ ] **Task 4.1.3**: Create `FTMOBaseStrategy` class extending `Strategy`
  - Inject `FTMORuleEngine` dependency
  - Implement `submit_order_with_compliance()` method
  - Implement `get_compliant_position_size()` method
  - Implement `publish_alert()` method for notifications
- [ ] **Task 4.1.4**: Implement lifecycle hooks
  - `on_start()`: Initialize state, subscribe to data
  - `on_stop()`: Cancel orders, close positions, cleanup
  - `on_save()`/`on_load()`: State persistence for crash recovery
- [ ] **Task 4.1.5**: Add structured logging for all trade decisions
- [ ] **Task 4.1.6**: Write unit tests for base strategy class

#### Story 4.2: FTMO Position Sizer

- [ ] **Task 4.2.1**: Create `src/strategies/position_sizer.py`
- [ ] **Task 4.2.2**: Implement `FTMOPositionSizer` class
  ```python
  class FTMOPositionSizer:
      def calculate_size(
          self,
          entry_price: Decimal,
          stop_loss_price: Decimal,
          account_balance: Decimal,
          current_daily_loss_percent: Decimal,
          current_drawdown_percent: Decimal,
          risk_per_trade_percent: Decimal = Decimal("0.01"),
          max_daily_loss_percent: Decimal = Decimal("0.05"),
          max_drawdown_percent: Decimal = Decimal("0.10"),
      ) -> PositionSizeResult
  ```
- [ ] **Task 4.2.3**: Implement dynamic size reduction when approaching limits
  - If daily loss > 3.5%: reduce size by 50%
  - If daily loss > 4.0%: reduce size by 75%
  - If daily loss > 4.5%: block new positions
- [ ] **Task 4.2.4**: Add pip value calculation per symbol
  - GOLD (XAUUSD): $0.10 per 0.01 lot per pip
  - BTC (BTCUSD): Variable based on price
  - EUR (EURUSD): $0.10 per 0.01 lot per pip
- [ ] **Task 4.2.5**: Write unit tests for position sizer with edge cases

#### Story 4.3: MA Crossover Example Strategy

- [ ] **Task 4.3.1**: Create `src/strategies/ma_crossover.py`
- [ ] **Task 4.3.2**: Implement `MACrossoverConfig`
  ```python
  class MACrossoverConfig(FTMOBaseStrategyConfig, frozen=True):
      fast_ema_period: int = 20
      slow_ema_period: int = 50
      atr_period: int = 14
      atr_multiplier: Decimal = Decimal("2.0")  # For stop loss
  ```
- [ ] **Task 4.3.3**: Implement `MACrossoverStrategy` extending `FTMOBaseStrategy`
  - Initialize EMA indicators in `__init__`
  - Register indicators in `on_start()`
  - Detect crossovers in `on_bar()`
  - Generate signals with stop loss (ATR-based)
- [ ] **Task 4.3.4**: Implement entry logic
  - BUY: fast EMA crosses above slow EMA
  - SELL: fast EMA crosses below slow EMA
  - Skip if already in position for symbol
- [ ] **Task 4.3.5**: Implement exit logic
  - Stop loss: Entry - (ATR * multiplier) for long
  - Take profit: Entry + (ATR * multiplier * 2) for long
  - Reverse on opposite signal
- [ ] **Task 4.3.6**: Write integration tests with mock data

#### Story 4.4: Multi-Symbol Management

- [ ] **Task 4.4.1**: Extend `FTMOBaseStrategy` to handle multiple instruments
- [ ] **Task 4.4.2**: Create symbol-specific state tracking
  ```python
  @dataclass
  class SymbolState:
      instrument_id: InstrumentId
      position_side: PositionSide | None
      entry_price: Decimal | None
      stop_loss: Decimal | None
      take_profit: Decimal | None
      unrealized_pnl: Decimal
  ```
- [ ] **Task 4.4.3**: Implement aggregate exposure calculation
  ```python
  def get_total_exposure(self) -> Decimal:
      """Sum notional value across all positions"""
  ```
- [ ] **Task 4.4.4**: Add per-symbol configuration support
  ```yaml
  symbols:
    GOLD:
      timeframe: 1m
      risk_percent: 1.0
      max_size: 0.5  # lots
    BTC:
      timeframe: 5m
      risk_percent: 0.5
      max_size: 0.1
  ```
- [ ] **Task 4.4.5**: Update compliance checks for aggregate exposure
- [ ] **Task 4.4.6**: Write tests for concurrent symbol management

#### Story 4.5: Trade Decision Logging

- [ ] **Task 4.5.1**: Create `src/strategies/trade_logger.py`
- [ ] **Task 4.5.2**: Define `TradeDecision` schema
  ```python
  @dataclass
  class TradeDecision:
      timestamp: datetime
      event: str  # "signal", "entry", "exit", "skip"
      decision: str  # "ENTER_LONG", "EXIT_SHORT", "SKIP_COMPLIANCE", etc.
      symbol: str
      strategy: str
      signal: dict  # Indicator values that triggered
      market: dict  # Bid, ask, spread at decision time
      order: dict | None  # Order details if submitted
      compliance: dict  # FTMO metrics at decision time
      reason: str | None  # Why skipped if applicable
  ```
- [ ] **Task 4.5.3**: Implement `TradeDecisionLogger` class
  - Log to structlog (JSON format)
  - Persist to TimescaleDB `trade_decisions` table
  - Publish to Redis for notification service
- [ ] **Task 4.5.4**: Create database migration for `trade_decisions` table
  ```sql
  CREATE TABLE trade_decisions (
      id UUID PRIMARY KEY,
      timestamp TIMESTAMPTZ NOT NULL,
      event VARCHAR(20) NOT NULL,
      decision VARCHAR(50) NOT NULL,
      symbol VARCHAR(20) NOT NULL,
      strategy VARCHAR(100) NOT NULL,
      signal JSONB,
      market JSONB,
      order_details JSONB,
      compliance JSONB,
      reason TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
  );
  SELECT create_hypertable('trade_decisions', 'timestamp');
  ```
- [ ] **Task 4.5.5**: Integrate logger into `FTMOBaseStrategy`
- [ ] **Task 4.5.6**: Write tests for logging functionality

---

### Acceptance Criteria

#### Story 4.1: FTMO Base Strategy Class

- [ ] **AC 4.1.1**: Given I create a strategy inheriting from `FTMOBaseStrategy`, When I call `submit_order_with_compliance(order)`, Then compliance is validated before submission
- [ ] **AC 4.1.2**: Given compliance check fails, When order is submitted, Then order is rejected with specific reason and audit log entry created
- [ ] **AC 4.1.3**: Given compliance check passes, When order is submitted, Then order is forwarded to execution adapter
- [ ] **AC 4.1.4**: Given strategy provides `get_position_size(entry, stop_loss)`, When called, Then returns FTMO-compliant size
- [ ] **AC 4.1.5**: Given strategy calls `publish_alert()`, Then alert is sent to notification service via Redis

#### Story 4.2: FTMO Position Sizer

- [ ] **AC 4.2.1**: Given account balance $100,000, risk 1%, entry $1850, stop $1840, When calculating size, Then size = $1000 / $10 = 100 units (0.1 lots)
- [ ] **AC 4.2.2**: Given calculated size exceeds max position limit, When sizing runs, Then size is capped at maximum
- [ ] **AC 4.2.3**: Given daily loss at 4% of 5% limit, When calculating size, Then size is reduced by 50%
- [ ] **AC 4.2.4**: Given daily loss at 4.75% of 5% limit, When calculating size, Then returns zero (blocked)

#### Story 4.3: MA Crossover Example Strategy

- [ ] **AC 4.3.1**: Given fast EMA (20) crosses above slow EMA (50), When `on_bar()` is called, Then BUY signal is generated
- [ ] **AC 4.3.2**: Given fast EMA crosses below slow EMA, When `on_bar()` is called, Then SELL signal is generated
- [ ] **AC 4.3.3**: Given signal generated, When order submitted, Then stop loss is set at entry - (ATR * 2)
- [ ] **AC 4.3.4**: Given strategy is backtested on 1 year of data, When results analyzed, Then strategy produces trades (validates infrastructure)

#### Story 4.4: Multi-Symbol Management

- [ ] **AC 4.4.1**: Given strategy configured for ["GOLD", "BTC", "EUR"], When started, Then subscribes to data for all symbols
- [ ] **AC 4.4.2**: Given GOLD generates signal, When order submitted, Then BTC and EUR positions unaffected
- [ ] **AC 4.4.3**: Given all three symbols have positions, When aggregate exposure checked, Then total calculated across all
- [ ] **AC 4.4.4**: Given aggregate exposure at limit, When new position attempted, Then blocked with reason

#### Story 4.5: Trade Decision Logging

- [ ] **AC 4.5.1**: Given trade signal generated, When decision made, Then JSON log entry created with full context
- [ ] **AC 4.5.2**: Given order blocked by compliance, When logged, Then includes block reason and threshold values
- [ ] **AC 4.5.3**: Given trade decision logged, When queried from TimescaleDB, Then all fields present and queryable
- [ ] **AC 4.5.4**: Given verbose logging enabled, When strategy runs, Then every bar evaluation is logged

---

## Additional Context

### Dependencies

| Dependency | Type | Source | Status |
|------------|------|--------|--------|
| Nautilus Trader 1.x | Library | PyPI | Available |
| FTMORuleEngine | Internal | Epic 3 | Required |
| RedisDataAdapter | Internal | Epic 2 | Required |
| ZMQExecutionAdapter | Internal | Epic 2 | Required |
| TimescaleDBAdapter | Internal | Epic 2 | Required |
| structlog | Library | PyPI | Available |
| pydantic | Library | PyPI | Available |

### Testing Strategy

**Unit Tests (pytest):**
- `test_ftmo_base_strategy.py` - Base class methods, compliance integration
- `test_position_sizer.py` - Size calculations, edge cases, limit scenarios
- `test_ma_crossover.py` - Signal generation, crossover detection
- `test_trade_logger.py` - Log formatting, persistence

**Integration Tests:**
- `test_strategy_with_mock_adapters.py` - Full flow with mocked Redis/ZMQ
- `test_multi_symbol_concurrent.py` - Concurrent symbol handling

**Test Fixtures:**
```python
@pytest.fixture
def mock_rule_engine():
    """Returns FTMORuleEngine with configurable responses"""

@pytest.fixture
def sample_bar_data():
    """Returns 100 bars of GOLD 1m data for testing"""

@pytest.fixture
def mock_portfolio():
    """Returns Portfolio with configurable balance/positions"""
```

### Configuration Example

```yaml
# config/strategies/ma_crossover.yaml
strategy:
  name: ma_crossover
  class: src.strategies.ma_crossover.MACrossoverStrategy

  # Common settings
  risk_per_trade_percent: 1.0
  max_total_exposure: 50000  # USD

  # MA Crossover specific
  fast_ema_period: 20
  slow_ema_period: 50
  atr_period: 14
  atr_multiplier: 2.0

  # Symbols
  symbols:
    - instrument_id: "XAUUSD.FTMO"
      bar_type: "XAUUSD.FTMO-1-MINUTE-LAST-INTERNAL"
      max_position_size: 0.5  # lots

    - instrument_id: "BTCUSD.FTMO"
      bar_type: "BTCUSD.FTMO-5-MINUTE-LAST-INTERNAL"
      max_position_size: 0.1

    - instrument_id: "EURUSD.FTMO"
      bar_type: "EURUSD.FTMO-1-MINUTE-LAST-INTERNAL"
      max_position_size: 1.0
```

### Notes

1. **Indicator Warmup**: Strategies should wait for indicators to be initialized (check `indicator.initialized`) before generating signals

2. **Order ID Generation**: Use format `{strategy_id}-{symbol}-{timestamp}` for traceability

3. **State Recovery**: Implement `on_save()`/`on_load()` for crash recovery - store open positions, pending orders, indicator state

4. **Logging Levels**:
   - INFO: Trade entries/exits, signals acted upon
   - DEBUG: Every bar evaluation, indicator values
   - WARNING: Compliance blocks, size reductions
   - ERROR: Execution failures, connection issues

5. **Performance Considerations**:
   - EMA indicators are O(1) per update
   - Position sizer calculations are O(1)
   - Avoid database writes on every bar - batch or use Redis cache

---

**Tech-Spec Complete!**

Saved to: `docs/sprint-artifacts/tech-spec-epic-4-strategy-framework.md`

**Recommended:** Run `/bmad:bmm:workflows:quick-dev` with this tech-spec in a fresh context for implementation.
