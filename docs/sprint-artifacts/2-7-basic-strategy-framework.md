# Story 2.7: Basic Strategy Framework

Status: Done

## Story

As a **developer**,
I want **a base strategy class that integrates with Nautilus Trader**,
So that **I can implement trading strategies consistently**.

## Acceptance Criteria

1. **AC1**: Given I create a new strategy class, when I inherit from `BaseStrategy`, then I have access to:
   - `on_bar(bar)` - Called when new bar arrives
   - `on_tick(tick)` - Called when new tick arrives
   - `generate_signal()` - Returns BUY, SELL, or None
   - `get_position_size(signal)` - Returns lot size for the signal
   - `account` - Reference to the account this strategy runs on

2. **AC2**: Given a strategy is attached to an account, when the account receives market data, then the data is routed to the strategy's appropriate handler

3. **AC3**: Given a strategy generates a signal, when `generate_signal()` returns BUY or SELL, then the engine creates an order and sends it for execution

4. **AC4**: BaseStrategy inherits from NautilusTrader Strategy class with proper initialization

5. **AC5**: Signal enum includes BUY, SELL, CLOSE, NONE types

6. **AC6**: Position sizer calculates lot size based on account balance and risk parameters

7. **AC7**: Unit tests cover base strategy lifecycle, signal generation, and position sizing

## Tasks / Subtasks

### Task 1: Create Signal Enum Extension (AC: 5)
- [x] **ALREADY EXISTS**: `src/orders/signal.py` has SignalType enum with BUY, SELL, CLOSE
- [x] Add `NONE` type to SignalType enum for no-signal case
- [x] Update Signal dataclass to support optional signal (when NONE)
- [x] Write unit tests for NONE signal type

### Task 2: Create BaseStrategyConfig (AC: 1, 4)
- [x] Create `src/strategies/config.py` with BaseStrategyConfig Pydantic model
- [x] Inherit from NautilusTrader's StrategyConfig
- [x] Define fields: instrument_id, bar_type, trade_size, account_id
- [x] Add validation for required fields
- [x] Write unit tests for configuration validation

### Task 3: Create BaseStrategy Class (AC: 1, 4)
- [x] Create `src/strategies/base_strategy.py` with BaseStrategy class
- [x] Inherit from `nautilus_trader.trading.strategy.Strategy`
- [x] **CRITICAL**: Call `super().__init__(config)` in `__init__`
- [x] Implement `on_start()` - subscribe to bars, register indicators
- [x] Implement `on_stop()` - unsubscribe, cleanup
- [x] Implement `on_bar(bar: Bar)` - call generate_signal, execute if needed
- [x] Implement `on_tick(tick)` - pass to subclass if overridden
- [x] Implement abstract `generate_signal(bar) -> SignalType` method
- [x] Add `account` property for account reference
- [x] Add `instrument` property for instrument reference

### Task 4: Implement Position State Properties (AC: 1)
- [x] Add `is_flat` property (no open position)
- [x] Add `is_long` property (long position open)
- [x] Add `is_short` property (short position open)
- [x] Add `position` property to track current position
- [x] Handle position events (PositionOpened, PositionClosed)

### Task 5: Implement Signal Execution (AC: 3)
- [x] Implement `_execute_signal(signal: SignalType)` method
- [x] On BUY signal + is_flat: create market buy order via order_factory
- [x] On SELL signal + is_flat: create market sell order
- [x] On CLOSE signal + not is_flat: close current position
- [x] Use `self.submit_order(order)` to send orders
- [x] Log signal execution with price and quantity

### Task 6: Create PositionSizer (AC: 6)
- [x] Create `src/strategies/position_sizer.py` with PositionSizer class
- [x] Implement `calculate_size(account_balance, risk_percent, stop_loss_pips)` method
- [x] Implement `get_lot_size(signal, current_price)` method
- [x] Add min/max lot size constraints
- [x] Support fixed lot size mode (for prop firm accounts)
- [x] Write unit tests for position sizing calculations

### Task 7: Create Strategy Registry (AC: 2)
- [x] Create `src/strategies/registry.py` with StrategyRegistry class
- [x] Implement `register(name: str, strategy_class: Type[BaseStrategy])` method
- [x] Implement `get(name: str) -> Type[BaseStrategy]` method
- [x] Pre-register built-in strategies (prepare for Story 2.8)
- [x] Support dynamic strategy loading from configuration

