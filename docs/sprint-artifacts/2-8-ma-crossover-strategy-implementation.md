# Story 2.8: MA Crossover Strategy Implementation

Status: done

## Story

As a **trader**,
I want **a Moving Average Crossover strategy**,
So that **I can trade based on trend-following signals**.

## Acceptance Criteria

1. **AC1**: Given I configure an account with `strategy: "ma_crossover"` and `strategy_params: {fast_period: 20, slow_period: 50}`, when the strategy runs, then it calculates 20-period and 50-period Exponential Moving Averages

2. **AC2**: Given the fast MA crosses above the slow MA (bullish crossover), when `on_bar()` is called, then `generate_signal()` returns `SignalType.BUY`

3. **AC3**: Given the fast MA crosses below the slow MA (bearish crossover), when `on_bar()` is called, then `generate_signal()` returns `SignalType.SELL`

4. **AC4**: Given no crossover occurs, when `on_bar()` is called, then `generate_signal()` returns `SignalType.NONE`

5. **AC5**: Given I have an open BUY position, when a SELL signal is generated, then the existing position is closed before opening the new position

6. **AC6**: MACrossoverStrategy inherits from BaseStrategy (Story 2.7) with proper indicator registration

7. **AC7**: Strategy is registered in StrategyRegistry with name "ma_crossover"

8. **AC8**: Unit tests cover MA calculation, crossover detection, and signal generation

## Tasks / Subtasks

### Task 1: Create MACrossoverConfig (AC: 1, 6)
- [x] Create `src/strategies/ma_crossover.py` with MACrossoverConfig
- [x] Inherit from `BaseStrategyConfig` (frozen=True, kw_only=True)
- [x] Add fields: `fast_period: int = 20`, `slow_period: int = 50`
- [x] Add `__post_init__` validation to enforce `slow_period > fast_period` (using msgspec pattern instead of Pydantic):
  ```python
  def __post_init__(self) -> None:
      if self.slow_period <= self.fast_period:
          raise ValueError(f"slow_period ({self.slow_period}) must be > fast_period ({self.fast_period})")
  ```
- [x] Write unit tests for configuration validation (valid and invalid configs)

### Task 2: Create MACrossoverStrategy Class (AC: 1, 6)
- [x] Create MACrossoverStrategy class inheriting from BaseStrategy
- [x] Initialize EMA indicators in `__init__`: `self.fast_ema`, `self.slow_ema`
- [x] Add previous value tracking: `self._prev_fast`, `self._prev_slow`
- [x] **CRITICAL**: Call `super().__init__(config)` in constructor

### Task 3: Implement Indicator Registration (AC: 1, 6)
- [x] Override `on_start()` method
- [x] Call `super().on_start()` first (gets instrument, subscribes to bars)
- [x] **CRITICAL ORDER**: Register indicators BEFORE requesting historical data:
  ```python
  self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
  self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
  ```
- [x] Optionally request historical data: `self.request_bars(self.config.bar_type)`

### Task 3b: Implement on_reset() Method (AC: 6)
- [x] Override `on_reset()` method for indicator reset (NautilusTrader pattern)
- [x] Reset both EMA indicators and previous value tracking:
  ```python
  def on_reset(self) -> None:
      self.fast_ema.reset()
      self.slow_ema.reset()
      self._prev_fast = None
      self._prev_slow = None
  ```
- [x] Add unit test for reset behavior

### Task 4: Implement Crossover Detection (AC: 2, 3, 4)
- [x] Implement `generate_signal(bar: Bar) -> SignalType` method
- [x] Check if both EMAs are initialized: `if not self.fast_ema.initialized or not self.slow_ema.initialized: return SignalType.NONE`
- [x] Get current values: `fast = self.fast_ema.value`, `slow = self.slow_ema.value`
- [x] Detect bullish crossover: `prev_fast <= prev_slow AND fast > slow`
- [x] Detect bearish crossover: `prev_fast >= prev_slow AND fast < slow`
- [x] Update previous values after check
- [x] Return appropriate SignalType

