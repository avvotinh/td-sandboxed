# Story 4.7: Real-Time P&L Tracking

Status: Done

## Story

As a **trader**,
I want **my P&L tracked in real-time**,
So that **rule calculations use accurate current values**.

## Acceptance Criteria

1. **AC1**: Given an account has open positions, when new ticks arrive, then unrealized P&L is recalculated and equity is updated.

2. **AC2**: Given a trade is executed, when the execution confirmation returns, then realized P&L is updated, daily P&L is updated, and balance is updated.

3. **AC3**: Given a position is closed, when the close confirmation returns, then the closed P&L is added to daily totals and the position is removed from open positions.

4. **AC4**: Given I request account status, when I view P&L metrics, then I see: current equity (balance + unrealized P&L), daily P&L (realized + unrealized today), and total drawdown percentage.

5. **AC5**: Given the P&L tracker receives a tick update, when processing completes, then the processing time is under 10ms (performance requirement for real-time responsiveness).

6. **AC6**: Given multiple accounts are tracking P&L simultaneously, when updates occur for one account, then other accounts' P&L states are completely unaffected (risk isolation).

## Tasks / Subtasks

### Task 1: Create PnLTracker Class (AC: 1-4, 6)

- [x] 1.1: Create new file `src/accounts/pnl_tracker.py`
- [x] 1.2: Define `PnLTracker` class with constructor parameters:
  - `account_id: str` - Account identifier
  - `initial_balance: Decimal` - Starting balance for calculations
  - `risk_registry: RiskStateRegistry` - For updating risk state
- [x] 1.3: Define `Position` dataclass for tracking open positions:
  ```python
  @dataclass
  class Position:
      position_id: str  # order_id from original order
      symbol: str
      side: OrderSide  # BUY or SELL
      volume: Decimal  # Remaining open volume
      entry_price: Decimal  # Average entry price
      current_price: Decimal  # Last mark-to-market price
      unrealized_pnl: Decimal  # Cached unrealized P&L
      open_time: datetime
  ```
- [x] 1.4: Implement internal state tracking:
  - `_positions: dict[str, Position]` - Open positions by position_id
  - `_daily_realized_pnl: Decimal` - Realized P&L accumulated today
  - `_current_equity: Decimal` - Balance + unrealized P&L
  - `_last_tick_time: datetime` - For performance monitoring
- [x] 1.5: Implement `calculate_unrealized_pnl(position: Position, current_price: Decimal) -> Decimal`:
  - For LONG: `(current_price - entry_price) * volume * multiplier`
  - For SHORT: `(entry_price - current_price) * volume * multiplier`
  - Use Decimal for precision (no float math)
  - See Dev Notes: **P&L CALCULATION FORMULAS** and **INSTRUMENT MULTIPLIER HANDLING** sections

### Task 2: Implement Tick Update Handler (AC: 1, 5)

- [x] 2.1: Implement `async on_tick(symbol: str, bid: Decimal, ask: Decimal) -> None`:
  **NOTE:** ZmqAdapter yields Tick with float bid/ask - convert to Decimal at method boundary using `Decimal(str(bid))`
  - Find all positions matching symbol
  - Use bid for SHORT positions, ask for LONG positions (mark-to-market)
  - Recalculate unrealized P&L for each position
  - Update total unrealized P&L
  - Update current equity
- [x] 2.2: Call `_risk_registry.update_account_equity(account_id, new_equity)` after update
- [x] 2.3: Add performance timing (measure processing time, log warning if > 10ms)
- [x] 2.4: Handle case where tick symbol has no open positions (no-op, fast path)

### Task 3: Implement Trade Execution Handler (AC: 2)

- [x] 3.1: Implement `async on_trade_executed(order_result: OrderResult, order: Order) -> None`:
  - Create new Position from Order + OrderResult
  - Calculate entry price from fill_price
  - Store in `_positions` with order_id as key
  - Log position opened