### Task 8: Integrate with Account Model (AC: 2)
- [x] **ALREADY EXISTS**: Account model has `strategy: str` field at `src/accounts/models.py:79`
- [x] Implement strategy instantiation from account configuration using StrategyRegistry
- [x] Route Bar data from RedisAdapter to account's strategy via callback
- [x] Route Tick data from ZmqAdapter to account's strategy via callback
- [x] Write integration tests for data routing

### Task 9: Write Unit Tests (AC: 7)
- [x] Create `tests/unit/test_base_strategy.py` - BaseStrategy lifecycle
- [x] Create `tests/unit/test_position_sizer.py` - Position sizing logic
- [x] Create `tests/unit/test_strategy_registry.py` - Registry operations
- [x] Test signal generation flow with mock bars
- [x] Test position state transitions
- [x] Test order creation from signals

### Task 10: Update Module Exports (AC: 1, 5, 6)
- [x] Update `src/strategies/__init__.py` to export:
  - BaseStrategy, BaseStrategyConfig
  - PositionSizer
  - StrategyRegistry
- [x] Update `src/orders/signal.py` to include NONE type

## Dev Notes

### Quick Reference (Executive Summary)

**Key Implementation Points:**
- **BaseStrategy** inherits from `nautilus_trader.trading.strategy.Strategy`
- **CRITICAL**: Always call `super().__init__(config)` in strategy constructor
- Register indicators BEFORE requesting/subscribing to data
- Use `order_factory.market()` for market orders, `submit_order()` to execute
- Track position state via `is_flat`, `is_long`, `is_short` properties
- SignalType enum already exists in `src/orders/signal.py` - just add NONE

**NautilusTrader Strategy Lifecycle:**
```
on_start() → subscribe_bars() → [bars arrive] → on_bar() → generate_signal() → submit_order()
                                                                    ↓
                                              on_event() ← PositionOpened/PositionClosed
```

**Position State Pattern (from Context7 2025-12-23):**
```python
@property
def is_flat(self) -> bool:
    return self.position is None

@property
def is_long(self) -> bool:
    return self.position and self.position.side == PositionSide.LONG

@property
def is_short(self) -> bool:
    return self.position and self.position.side == PositionSide.SHORT
```

### Architecture Patterns and Constraints

**From Architecture Document (docs/architecture.md):**

```
services/trading-engine/
├── src/
│   ├── strategies/              # Trading strategies
│   │   ├── __init__.py
│   │   ├── base_strategy.py     # Base class with compliance
│   │   ├── ma_crossover.py      # Example strategy (Story 2.8)
│   │   └── position_sizer.py    # Account-aware sizing
```

**Strategy Framework Requirements:**
| Component | Purpose |
|-----------|---------|
| `base_strategy.py` | NautilusTrader Strategy base with signal generation |
| `position_sizer.py` | Calculate lot sizes based on account/risk |
| `registry.py` | Dynamic strategy registration and loading |

### Technical Requirements

**From Context7 NautilusTrader Research (2025-12-23):**

**1. Strategy Configuration Pattern:**
```python
from decimal import Decimal
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import BarType, InstrumentId
from nautilus_trader.trading.strategy import Strategy

class BaseStrategyConfig(StrategyConfig):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal
    order_id_tag: str

class BaseStrategy(Strategy):
    def __init__(self, config: BaseStrategyConfig) -> None:
        super().__init__(config)  # CRITICAL: Must call parent
        self.position = None
```

**2. Indicator Registration Pattern (CRITICAL ORDER):**
```python
def on_start(self) -> None:
    # 1. Get instrument reference
    self.instrument = self.cache.instrument(self.instrument_id)

    # 2. Register indicators BEFORE requesting data
    self.register_indicator_for_bars(self.bar_type, self.fast_ema)
    self.register_indicator_for_bars(self.bar_type, self.slow_ema)

    # 3. Request historical data (indicators auto-updated)
    self.request_bars(self.bar_type)

    # 4. Subscribe to live data
    self.subscribe_bars(self.bar_type)
```

**3. Order Factory Pattern:**
```python
def go_long(self) -> None:
    if not self.is_flat:
        return

    order = self.order_factory.market(
        instrument_id=self.config.instrument_id,
        order_side=OrderSide.BUY,
        quantity=self.trade_size,
    )
    self.submit_order(order)
    self._log.info(f"Going LONG at {self.clock.utc_now()}")

def go_short(self) -> None:
    if not self.is_flat:
        return

    order = self.order_factory.market(
        instrument_id=self.config.instrument_id,
        order_side=OrderSide.SELL,
        quantity=self.trade_size,
    )
    self.submit_order(order)
```