### Task 5: Implement Position Reversal (AC: 5)
- [x] Override `_execute_signal()` to handle reversal with **immediate re-entry**
- [x] When BUY signal and `is_short`: close position AND immediately go long (same bar)
- [x] When SELL signal and `is_long`: close position AND immediately go short (same bar)
- [x] **CRITICAL**: Do NOT return after close - enter immediately to avoid missed entries
- [x] Log reversal actions with EMA values
- [x] Pattern (matches NautilusTrader official ema_cross.py):
  ```python
  def _execute_signal(self, signal: SignalType) -> None:
      if signal == SignalType.BUY:
          if self.is_short:
              self._log.info("Reversing: closing short, entering long")
              self._close_position()
          self._go_long()  # Immediate entry
      elif signal == SignalType.SELL:
          if self.is_long:
              self._log.info("Reversing: closing long, entering short")
              self._close_position()
          self._go_short()  # Immediate entry
  ```

### Task 6: Register Strategy (AC: 7)
- [x] Use `@register_strategy("ma_crossover")` decorator on class
- [x] OR manually register in module: `StrategyRegistry.register("ma_crossover", MACrossoverStrategy)`
- [x] Update `src/strategies/__init__.py` to export MACrossoverStrategy

### Task 7: Write Unit Tests (AC: 8)
- [x] Create `tests/unit/test_ma_crossover.py`
- [x] Test configuration validation (fast < slow)
- [x] Test EMA initialization and warmup
- [x] Test bullish crossover detection (signal = BUY)
- [x] Test bearish crossover detection (signal = SELL)
- [x] Test no crossover (signal = NONE)
- [x] Test position reversal logic
- [x] Test with mock bar data sequence
- [x] Test edge cases: first bar, insufficient data

## Dev Notes

### Quick Reference

**Key Implementation Points:**
- Inherit from `BaseStrategy` (Story 2.7 already complete)
- Use NautilusTrader's `ExponentialMovingAverage` indicator class
- Register indicators BEFORE requesting/subscribing to data
- Track previous EMA values for crossover detection
- Strategy automatically registered via `@register_strategy("ma_crossover")` decorator

**NautilusTrader EMA Pattern (from Context7 2025-12-27):**
```python
from nautilus_trader.indicators.average.ema import ExponentialMovingAverage

# In __init__:
self.fast_ema = ExponentialMovingAverage(config.fast_period)
self.slow_ema = ExponentialMovingAverage(config.slow_period)

# In on_start (AFTER super().on_start()):
self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)
```

**Crossover Detection Logic:**
```python
# Bullish: fast crosses above slow
if self._prev_fast <= self._prev_slow and fast > slow:
    return SignalType.BUY

# Bearish: fast crosses below slow
if self._prev_fast >= self._prev_slow and fast < slow:
    return SignalType.SELL
```

### Architecture Patterns and Constraints

**From Architecture Document (docs/architecture.md):**
```
services/trading-engine/
├── src/
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base_strategy.py     # BaseStrategy class (Story 2.7) ✅
│   │   ├── ma_crossover.py      # NEW: MACrossoverStrategy
│   │   ├── config.py            # BaseStrategyConfig ✅
│   │   ├── position_sizer.py    # PositionSizer ✅
│   │   └── registry.py          # StrategyRegistry ✅
```

**Technology Stack:**
| Component | Technology | Version |
|-----------|------------|---------|
| Trading Framework | NautilusTrader | 1.x (1.200+) |
| Package Manager | uv | Latest |
| Python | Python | 3.11+ |
| EMA Indicator | nautilus_trader.indicators.average.ema | Built-in |

### Technical Requirements

**From Context7 NautilusTrader Research (2025-12-27):**