- [x] 3.2: Update balance in Redis via `_redis.save_account_balance(account_id, new_balance)`
- [x] 3.3: Recalculate equity after position added
- [x] 3.4: Handle partial fills (volume tracking)

### Task 4: Implement Position Close Handler (AC: 3)

- [x] 4.1: Implement `async on_position_closed(position_id: str, close_price: Decimal, realized_pnl: Decimal) -> None`:
  - Remove position from `_positions`
  - Add realized_pnl to `_daily_realized_pnl`
  - Update balance: `balance += realized_pnl`
- [x] 4.2: Call `_risk_registry.record_account_trade(account_id, realized_pnl)`
- [x] 4.3: Update Redis balance
- [x] 4.4: Recalculate equity (now without closed position's unrealized)
- [x] 4.5: Log position closed with P&L details

### Task 5: Implement Metrics Getter (AC: 4)

- [x] 5.1: Implement `get_pnl_metrics() -> PnLMetrics`:
  ```python
  @dataclass
  class PnLMetrics:
      current_equity: Decimal
      balance: Decimal
      unrealized_pnl: Decimal
      daily_pnl: Decimal  # realized + unrealized today
      daily_pnl_percent: Decimal
      total_drawdown_percent: Decimal
      open_positions_count: int
  ```
- [x] 5.2: Calculate daily_pnl = `_daily_realized_pnl + sum(unrealized_pnl for all positions)`
- [x] 5.3: Calculate daily_pnl_percent using daily_starting_balance from RiskState
- [x] 5.4: Get total_drawdown_percent from RiskState

### Task 6: Integrate with ZmqAdapter (AC: 1-3)

- [x] 6.1: Create `PnLTrackerRegistry` class in `src/accounts/pnl_registry.py`:
  - Maps account_id -> PnLTracker
  - `get_or_create(account_id) -> PnLTracker`
  - `on_tick_all(symbol, bid, ask)` - broadcasts to relevant trackers
  - `get_open_positions_count(account_id) -> int` - for ValidatedZmqAdapter
  - `get_total_exposure(account_id) -> Decimal` - for ValidatedZmqAdapter
- [x] 6.2: Register PnLTrackerRegistry with ZmqAdapter for tick routing
- [x] 6.3: Modify `ZmqAdapter.receive_ticks()` to call pnl_registry on each tick
- [x] 6.4: Integrate with `ValidatedZmqAdapter` - on order execution, notify PnLTracker:
  ```
  Integration Flow:
  ValidatedZmqAdapter.send_order_and_wait(order)
      -> ZmqAdapter.send_order_and_wait() -> OrderResult
      -> ValidatedZmqAdapter calls pnl_registry.get(order.account_id).on_trade_executed(result, order)
  ```

### Task 7: Integration with AccountMetricsService (AC: 4)

- [x] 7.1: Update `AccountMetricsService.get_account_metrics()` to use PnLTracker for real-time metrics
- [x] 7.2: Verify `AccountMetrics.unrealized_pnl` computed property uses accurate equity from PnLTracker (property already exists at line 45-48 of metrics.py)
- [x] 7.3: Include open_positions_count in metrics
- [x] 7.4: Ensure metrics service fallback when PnLTracker not available

### Task 8: Unit Tests (AC: 1-6)

- [x] 8.1: Create `tests/unit/test_pnl_tracker.py`
- [x] 8.2: Test unrealized P&L calculation for LONG position (price up = profit)
- [x] 8.3: Test unrealized P&L calculation for SHORT position (price down = profit)
- [x] 8.4: Test equity update on tick (equity = balance + unrealized)
- [x] 8.5: Test daily realized P&L accumulation on position close
- [x] 8.6: Test daily P&L = realized + unrealized
- [x] 8.7: Test tick with no matching positions (fast no-op)
- [x] 8.8: Test Decimal precision (no floating point errors)
- [x] 8.9: Test account isolation (update one tracker doesn't affect another)

### Task 9: Integration Tests (AC: 1-6)

- [x] 9.1: Create `tests/integration/test_pnl_tracking.py`
- [x] 9.2: Test full flow: open position -> tick update -> P&L changes
- [x] 9.3: Test full flow: open -> tick -> close -> realized P&L correct
- [x] 9.4: Test multiple positions on same symbol
- [x] 9.5: Test concurrent tick updates for multiple accounts
- [x] 9.6: Test integration with RiskStateRegistry (equity updates propagate)
- [x] 9.7: Test integration with AccountMetricsService (metrics include P&L)
- [x] 9.8: Performance test: 1000 ticks processed in < 10 seconds (< 10ms each)

### Task 10: Documentation (AC: 1-6)

- [x] 10.1: Add docstrings to PnLTracker and all methods
- [x] 10.2: Document Position dataclass fields
- [x] 10.3: Add inline comments for P&L calculation formulas
- [x] 10.4: Document integration points with other components

## Dev Notes

### CRITICAL: FULL FILE PATHS (Monorepo Structure)

**All paths are relative to project root `/home/hopdev/Dev/Sandboxed/`:**

| Full Path | Action | Purpose |
|-----------|--------|---------|
| **New Files** | | |
| `services/trading-engine/src/accounts/pnl_tracker.py` | CREATE | PnLTracker, Position, PnLMetrics |
| `services/trading-engine/src/accounts/pnl_registry.py` | CREATE | PnLTrackerRegistry |
| `services/trading-engine/tests/unit/test_pnl_tracker.py` | CREATE | Unit tests |
| `services/trading-engine/tests/integration/test_pnl_tracking.py` | CREATE | Integration tests |
| **Modify Files** | | |
| `services/trading-engine/src/accounts/__init__.py` | MODIFY | Add pnl_tracker exports |
| `services/trading-engine/src/accounts/metrics.py` | VERIFY | Confirm unrealized_pnl property works with PnLTracker equity |
| `services/trading-engine/src/accounts/metrics_service.py` | MODIFY | Integrate PnLTracker |
| `services/trading-engine/src/adapters/zmq_adapter.py` | MODIFY | Route ticks to PnL registry |

### PREREQUISITES (Story 3.5 and 4.6 Complete)

**Story 3.5** (Per-Account Risk Isolation):
- RiskState dataclass with daily_pnl, daily_pnl_percent, current_equity, peak_equity, total_drawdown_percent, daily_starting_balance, last_updated
- RiskStateRegistry for per-account state management
- AccountRiskManager with update_equity() and record_trade_pnl() methods

**Story 4.6** (Rule Validation Before Trade):
- ValidatedZmqAdapter wraps order execution
- OrderResult with fill_price and status
- Integration point for notifying PnLTracker on order fills

**NOTE on open_positions_count and total_exposure:**
Story 4.6 review added TODO comments for these untracked fields. They should be tracked in PnLTracker (this story) and exposed via PnLTrackerRegistry for ValidatedZmqAdapter to query. These are NOT stored in RiskState to avoid coupling P&L tracking with risk state.

**Key files to reference:**
- `services/trading-engine/src/accounts/risk_state.py` - RiskState dataclass
- `services/trading-engine/src/accounts/risk_registry.py` - RiskStateRegistry
- `services/trading-engine/src/accounts/risk_manager.py` - AccountRiskManager
- `services/trading-engine/src/accounts/metrics_service.py` - AccountMetricsService
- `services/trading-engine/src/adapters/zmq_adapter.py` - Tick receiving and account_info handling

### EXISTING ARCHITECTURE PATTERNS

**Current Tick Flow:**
```
MT5 EA -> mt5-bridge -> ZmqAdapter.receive_ticks() -> (currently just yields tick)
```

**After This Story:**
```
MT5 EA -> mt5-bridge -> ZmqAdapter.receive_ticks()
                              |
                              v
                    PnLTrackerRegistry.on_tick_all(symbol, bid, ask)
                              |
            +-----------------+-----------------+
            |                 |                 |
            v                 v                 v
      PnLTracker-A      PnLTracker-B      PnLTracker-C
      (FTMO account)    (5ers account)    (Personal)
            |                 |                 |
            v                 v                 v
    RiskStateRegistry.update_account_equity(account_id, new_equity)
```

**Current Order Execution Flow:**
```
Strategy -> ValidatedZmqAdapter.send_order() -> ZmqAdapter -> MT5
                                                    |
                                              OrderResult
```

**After This Story:**
```
Strategy -> ValidatedZmqAdapter.send_order() -> ZmqAdapter -> MT5
                  |                                   |
                  v                             OrderResult
        PnLTracker.on_trade_executed(result, order)
```

### P&L CALCULATION FORMULAS (From Context7 NautilusTrader Research)

**Unrealized P&L Calculation:**
```python
# For standard instruments
# LONG: unrealized_pnl = (current_price - entry_price) * volume * multiplier
# SHORT: unrealized_pnl = (entry_price - current_price) * volume * multiplier

# Use mark-to-market price (worst exit price for conservative valuation):
# - LONG positions: use current BID (selling to close at lower price)
# - SHORT positions: use current ASK (buying to cover at higher price)
# This is conservative and accounts for spread
```

**Realized P&L Calculation:**
```python
# On position close
# LONG: realized_pnl = (exit_price - entry_price) * closed_volume * multiplier
# SHORT: realized_pnl = (entry_price - exit_price) * closed_volume * multiplier
```

**Equity Calculation:**
```python
# Current equity = Balance + Total Unrealized P&L
# Balance = Starting balance + All realized P&L from closed trades
# Total Unrealized = Sum of unrealized P&L from all open positions
```

### INSTRUMENT MULTIPLIER HANDLING

**For MVP:** Use default multiplier of `Decimal("1.0")` for all forex pairs. Standard forex lot size is 100,000 units, but MT5 already accounts for this in the price/volume relationship.

```python
# MVP implementation - default multiplier
def get_multiplier(symbol: str) -> Decimal:
    """Get instrument multiplier. Default 1.0 for forex pairs."""
    # Future: Load from services/trading-engine/src/config/instruments.yaml
    return Decimal("1.0")
```

**Future Enhancement:** Add instrument configuration file at `services/trading-engine/src/config/instruments.yaml` with per-symbol multipliers for indices, commodities, etc.

### ACCOUNT ISOLATION REQUIREMENTS (From Story 3.5)

**CRITICAL:** Each account's PnLTracker MUST be completely isolated:
- Own internal state (positions dict, daily P&L counters)
- No shared mutable state between trackers
- Update to Account A's equity must NOT affect Account B
- Use per-account locks for thread safety if needed

**Pattern from RiskStateRegistry:**
```python
class PnLTrackerRegistry:
    def __init__(self):
        self._trackers: dict[str, PnLTracker] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, account_id: str) -> asyncio.Lock:
        return self._locks.setdefault(account_id, asyncio.Lock())

    async def on_tick_all(self, symbol: str, bid: Decimal, ask: Decimal) -> None:
        # Update all trackers that have positions in this symbol
        for account_id, tracker in self._trackers.items():
            if tracker.has_position_for_symbol(symbol):
                async with self._get_lock(account_id):
                    await tracker.on_tick(symbol, bid, ask)
```

### DECIMAL PRECISION REQUIREMENTS

**CRITICAL:** All financial calculations MUST use Decimal, never float:
```python
from decimal import Decimal

# CORRECT
price = Decimal("1850.25")
volume = Decimal("0.10")
pnl = (price - entry_price) * volume

# WRONG - DO NOT USE FLOATS
price = 1850.25  # BAD: floating point errors
pnl = (price - entry_price) * volume  # BAD: imprecise
```

**Decimal conversion from ticks:**
```python
async def on_tick(self, symbol: str, bid: float, ask: float) -> None:
    # Convert to Decimal immediately at boundary
    bid_decimal = Decimal(str(bid))
    ask_decimal = Decimal(str(ask))
    # All internal calculations use Decimal
```

### PERFORMANCE REQUIREMENTS (NFR-Based)

**From Architecture NFR2:** Rule validation < 50ms
**This Story:** P&L update per tick < 10ms (to stay well under budget)

**Performance monitoring pattern:**
```python
import time

async def on_tick(self, symbol: str, bid: Decimal, ask: Decimal) -> None:
    start = time.perf_counter()

    # ... P&L calculations ...

    elapsed_ms = (time.perf_counter() - start) * 1000
    if elapsed_ms > 10:
        logger.warning(f"P&L update slow: {elapsed_ms:.1f}ms for {symbol}")
```

**Fast path optimization:**
```python
def has_position_for_symbol(self, symbol: str) -> bool:
    """Quick check before expensive calculations."""
    return any(p.symbol == symbol for p in self._positions.values())
```

### INTEGRATION WITH EXISTING COMPONENTS

**ZmqAdapter (from `src/adapters/zmq_adapter.py`):**
- Already has `receive_ticks()` async generator
- Already subscribed to `tick:` topic from mt5-bridge
- Already handles `account_info:` for balance updates via AccountMetricsService
- Need to add PnLTrackerRegistry callback for tick routing

**AccountMetricsService (from `src/accounts/metrics_service.py`):**
- Already combines balance + RiskState for metrics
- Need to enhance with real-time unrealized P&L from PnLTracker
- Already has `on_mt5_balance_update()` for balance/equity updates

**RiskStateRegistry (from `src/accounts/risk_registry.py`):**
- Already tracks daily_pnl, equity, drawdown per account
- `update_account_equity(account_id, equity)` - call on each tick update
- `record_account_trade(account_id, realized_pnl)` - call on position close

### POSITION MANAGEMENT CONSIDERATIONS

**Position ID Strategy:**
- Use `order_id` from OrderResult as position_id
- Handles partial fills: track remaining volume
- Handles adding to position: update average entry price

**Position Tracking State:**
```python
@dataclass
class Position:
    position_id: str  # order_id from original order
    symbol: str
    side: OrderSide
    volume: Decimal  # Remaining open volume
    entry_price: Decimal  # Average entry price
    current_price: Decimal  # Last mark-to-market price
    unrealized_pnl: Decimal  # Cached unrealized P&L
    open_time: datetime
```

**NOTE:** This story focuses on P&L tracking. Actual position management integration with MT5 positions (reconciliation, position discovery) is covered in Epic 5 (State Persistence & Crash Recovery).

### ANTI-PATTERNS (What NOT to Do)

| Anti-Pattern | Why It's Wrong | Instead, Do This |
|--------------|----------------|------------------|
| Use float for money | Precision errors accumulate | Always use Decimal |
| Shared state between trackers | Violates account isolation | Per-account PnLTracker instances |
| Block on tick processing | Misses ticks, creates backpressure | Async processing, fast path for no positions |
| Skip equity update to registry | Rules use stale values | Always propagate equity updates |
| Hardcode multipliers | Different instruments have different multipliers | Get from instrument config (default to 1.0 for forex) |

### CLI COMMANDS FOR TESTING

```bash
cd services/trading-engine

# Run unit tests for P&L tracker
uv run pytest tests/unit/test_pnl_tracker.py -v

# Run integration tests
uv run pytest tests/integration/test_pnl_tracking.py -v

# Performance test
uv run pytest tests/integration/test_pnl_tracking.py::test_tick_processing_performance -v

# Verify all existing risk tests still pass
uv run pytest tests/ -k "risk" -v

# Verify all account/metrics tests still pass
uv run pytest tests/ -k "accounts or metrics" -v

# Lint check
uv run ruff check src/accounts/pnl_tracker.py src/accounts/pnl_registry.py
```

### TASK DEPENDENCIES (Execute in Order)

```
Task 1 (PnLTracker) ────► Task 2 (on_tick) ────► Task 3 (on_trade)
         │                       │                      │
         │                       │                      │
         ▼                       ▼                      ▼
         │              Task 6 (ZmqAdapter) ◄───────────┤
         │                       │                      │
         │                       │                      ▼
         │                       │              Task 4 (on_close)
         │                       │                      │
         ▼                       ▼                      ▼
    Task 5 (Metrics) ◄───────────┴──────────────────────┤
         │                                              │
         ▼                                              │
    Task 7 (MetricsService) ◄───────────────────────────┘
         │
         ▼
    Tasks 8-9 (Tests) ──► Task 10 (Docs)
```

### REFERENCES

- [docs/architecture.md#Trading-Engine-Service] - Service structure and components
- [docs/architecture.md#Data-Architecture] - Redis data structures for P&L
- [docs/architecture.md#Multi-Account-Architecture] - Account isolation patterns
- [docs/epics.md#Story-4.7] - Story requirements and acceptance criteria
- [docs/sprint-artifacts/4-6-rule-validation-before-trade.md] - Order execution flow
- [docs/sprint-artifacts/3-5-per-account-risk-isolation.md] - Risk state patterns
- [src/accounts/risk_state.py] - RiskState dataclass with P&L fields
- [src/accounts/risk_registry.py] - RiskStateRegistry for per-account state
- [src/accounts/metrics_service.py] - AccountMetricsService integration point
- [src/adapters/zmq_adapter.py] - Tick receiving and routing
- [Context7 NautilusTrader 2025-01-02] - Position P&L calculation formulas

## Dev Agent Record

**Story created:** 2026-01-02 via create-story workflow

**Story validated:** 2026-01-02 via validate-create-story workflow
- Validator: Claude Opus 4.5
- Result: 3 critical issues fixed, 5 enhancements applied, 2 optimizations applied
- See: validation-report-4-7-2026-01-02.md

**Context Analysis:**
- Epic 4 progress: Stories 4.1-4.6 complete (rule engine fully operational)
- Prerequisites satisfied: RiskStateRegistry (3.5) and ValidatedZmqAdapter (4.6) ready
- ZmqAdapter already receives ticks and account_info from mt5-bridge
- AccountMetricsService already combines balance with risk state
- Need to add real-time unrealized P&L tracking to complete the picture

**Context7 Research Summary (NautilusTrader):**
- `Position.unrealized_pnl(Price price) -> Money` - calculates unrealized P&L
- Standard formula: `(exit_price - entry_price) * quantity * multiplier`
- Mark-to-market using bid (SHORT) or ask (LONG) for conservative valuation
- Realized P&L calculated on position close
- Portfolio-level P&L aggregates position-level calculations

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Context Reference

- Epic 4 stories 4.1-4.6 implementation patterns
- Context7 NautilusTrader P&L calculation research (2026-01-02)
- Architecture document multi-account and data sections
- Existing RiskState, RiskStateRegistry, AccountMetricsService implementations

### Debug Log References

N/A - No debug issues encountered during implementation.

### Completion Notes List

**Implementation completed:** 2026-01-02
- All 10 tasks completed successfully
- 24 unit tests passing
- 15 integration tests passing
- Performance tests confirm < 10ms tick processing
- All acceptance criteria verified

**Code Review (2026-01-02):**
- Reviewer: Claude Opus 4.5 (adversarial review)
- Issues found: 3 HIGH, 3 MEDIUM, 2 LOW
- All issues fixed:
  - HIGH-1: Added documentation warning to `send_order()` about P&L tracking limitation
  - HIGH-2: Added `open_positions_count` field to AccountMetrics, populated from PnLTracker
  - HIGH-3: Corrected story Dev Notes (mark-to-market: LONG uses BID, SHORT uses ASK)
  - MED-1: Updated File List to include pyproject.toml, uv.lock, metrics.py changes
  - MED-2: Fixed pytest asyncio warnings by removing global pytestmark
  - MED-3: Added ValidatedZmqAdapter integration test
  - LOW-1: Added `get_total_position_lots()` to PnLTrackerRegistry, used in validated_adapter
- Post-fix tests: 40 passing (24 unit + 16 integration)

### File List (Full Paths from Project Root)

**Files to CREATE:**
| File | Purpose |
|------|---------|
| `services/trading-engine/src/accounts/pnl_tracker.py` | PnLTracker, Position, PnLMetrics |
| `services/trading-engine/src/accounts/pnl_registry.py` | PnLTrackerRegistry |
| `services/trading-engine/tests/unit/test_pnl_tracker.py` | Unit tests |
| `services/trading-engine/tests/integration/test_pnl_tracking.py` | Integration tests |

**Files to MODIFY:**
| File | Changes |
|------|---------|
| `services/trading-engine/src/accounts/__init__.py` | Add pnl_tracker exports |
| `services/trading-engine/src/accounts/metrics.py` | Add open_positions_count field (code review fix) |
| `services/trading-engine/src/accounts/metrics_service.py` | Integrate PnLTracker, populate open_positions_count |
| `services/trading-engine/src/adapters/zmq_adapter.py` | Route ticks to PnL registry |
| `services/trading-engine/src/execution/validated_adapter.py` | Notify PnL tracker on order execution |
| `services/trading-engine/pyproject.toml` | Add pytest-asyncio and ruff dev dependencies |
| `services/trading-engine/uv.lock` | Updated lock file |

---

## Definition of Done

**Core Implementation:**
- [x] PnLTracker class created with on_tick(), on_trade_executed(), on_position_closed()
- [x] Position dataclass for tracking open positions
- [x] PnLMetrics dataclass for returning P&L state
- [x] PnLTrackerRegistry for per-account tracker management

**P&L Calculations:**
- [x] Unrealized P&L calculated correctly for LONG and SHORT positions
- [x] Realized P&L added to daily totals on position close
- [x] Equity = Balance + Total Unrealized P&L
- [x] Daily P&L = Realized + Unrealized
- [x] All calculations use Decimal (no floats)

**Integration:**
- [x] PnLTrackerRegistry receives ticks from ZmqAdapter
- [x] Equity updates propagate to RiskStateRegistry
- [x] Realized P&L recorded via record_account_trade()
- [x] AccountMetricsService includes unrealized P&L in metrics

**Performance:**
- [x] Tick processing < 10ms (measured and logged)
- [x] Fast path for symbols with no positions
- [x] No blocking operations in tick handler

**Account Isolation:**
- [x] Each account has isolated PnLTracker instance
- [x] Updates to one account don't affect others
- [x] Per-account locks prevent race conditions

**Testing:**
- [x] Unit tests for P&L calculations (LONG, SHORT, edge cases)
- [x] Integration tests for full tick -> P&L -> metrics flow
- [x] Performance tests (1000 ticks < 10 seconds)
- [x] Account isolation tests (update A, verify B unchanged)

**Acceptance Criteria Verification:**
- [x] AC1: Tick updates recalculate unrealized P&L and equity
- [x] AC2: Trade execution updates realized P&L, daily P&L, balance
- [x] AC3: Position close adds to daily totals, removes position
- [x] AC4: Metrics show equity, daily P&L, drawdown percentage
- [x] AC5: Processing under 10ms per tick
- [x] AC6: Complete account isolation maintained

---