**4. Position Event Handling:**
```python
from nautilus_trader.core.message import Event
from nautilus_trader.model.events import PositionOpened, PositionClosed

def on_event(self, event: Event) -> None:
    if isinstance(event, PositionOpened):
        self.position = self.cache.position(event.position_id)
        self._log.info(f"Position opened: {self.position.side} @ {self.position.avg_px_open}")
    elif isinstance(event, PositionClosed):
        if self.position and self.position.id == event.position_id:
            pnl = self.position.realized_pnl
            self._log.info(f"Position closed with PnL: {pnl}")
            self.position = None
```

**5. Close Position Pattern:**
```python
def close_position(self) -> None:
    if self.position:
        self.close_position(self.position)  # NautilusTrader built-in method

# Or close all positions for instrument:
self.close_all_positions(self.config.instrument_id)
```

### Existing Codebase Integration

**SignalType Enum (src/orders/signal.py) - ALREADY EXISTS:**

> **Note: SignalType vs Signal Relationship**
> - `SignalType` (enum): Simple enum for signal direction (BUY, SELL, CLOSE, NONE)
> - `Signal` (dataclass): Full signal object with type, symbol, strategy, timestamp, metadata
> - Strategies return `SignalType` from `generate_signal()` for simplicity
> - The `Signal` dataclass (also in signal.py) is used for external communication/logging

```python
class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    # ADD: NONE = "NONE"  # For no-signal case (strategies return this when no action needed)
```

**Bar Model (src/adapters/redis_models.py) - ALREADY EXISTS:**
- Bar class with symbol, timeframe, OHLCV fields
- `from_json()` for parsing Redis messages
- `channel_name` property

**Integration Points:**
- Strategy receives Bar from RedisAdapter via callback
- Strategy receives Tick from ZmqAdapter (Story 2.4)
- Strategy sends orders via OrderExecutionService (Story 2.5)

**Data Routing Patterns (CRITICAL for AC2):**

```python
# Bar routing from RedisAdapter to Account's Strategy
# In AccountManager or Engine setup:
async def setup_bar_routing(accounts: list[Account], redis_adapter: RedisAdapter):
    async def route_bar_to_accounts(bar: Bar) -> None:
        for account in accounts:
            if account.status != "active":
                continue
            # Check symbol filter
            allowed_symbols = [s.upper() for s in account.signal_filter.symbols]
            if bar.symbol.upper() in allowed_symbols:
                account.strategy.on_bar(bar)

    redis_adapter.set_bar_callback(route_bar_to_accounts)

# Tick routing from ZmqAdapter to Account's Strategy
# In AccountManager or Engine setup:
async def setup_tick_routing(accounts: list[Account], zmq_adapter: ZmqAdapter):
    async def route_tick_to_accounts(tick: Tick) -> None:
        for account in accounts:
            if account.status != "active":
                continue
            # Route tick to strategy if it has on_tick handler
            if hasattr(account.strategy, 'on_tick'):
                account.strategy.on_tick(tick)

    zmq_adapter.set_tick_callback(route_tick_to_accounts)
```

### File Structure Requirements

```
services/trading-engine/
├── src/
│   ├── strategies/
│   │   ├── __init__.py          # Module exports
│   │   ├── base_strategy.py     # NEW: BaseStrategy class
│   │   ├── config.py            # NEW: BaseStrategyConfig
│   │   ├── position_sizer.py    # NEW: PositionSizer class
│   │   └── registry.py          # NEW: StrategyRegistry
│   ├── orders/
│   │   └── signal.py            # MODIFY: Add NONE to SignalType
│   └── accounts/
│       └── models.py            # MODIFY: Add strategy field
├── tests/
│   ├── unit/
│   │   ├── test_base_strategy.py    # NEW
│   │   ├── test_position_sizer.py   # NEW
│   │   └── test_strategy_registry.py # NEW
│   └── integration/
│       └── test_strategy_integration.py  # NEW (optional)
```

### Expected Implementation Patterns

**BaseStrategyConfig:**

> **CRITICAL: `frozen=True` is MANDATORY** for NautilusTrader StrategyConfig subclasses.
> This ensures configuration immutability after instantiation, which NautilusTrader
> requires for proper strategy lifecycle management and serialization.