**1. EMA Crossover Strategy Pattern:**
```python
from nautilus_trader.indicators.average.ema import ExponentialMovingAverage
from nautilus_trader.model.data import Bar
from nautilus_trader.trading.strategy import Strategy

from src.orders.signal import SignalType
from src.strategies.base_strategy import BaseStrategy
from src.strategies.config import BaseStrategyConfig
from src.strategies.registry import register_strategy


class MACrossoverConfig(BaseStrategyConfig, frozen=True, kw_only=True):
    """Configuration for MA Crossover strategy."""
    fast_period: int = 20
    slow_period: int = 50


@register_strategy("ma_crossover")
class MACrossoverStrategy(BaseStrategy):
    """Moving Average Crossover strategy.

    Generates BUY signal on bullish crossover (fast > slow),
    SELL signal on bearish crossover (fast < slow).
    """

    def __init__(self, config: MACrossoverConfig) -> None:
        super().__init__(config)
        # Initialize EMA indicators
        self.fast_ema = ExponentialMovingAverage(config.fast_period)
        self.slow_ema = ExponentialMovingAverage(config.slow_period)
        # Track previous values for crossover detection
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

    def on_start(self) -> None:
        """Called when strategy starts."""
        super().on_start()  # Sets instrument, subscribes to bars

        # Register indicators BEFORE requesting data
        self.register_indicator_for_bars(self.config.bar_type, self.fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self.slow_ema)

        self._log.info(
            f"MACrossover started: fast={self.config.fast_period}, "
            f"slow={self.config.slow_period}"
        )

    def generate_signal(self, bar: Bar) -> SignalType:
        """Generate signal based on EMA crossover."""
        # Wait for indicators to warm up
        if not self.fast_ema.initialized or not self.slow_ema.initialized:
            return SignalType.NONE

        fast = self.fast_ema.value
        slow = self.slow_ema.value

        signal = SignalType.NONE

        # Check for crossover (requires previous values)
        if self._prev_fast is not None and self._prev_slow is not None:
            # Bullish crossover: fast crosses above slow
            if self._prev_fast <= self._prev_slow and fast > slow:
                signal = SignalType.BUY
                self._log.info(f"Bullish crossover: fast={fast:.5f} > slow={slow:.5f}")
            # Bearish crossover: fast crosses below slow
            elif self._prev_fast >= self._prev_slow and fast < slow:
                signal = SignalType.SELL
                self._log.info(f"Bearish crossover: fast={fast:.5f} < slow={slow:.5f}")

        # Update previous values
        self._prev_fast = fast
        self._prev_slow = slow

        return signal
```

**2. Position Reversal Pattern:**
```python
def _execute_signal(self, signal: SignalType) -> None:
    """Execute signal with position reversal support."""
    # Handle reversal: close existing position before reversing
    if signal == SignalType.BUY and self.is_short:
        self._log.info("Closing short position before going long")
        self._close_position()
        # Note: Position will close asynchronously, _go_long called on next signal
        return
    elif signal == SignalType.SELL and self.is_long:
        self._log.info("Closing long position before going short")
        self._close_position()
        return

    # Normal signal execution (from BaseStrategy)
    super()._execute_signal(signal)
```

**3. Indicator Initialization Check:**
```python
# EMA indicators become initialized after receiving enough bars
# fast_ema.initialized = True after fast_period bars
# slow_ema.initialized = True after slow_period bars

# Check both before generating signals:
if not self.fast_ema.initialized or not self.slow_ema.initialized:
    return SignalType.NONE
```

### Existing Codebase Integration

**BaseStrategy (src/strategies/base_strategy.py) - Story 2.7 COMPLETE:**
- Inherits from `nautilus_trader.trading.strategy.Strategy`
- Provides: `is_flat`, `is_long`, `is_short` properties
- Provides: `on_start()`, `on_stop()`, `on_bar()`, `on_event()` lifecycle
- Provides: `_go_long()`, `_go_short()`, `_close_position()` methods
- Abstract method: `generate_signal(bar: Bar) -> SignalType`

**SignalType (src/orders/signal.py) - Story 2.7 COMPLETE:**
```python
class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    NONE = "NONE"
```

**StrategyRegistry (src/strategies/registry.py) - Story 2.7 COMPLETE:**
```python
from src.strategies.registry import register_strategy, StrategyRegistry

@register_strategy("ma_crossover")
class MACrossoverStrategy(BaseStrategy):
    ...

# OR manually:
StrategyRegistry.register("ma_crossover", MACrossoverStrategy)
```

**BaseStrategyConfig (src/strategies/config.py) - Story 2.7 COMPLETE:**
```python
class BaseStrategyConfig(StrategyConfig, frozen=True, kw_only=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal = Decimal("0.1")
    account_id: str = ""
    order_id_tag: str = "001"
```