```python
from decimal import Decimal
from typing import Optional

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model import BarType, InstrumentId


class BaseStrategyConfig(StrategyConfig, frozen=True):  # frozen=True REQUIRED!
    """Base configuration for all trading strategies.

    Attributes:
        instrument_id: Instrument to trade (e.g., "XAUUSD.BROKER")
        bar_type: Bar type for data subscription
        trade_size: Default trade quantity
        account_id: Associated account ID
    """

    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal = Decimal("0.1")
    account_id: str = ""
    order_id_tag: str = "001"
```

**BaseStrategy:**
```python
from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from nautilus_trader.core.message import Event
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide, PositionSide
from nautilus_trader.model.events import PositionClosed, PositionOpened
from nautilus_trader.trading.strategy import Strategy

from src.orders.signal import SignalType
from src.strategies.config import BaseStrategyConfig

if TYPE_CHECKING:
    from nautilus_trader.model import Position


class BaseStrategy(Strategy):
    """Base class for all trading strategies.

    Provides common functionality for signal generation, position
    management, and order execution. Subclasses must implement
    the `generate_signal()` method.

    Example:
        class MyStrategy(BaseStrategy):
            def generate_signal(self, bar: Bar) -> SignalType:
                if some_condition:
                    return SignalType.BUY
                return SignalType.NONE
    """

    def __init__(self, config: BaseStrategyConfig) -> None:
        super().__init__(config)  # CRITICAL: Initialize parent
        self._position: Position | None = None
        self._instrument = None

    # Position state properties
    @property
    def is_flat(self) -> bool:
        """Check if no position is open."""
        return self._position is None

    @property
    def is_long(self) -> bool:
        """Check if long position is open."""
        return self._position is not None and self._position.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        """Check if short position is open."""
        return self._position is not None and self._position.side == PositionSide.SHORT

    @property
    def position(self) -> Position | None:
        """Current open position, if any."""
        return self._position

    @property
    def instrument(self):
        """Cached instrument reference."""
        return self._instrument

    # Lifecycle methods
    def on_start(self) -> None:
        """Called when strategy starts."""
        # Get instrument reference
        self._instrument = self.cache.instrument(self.config.instrument_id)
        if self._instrument is None:
            self.log.error(f"Instrument not found: {self.config.instrument_id}")
            self.stop()
            return

        # Subscribe to bar data
        self.subscribe_bars(self.config.bar_type)
        self.log.info(f"Strategy {self.id} started, subscribed to {self.config.bar_type}")

    def on_stop(self) -> None:
        """Called when strategy stops."""
        self.unsubscribe_bars(self.config.bar_type)
        self.log.info(f"Strategy {self.id} stopped")

    def on_bar(self, bar: Bar) -> None:
        """Process incoming bar data."""
        signal = self.generate_signal(bar)
        if signal != SignalType.NONE:
            self._execute_signal(signal)

    def on_event(self, event: Event) -> None:
        """Handle position events."""
        if isinstance(event, PositionOpened):
            self._position = self.cache.position(event.position_id)
            self.log.info(f"Position opened: {self._position.side} @ {self._position.avg_px_open}")
        elif isinstance(event, PositionClosed):
            if self._position and self._position.id == event.position_id:
                pnl = self._position.realized_pnl
                self.log.info(f"Position closed with PnL: {pnl}")
                self._position = None

    # Abstract method for subclasses
    @abstractmethod
    def generate_signal(self, bar: Bar) -> SignalType:
        """Generate trading signal from bar data.

        Args:
            bar: Latest bar data

        Returns:
            SignalType indicating action (BUY, SELL, CLOSE, or NONE)
        """
        raise NotImplementedError

    # Signal execution
    def _execute_signal(self, signal: SignalType) -> None:
        """Execute trading signal."""
        if signal == SignalType.BUY:
            self._go_long()
        elif signal == SignalType.SELL:
            self._go_short()
        elif signal == SignalType.CLOSE:
            self._close_position()

    def _go_long(self) -> None:
        """Enter long position."""
        if not self.is_flat:
            return

        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self._instrument.make_qty(float(self.config.trade_size)),
        )
        self.submit_order(order)
        self.log.info(f"Going LONG with {self.config.trade_size}")

    def _go_short(self) -> None:
        """Enter short position."""
        if not self.is_flat:
            return

        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=self._instrument.make_qty(float(self.config.trade_size)),
        )
        self.submit_order(order)
        self.log.info(f"Going SHORT with {self.config.trade_size}")

    def _close_position(self) -> None:
        """Close current position."""
        if self._position:
            self.close_all_positions(self.config.instrument_id)
            self.log.info("Closing position")
```

**PositionSizer:**
```python
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class PositionSizerConfig(BaseModel):
    """Configuration for position sizing.

    Attributes:
        risk_percent: Risk per trade as % of balance (default 1%)
        max_lot_size: Maximum allowed lot size
        min_lot_size: Minimum allowed lot size
        fixed_lot_size: Fixed size (overrides risk calculation if set)
    """

    risk_percent: Decimal = Field(default=Decimal("1.0"), ge=0, le=100)
    max_lot_size: Decimal = Field(default=Decimal("10.0"), gt=0)
    min_lot_size: Decimal = Field(default=Decimal("0.01"), gt=0)
    fixed_lot_size: Optional[Decimal] = None


class PositionSizer:
    """Calculates position sizes based on risk parameters.

    Supports:
    - Fixed lot sizing (for prop firm accounts)
    - Risk-based sizing (% of balance at risk)
    - Min/max lot size constraints

    Example:
        sizer = PositionSizer(PositionSizerConfig(risk_percent=2.0))
        lot_size = sizer.calculate_size(
            account_balance=100000,
            stop_loss_pips=20,
            pip_value=10.0
        )
    """

    def __init__(self, config: Optional[PositionSizerConfig] = None):
        self.config = config or PositionSizerConfig()

    def calculate_size(
        self,
        account_balance: Decimal,
        stop_loss_pips: Decimal,
        pip_value: Decimal = Decimal("10.0"),
    ) -> Decimal:
        """Calculate lot size based on risk parameters.

        Args:
            account_balance: Current account balance
            stop_loss_pips: Stop loss distance in pips
            pip_value: Value per pip per lot (default $10 for gold)

        Returns:
            Calculated lot size within min/max constraints
        """
        # Use fixed size if configured
        if self.config.fixed_lot_size is not None:
            return self._apply_constraints(self.config.fixed_lot_size)

        # Calculate risk amount
        risk_amount = account_balance * (self.config.risk_percent / Decimal("100"))

        # Calculate lot size: risk_amount / (stop_loss_pips * pip_value)
        if stop_loss_pips <= 0 or pip_value <= 0:
            return self.config.min_lot_size

        lot_size = risk_amount / (stop_loss_pips * pip_value)
        return self._apply_constraints(lot_size)

    def get_fixed_size(self) -> Decimal:
        """Get fixed lot size for simple strategies."""
        if self.config.fixed_lot_size is not None:
            return self._apply_constraints(self.config.fixed_lot_size)
        return self.config.min_lot_size

    def _apply_constraints(self, lot_size: Decimal) -> Decimal:
        """Apply min/max constraints to lot size."""
        lot_size = max(lot_size, self.config.min_lot_size)
        lot_size = min(lot_size, self.config.max_lot_size)
        # Round to 2 decimal places
        return round(lot_size, 2)
```

**StrategyRegistry (Task 7):**
```python
from __future__ import annotations

from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from src.strategies.base_strategy import BaseStrategy


class StrategyRegistry:
    """Registry for dynamic strategy loading.

    Maintains a mapping of strategy names to strategy classes,
    enabling configuration-driven strategy instantiation.

    Example:
        # Register strategies
        StrategyRegistry.register("ma_crossover", MACrossoverStrategy)

        # Get strategy class from config
        strategy_class = StrategyRegistry.get(account.strategy)
        strategy = strategy_class(config)
    """

    _strategies: dict[str, Type[BaseStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: Type[BaseStrategy]) -> None:
        """Register a strategy class by name.

        Args:
            name: Strategy name (used in account config)
            strategy_class: Strategy class (must inherit BaseStrategy)
        """
        cls._strategies[name] = strategy_class

    @classmethod
    def get(cls, name: str) -> Type[BaseStrategy]:
        """Get a registered strategy class by name.

        Args:
            name: Strategy name from configuration

        Returns:
            Strategy class

        Raises:
            ValueError: If strategy name not registered
        """
        if name not in cls._strategies:
            available = ", ".join(cls._strategies.keys()) or "none"
            raise ValueError(
                f"Strategy '{name}' not registered. Available: {available}"
            )
        return cls._strategies[name]

    @classmethod
    def list_available(cls) -> list[str]:
        """List all registered strategy names."""
        return list(cls._strategies.keys())


# Strategy registration decorator (optional convenience)
def register_strategy(name: str):
    """Decorator to register a strategy class.

    Example:
        @register_strategy("my_strategy")
        class MyStrategy(BaseStrategy):
            ...
    """
    def decorator(cls: Type[BaseStrategy]) -> Type[BaseStrategy]:
        StrategyRegistry.register(name, cls)
        return cls
    return decorator
```