### File Structure Requirements

```
services/trading-engine/
├── src/
│   ├── strategies/
│   │   ├── __init__.py          # MODIFY: Add MACrossoverStrategy, MACrossoverConfig
│   │   ├── base_strategy.py     # EXISTS (Story 2.7)
│   │   ├── config.py            # EXISTS (Story 2.7)
│   │   ├── ma_crossover.py      # NEW: MACrossoverStrategy
│   │   ├── position_sizer.py    # EXISTS (Story 2.7)
│   │   └── registry.py          # EXISTS (Story 2.7)
├── tests/
│   ├── unit/
│   │   └── test_ma_crossover.py # NEW
```

### Testing Requirements

**Unit Test Example (test_ma_crossover.py):**
```python
import pytest
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch

from src.orders.signal import SignalType
from src.strategies.ma_crossover import MACrossoverConfig, MACrossoverStrategy


class TestMACrossoverConfig:
    def test_default_periods(self):
        config = MACrossoverConfig(
            instrument_id=Mock(),
            bar_type=Mock(),
        )
        assert config.fast_period == 20
        assert config.slow_period == 50

    def test_custom_periods(self):
        config = MACrossoverConfig(
            instrument_id=Mock(),
            bar_type=Mock(),
            fast_period=10,
            slow_period=30,
        )
        assert config.fast_period == 10
        assert config.slow_period == 30


class TestMACrossoverStrategy:
    @pytest.fixture
    def mock_config(self):
        config = Mock(spec=MACrossoverConfig)
        config.fast_period = 20
        config.slow_period = 50
        config.instrument_id = "XAUUSD.BROKER"
        config.bar_type = Mock()
        config.trade_size = Decimal("0.1")
        config.account_id = "test-account"
        return config

    def test_generate_signal_returns_none_when_not_initialized(self, mock_config):
        with patch.object(MACrossoverStrategy, '__init__', lambda x, y: None):
            strategy = MACrossoverStrategy.__new__(MACrossoverStrategy)
            strategy.fast_ema = Mock(initialized=False)
            strategy.slow_ema = Mock(initialized=True)
            strategy._prev_fast = None
            strategy._prev_slow = None

            result = strategy.generate_signal(Mock())
            assert result == SignalType.NONE

    def test_bullish_crossover_returns_buy(self, mock_config):
        with patch.object(MACrossoverStrategy, '__init__', lambda x, y: None):
            strategy = MACrossoverStrategy.__new__(MACrossoverStrategy)
            strategy.fast_ema = Mock(initialized=True, value=51.0)
            strategy.slow_ema = Mock(initialized=True, value=50.0)
            strategy._prev_fast = 49.0  # Was below
            strategy._prev_slow = 50.0
            strategy._log = Mock()

            result = strategy.generate_signal(Mock())
            assert result == SignalType.BUY

    def test_bearish_crossover_returns_sell(self, mock_config):
        with patch.object(MACrossoverStrategy, '__init__', lambda x, y: None):
            strategy = MACrossoverStrategy.__new__(MACrossoverStrategy)
            strategy.fast_ema = Mock(initialized=True, value=49.0)
            strategy.slow_ema = Mock(initialized=True, value=50.0)
            strategy._prev_fast = 51.0  # Was above
            strategy._prev_slow = 50.0
            strategy._log = Mock()

            result = strategy.generate_signal(Mock())
            assert result == SignalType.SELL

    def test_no_crossover_returns_none(self, mock_config):
        with patch.object(MACrossoverStrategy, '__init__', lambda x, y: None):
            strategy = MACrossoverStrategy.__new__(MACrossoverStrategy)
            strategy.fast_ema = Mock(initialized=True, value=52.0)
            strategy.slow_ema = Mock(initialized=True, value=50.0)
            strategy._prev_fast = 51.0  # Still above
            strategy._prev_slow = 50.0
            strategy._log = Mock()

            result = strategy.generate_signal(Mock())
            assert result == SignalType.NONE
```