### Testing Requirements

**Unit Test Example (test_base_strategy.py):**
```python
import pytest
from decimal import Decimal
from unittest.mock import Mock, MagicMock

from src.strategies.base_strategy import BaseStrategy
from src.strategies.config import BaseStrategyConfig
from src.orders.signal import SignalType


class ConcreteStrategy(BaseStrategy):
    """Concrete implementation for testing."""

    def __init__(self, config, signal_to_return=SignalType.NONE):
        super().__init__(config)
        self._signal_to_return = signal_to_return

    def generate_signal(self, bar):
        return self._signal_to_return


class TestBaseStrategy:
    @pytest.fixture
    def mock_config(self):
        config = Mock(spec=BaseStrategyConfig)
        config.instrument_id = "XAUUSD.BROKER"
        config.bar_type = "XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"
        config.trade_size = Decimal("0.1")
        return config

    def test_is_flat_when_no_position(self, mock_config):
        strategy = ConcreteStrategy(mock_config)
        strategy._position = None
        assert strategy.is_flat is True
        assert strategy.is_long is False
        assert strategy.is_short is False

    def test_generate_signal_called_on_bar(self, mock_config):
        strategy = ConcreteStrategy(mock_config, SignalType.BUY)
        strategy._instrument = Mock()
        strategy._instrument.make_qty = Mock(return_value=Mock())
        strategy.order_factory = Mock()
        strategy.submit_order = Mock()
        strategy.log = Mock()

        mock_bar = Mock()
        strategy.on_bar(mock_bar)

        # BUY signal should trigger _go_long
        strategy.order_factory.market.assert_called_once()


class TestPositionSizer:
    def test_fixed_lot_size(self):
        from src.strategies.position_sizer import PositionSizer, PositionSizerConfig

        config = PositionSizerConfig(fixed_lot_size=Decimal("0.5"))
        sizer = PositionSizer(config)

        result = sizer.calculate_size(
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("20"),
        )

        assert result == Decimal("0.5")

    def test_risk_based_sizing(self):
        from src.strategies.position_sizer import PositionSizer, PositionSizerConfig

        config = PositionSizerConfig(risk_percent=Decimal("1.0"))
        sizer = PositionSizer(config)

        # 1% of $100,000 = $1000 risk
        # $1000 / (20 pips * $10/pip) = 5 lots
        result = sizer.calculate_size(
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("20"),
            pip_value=Decimal("10.0"),
        )

        assert result == Decimal("5.0")
```

**Test Execution:**
```bash
# From services/trading-engine directory
cd services/trading-engine

# Install dependencies
uv sync

# Run unit tests
uv run pytest tests/unit/test_base_strategy.py -v
uv run pytest tests/unit/test_position_sizer.py -v

# Run all strategy tests
uv run pytest tests/unit/ -k strategy -v

# Check code quality
uv run ruff check src/strategies/
```

### Previous Story Learnings (Story 2.6)

From Story 2.6 Redis Market Data Subscription implementation:

**Key Patterns Established:**
- **Pydantic models** for all data structures with validation
- **Async context manager** pattern for adapters
- **Bar model** in `src/adapters/redis_models.py` ready for use
- Bar callback mechanism via `set_bar_callback()` in RedisAdapter

**Integration Point (from RedisAdapter):**
```python
# In RedisAdapter:
def set_bar_callback(self, callback: Callable[[Bar], None] | None) -> None:
    self._on_bar_callback = callback

# Strategy receives bars via this callback
```

### Git Intelligence (Recent Commits)

From commit `a17cf6a` (Story 2.6):
- Created RedisAdapter with async pub/sub
- Bar model with Pydantic validation
- Callback mechanism for bar routing
- 390 unit tests passing

**Pattern Continuity:**
- BaseStrategy follows same code style as adapters
- Pydantic for configuration validation
- Async patterns where applicable
- Comprehensive unit test coverage

### Environment Variables Required

```bash
# Trading Engine (already configured)
REDIS_URL=redis://localhost:6379

# Logging
LOG_LEVEL=INFO
```

### Dependencies (pyproject.toml - Already Configured)

```toml
dependencies = [
    "nautilus_trader>=1.200",  # Core trading framework
    "redis>=5.0",
    "pyzmq>=25.0",
    "sqlalchemy>=2.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "pyyaml>=6.0",
    "typer>=0.9",
]
```

### Project Structure Notes

- New files in `src/strategies/`: `base_strategy.py`, `config.py`, `position_sizer.py`, `registry.py`
- Modify `src/orders/signal.py` to add NONE to SignalType
- Follows existing patterns from adapters module
- BaseStrategy prepared for MA Crossover (Story 2.8) and signal filtering (Story 2.9)

### References

- [Source: docs/architecture.md#Trading-Engine-Service] - Strategy framework structure
- [Source: docs/architecture.md#Key-Components] - Strategy components definition
- [Source: docs/epic-2-context.md#Story-2.7] - Story technical context with patterns
- [Source: docs/epics.md#Story-2.7] - Original story definition and acceptance criteria
- [Source: docs/sprint-artifacts/2-6-redis-market-data-subscription.md] - Previous story patterns
- [Source: Context7 NautilusTrader 2025-12-23] - Latest Strategy patterns, indicators, position management

## Dev Agent Record

### Context Reference

- Epic 2 Context: `docs/epic-2-context.md`
- Architecture: `docs/architecture.md`
- PRD: `docs/prd.md`
- Previous Story: `docs/sprint-artifacts/2-6-redis-market-data-subscription.md`

### Agent Model Used

- Story Creation: Claude Opus 4.5 (claude-opus-4-5-20251101)
- Implementation: Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A

### Completion Notes List

- Story created with comprehensive NautilusTrader context from Context7 MCP (2025-12-23)
- Strategy lifecycle patterns documented: on_start, on_bar, on_stop, on_event
- Position state management patterns: is_flat, is_long, is_short
- Order factory patterns for market orders
- Indicator registration order (register BEFORE request data)
- PositionSizer with fixed and risk-based sizing modes
- Integration with existing SignalType enum and Bar model
- All acceptance criteria mapped to specific tasks with code examples

**Implementation Notes (2025-12-27):**
- ✅ Implemented BaseStrategy inheriting from NautilusTrader Strategy class
- ✅ Added SignalType.NONE to signal.py with is_none() method
- ✅ Created BaseStrategyConfig with frozen=True, kw_only=True for NautilusTrader compatibility
- ✅ Implemented position state properties (is_flat, is_long, is_short)
- ✅ Implemented signal execution flow (_go_long, _go_short, _close_position)
- ✅ Created PositionSizer with fixed and risk-based sizing modes
- ✅ Created StrategyRegistry with register_strategy decorator
- ✅ Created StrategyDataRouter for Bar/Tick routing to account strategies
- ✅ 109 new tests added (484 total unit tests passing)
- ✅ All linting checks pass

**Code Review Fixes (2025-12-27):**
- ✅ Created account_binding.py with BoundAccount and bind_strategy_to_account (fixes Task 8 strategy instantiation)
- ✅ Fixed deprecated typing patterns (Type→type, Optional→X|None, timezone.utc→UTC)
- ✅ Fixed import sorting in config.py
- ✅ Fixed line too long in base_strategy.py docstring
- ✅ Updated imports in data_router.py (collections.abc instead of typing)
- ✅ 12 additional tests for account binding (496 total unit tests passing)
- ✅ All linting checks pass with extended ruleset (E,W,S,B,I,C4,UP,PL)

### File List

Files created:
- `services/trading-engine/src/strategies/base_strategy.py` - BaseStrategy class
- `services/trading-engine/src/strategies/config.py` - BaseStrategyConfig
- `services/trading-engine/src/strategies/position_sizer.py` - PositionSizer class
- `services/trading-engine/src/strategies/registry.py` - StrategyRegistry class
- `services/trading-engine/src/strategies/data_router.py` - StrategyDataRouter class
- `services/trading-engine/src/strategies/account_binding.py` - BoundAccount, bind_strategy_to_account
- `services/trading-engine/tests/unit/test_base_strategy.py` - 27 tests
- `services/trading-engine/tests/unit/test_position_sizer.py` - 24 tests
- `services/trading-engine/tests/unit/test_strategy_registry.py` - 18 tests
- `services/trading-engine/tests/unit/test_strategy_config.py` - 9 tests
- `services/trading-engine/tests/unit/test_data_router.py` - 14 tests
- `services/trading-engine/tests/unit/test_account_binding.py` - 12 tests

Files modified:
- `services/trading-engine/src/strategies/__init__.py` - Export new classes including BoundAccount
- `services/trading-engine/src/orders/signal.py` - Add NONE to SignalType, modernize typing
- `services/trading-engine/tests/unit/test_signal.py` - Add NONE tests (17 tests total)

---

## Verification Checklist

### Manual Test Steps

```bash
# 1. Ensure you're in the trading-engine directory
cd services/trading-engine

# 2. Install dependencies
uv sync

# 3. Run unit tests
uv run pytest tests/unit/test_base_strategy.py tests/unit/test_position_sizer.py -v

# 4. Check code quality
uv run ruff check src/strategies/

# 5. Verify imports work
uv run python -c "
from src.strategies import BaseStrategy, BaseStrategyConfig, PositionSizer
from src.orders.signal import SignalType
print('SignalType.NONE:', SignalType.NONE)
print('Imports successful!')
"
```

### Acceptance Criteria Verification

- [x] **AC1**: BaseStrategy provides on_bar, on_tick, generate_signal, get_position_size, account
- [x] **AC2**: Strategy attached to account receives routed market data (via StrategyDataRouter)
- [x] **AC3**: Signal generation triggers order creation and execution
- [x] **AC4**: BaseStrategy inherits from NautilusTrader Strategy with super().__init__
- [x] **AC5**: SignalType includes BUY, SELL, CLOSE, NONE
- [x] **AC6**: PositionSizer calculates lot sizes correctly (24 tests)
- [x] **AC7**: Unit tests pass for all components (109 strategy-related tests)

---

## Definition of Done

- [x] `src/strategies/base_strategy.py` implements BaseStrategy with lifecycle handlers
- [x] `src/strategies/config.py` implements BaseStrategyConfig with validation
- [x] `src/strategies/position_sizer.py` implements PositionSizer with risk calculations
- [x] `src/strategies/registry.py` implements StrategyRegistry for dynamic loading
- [x] `src/strategies/account_binding.py` implements BoundAccount and bind_strategy_to_account
- [x] SignalType.NONE added to `src/orders/signal.py`
- [x] Position state properties (is_flat, is_long, is_short) implemented
- [x] Signal execution flow creates and submits orders
- [x] Strategy instantiation from account config via StrategyRegistry
- [x] All unit tests pass (496 unit tests, 121 strategy-related)
- [x] Linting passes: `uv run ruff check src/strategies/`
- [x] Story status updated to `done` (code review complete)

---

## Troubleshooting

### Common Issues

**NautilusTrader Import Errors**
```bash
# Ensure nautilus_trader is installed
uv run python -c "import nautilus_trader; print(nautilus_trader.__version__)"

# If not installed:
uv add nautilus_trader>=1.200
```

**Strategy Not Receiving Bars**
```python
# Ensure on_start subscribes correctly
def on_start(self):
    self.subscribe_bars(self.config.bar_type)  # Must match channel

# Verify bar_type format
# "XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"
```

**Position State Not Updating**
```python
# Ensure on_event handles PositionOpened/PositionClosed
def on_event(self, event):
    if isinstance(event, PositionOpened):
        self._position = self.cache.position(event.position_id)
```

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-23 | Story created with comprehensive NautilusTrader context by create-story workflow |
| 2025-12-23 | Context7 MCP research: Strategy patterns, indicator registration, position management |
| 2025-12-23 | Full implementation patterns provided with test examples |
| 2025-12-23 | Integration with existing SignalType and Bar model documented |
| 2025-12-23 | **Validation Review (SM Agent):** Applied 6 improvements: (1) Fixed Task 8 - strategy field already exists in Account model; (2) Added Data Routing Patterns for Bar/Tick from adapters to strategy; (3) Added StrategyRegistry implementation example with decorator; (4) Added `frozen=True` mandatory note for StrategyConfig; (5) Clarified SignalType vs Signal relationship; (6) Added validation report at `validation-report-2-7-20251223.md` |
| 2025-12-27 | **Implementation Complete:** All tasks completed. Created BaseStrategy, BaseStrategyConfig, PositionSizer, StrategyRegistry, StrategyDataRouter. Added 109 new tests. All 484 unit tests passing, linting clean. Status updated to Ready for Review. |
| 2025-12-27 | **Code Review Fixes:** Created account_binding.py (BoundAccount, bind_strategy_to_account) to complete Task 8 strategy instantiation. Fixed 14 linting issues (deprecated typing patterns, import sorting). Added 12 tests for account binding. Total: 496 unit tests passing. Status updated to Done. |