**Test Execution:**
```bash
# From services/trading-engine directory
cd services/trading-engine

# Install dependencies
uv sync

# Run MA crossover tests
uv run pytest tests/unit/test_ma_crossover.py -v

# Run all strategy tests
uv run pytest tests/unit/ -k strategy -v

# Check code quality
uv run ruff check src/strategies/ma_crossover.py
```

### Previous Story Learnings (Story 2.7)

From Story 2.7 Basic Strategy Framework implementation:

**Key Patterns Established:**
- **BaseStrategy** inherits from NautilusTrader Strategy with `super().__init__(config)`
- **BaseStrategyConfig** uses `frozen=True, kw_only=True` for NautilusTrader compatibility
- **Position state** via `is_flat`, `is_long`, `is_short` properties
- **Signal execution** via `_go_long()`, `_go_short()`, `_close_position()` methods
- **StrategyRegistry** with `@register_strategy()` decorator for dynamic loading

**Implementation Patterns from Story 2.7:**
```python
# Strategy lifecycle
def on_start(self) -> None:
    self._instrument = self.cache.instrument(self.config.instrument_id)
    self.subscribe_bars(self.config.bar_type)

# Position state
@property
def is_flat(self) -> bool:
    return self._position is None

# Order creation
order = self.order_factory.market(
    instrument_id=self.config.instrument_id,
    order_side=OrderSide.BUY,
    quantity=self._instrument.make_qty(self.get_position_size(SignalType.BUY)),
)
self.submit_order(order)
```

**Code Review Fixes Applied in Story 2.7:**
- Fixed deprecated typing patterns (`Type` -> `type`, `Optional` -> `X | None`)
- Fixed import sorting issues
- Created `account_binding.py` for strategy-account binding
- 496 total unit tests passing

### Git Intelligence (Recent Commits)

From commit `b3a023b` (Story 2.7):
- Implemented BaseStrategy with NautilusTrader integration
- Created StrategyRegistry with decorator pattern
- Created PositionSizer with fixed/risk-based sizing
- 496 unit tests passing, all linting clean

**Pattern Continuity:**
- MACrossoverStrategy follows same code style as BaseStrategy
- Uses same Pydantic config pattern with `frozen=True`
- Integrates with existing StrategyRegistry
- Follows existing test patterns with mocks

### Environment Variables Required

```bash
# Trading Engine (already configured from previous stories)
REDIS_URL=redis://localhost:6379
LOG_LEVEL=INFO
```

### Dependencies (pyproject.toml - Already Configured)

```toml
dependencies = [
    "nautilus_trader>=1.200",  # Core trading framework + EMA indicator
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

- New file: `src/strategies/ma_crossover.py` (MACrossoverConfig, MACrossoverStrategy)
- Modify: `src/strategies/__init__.py` (add exports)
- New test: `tests/unit/test_ma_crossover.py`
- Follows existing patterns from BaseStrategy (Story 2.7)
- Prepared for signal filtering (Story 2.9)

### References

- [Source: docs/architecture.md#Trading-Engine-Service] - Strategy framework structure
- [Source: docs/epic-2-context.md#Story-2.8] - MA Crossover technical context with patterns
- [Source: docs/epics.md#Story-2.8] - Original story definition and acceptance criteria
- [Source: docs/sprint-artifacts/2-7-basic-strategy-framework.md] - Previous story patterns and learnings
- [Source: Context7 NautilusTrader 2025-12-27] - Latest EMA indicator and crossover patterns
- [Source: nautilus_trader/examples/strategies/ema_cross.py] - **Official NautilusTrader EMA crossover example** (canonical reference for position reversal pattern)

## Dev Agent Record

### Context Reference

- Epic 2 Context: `docs/epic-2-context.md`
- Architecture: `docs/architecture.md`
- PRD: `docs/prd.md`
- Previous Story: `docs/sprint-artifacts/2-7-basic-strategy-framework.md`

### Agent Model Used

- Story Creation: Claude Opus 4.5 (claude-opus-4-5-20251101)
- Implementation: Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A

### Completion Notes List

- Story created with comprehensive NautilusTrader EMA crossover context from Context7 MCP (2025-12-27)
- EMA indicator patterns documented from latest NautilusTrader docs
- Crossover detection logic with previous value tracking
- Position reversal handling for opposite direction signals
- Full integration with BaseStrategy (Story 2.7) patterns
- All acceptance criteria mapped to specific tasks with code examples
- Test patterns provided with mock examples
- **Implementation complete (2025-12-27):**
  - Used `__post_init__` for config validation (msgspec pattern) instead of Pydantic `@field_validator`
  - Correct EMA import: `from nautilus_trader.indicators import ExponentialMovingAverage`
  - Tests use standalone logic validation due to NautilusTrader's Rust-based Strategy class limitations
  - All 28 unit tests pass, 524 total tests pass (no regressions)
  - Linting passes with no errors

### File List

Files created:
- `services/trading-engine/src/strategies/ma_crossover.py` - MACrossoverConfig, MACrossoverStrategy
- `services/trading-engine/tests/unit/test_ma_crossover.py` - 31 unit tests (including on_reset tests)

Files modified:
- `services/trading-engine/src/strategies/__init__.py` - Added MACrossoverStrategy, MACrossoverConfig exports

---

## Verification Checklist

### Manual Test Steps

```bash
# 1. Ensure you're in the trading-engine directory
cd services/trading-engine

# 2. Install dependencies
uv sync

# 3. Run unit tests
uv run pytest tests/unit/test_ma_crossover.py -v

# 4. Check code quality
uv run ruff check src/strategies/ma_crossover.py

# 5. Verify imports and registration work
uv run python -c "
from src.strategies import MACrossoverStrategy, MACrossoverConfig
from src.strategies.registry import StrategyRegistry
print('Strategy registered:', 'ma_crossover' in StrategyRegistry.list_available())
print('Imports successful!')
"
```

### Acceptance Criteria Verification

- [x] **AC1**: Strategy calculates fast/slow EMAs from config periods
- [x] **AC2**: Bullish crossover (fast crosses above slow) returns BUY
- [x] **AC3**: Bearish crossover (fast crosses below slow) returns SELL
- [x] **AC4**: No crossover returns NONE
- [x] **AC5**: Position reversal closes existing position before reversing
- [x] **AC6**: MACrossoverStrategy inherits from BaseStrategy with proper indicator registration
- [x] **AC7**: Strategy registered in StrategyRegistry as "ma_crossover"
- [x] **AC8**: Unit tests cover all crossover scenarios (31 tests)

---

## Definition of Done

- [x] `src/strategies/ma_crossover.py` implements MACrossoverConfig and MACrossoverStrategy
- [x] MACrossoverConfig has `__post_init__` validation for `slow_period > fast_period`
- [x] MACrossoverStrategy inherits from BaseStrategy with `super().__init__(config)`
- [x] EMA indicators registered in `on_start()` before data subscription
- [x] `on_reset()` method implemented to reset indicators
- [x] Crossover detection with previous value tracking
- [x] Position reversal with **immediate re-entry** (close and enter same bar)
- [x] Strategy registered with `@register_strategy("ma_crossover")` decorator
- [x] All unit tests pass (31 tests)
- [x] Linting passes: `uv run ruff check src/strategies/ma_crossover.py`
- [x] Story status updated to `done` after code review

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-27 | Story created with comprehensive NautilusTrader EMA crossover context by create-story workflow |
| 2025-12-27 | Context7 MCP research: EMA indicator patterns, crossover detection, position reversal |
| 2025-12-27 | Full implementation patterns provided with test examples |
| 2025-12-27 | Integration with BaseStrategy (Story 2.7) documented |
| 2025-12-27 | **Implementation completed**: MACrossoverConfig, MACrossoverStrategy, 28 unit tests, all passing |
| 2025-12-27 | **Code Review (H4 fix)**: Added 3 unit tests for `on_reset()` method (now 31 total tests) |
| 2025-12-27 | **Code Review (M3 fix)**: Marked all AC verification and DoD checkboxes complete |
| 2025-12-27 | **Code Review (H1 fix)**: Updated DoD to reflect `__post_init__` pattern (not `@field_validator`) |
| 2025-12-27 | **Code Review**: Story status updated to `done` |
